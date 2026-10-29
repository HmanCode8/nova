r"""语音模块自测：TTS 合成 → ASR 回读，验证本地语音链路。

不依赖麦克风：先用系统/piper 合成一段中文语音，再交给 faster-whisper 转写校验。
麦克风链路可选：设置 NOVA_MIC_TEST=1 时录 1 秒并转写（需要真实麦克风）。

运行（PowerShell）：
    $env:Path="$env:USERPROFILE\.local\bin;$env:Path"
    $env:PYTHONPATH="e:\nova-secretary"
    $env:NOVA_MODEL_DIR="$env:TEMP\nova_voice_models"
    uv run --project backend python -m backend.voice.selftest_voice
"""

from __future__ import annotations

import asyncio
import os
import sys
import wave
from pathlib import Path

import numpy as np

from backend.voice import asr, tts

SENTENCE = "帮我看看今天的邮件和日程"


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        rate = wav.getframerate()
        width = wav.getsampwidth()
        raw = wav.readframes(wav.getnframes())
    if width != 2:
        raise RuntimeError(f"仅支持 16bit wav，当前 {width * 8}bit")
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    if rate != asr.SAMPLE_RATE:
        duration = data.size / rate
        target = int(duration * asr.SAMPLE_RATE)
        data = np.interp(
            np.linspace(0, data.size, target, endpoint=False),
            np.arange(data.size),
            data,
        ).astype(np.float32)
    return data


def _wav_bytes_to_audio(data: bytes) -> np.ndarray:
    import io

    with wave.open(io.BytesIO(data), "rb") as wav:
        channels = wav.getnchannels()
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != asr.SAMPLE_RATE:
        target = int(audio.size * asr.SAMPLE_RATE / rate)
        audio = np.interp(
            np.linspace(0, audio.size, target, endpoint=False),
            np.arange(audio.size),
            audio,
        ).astype(np.float32)
    return audio


def _check(text: str, label: str, errors: list[str]) -> None:
    print(f"[{label}] 识别结果：{text}")
    if not text:
        errors.append(f"{label}：转写结果为空")
    elif not any(word in text for word in ("邮件", "日程", "今天")):
        errors.append(f"{label}：转写内容与预期不符：{text}")


async def main() -> int:
    errors: list[str] = []
    print(f"模型目录：{tts.models_dir()}")
    print(f"ASR 模型尺寸：{asr.MODEL_SIZE}")

    if sys.platform == "win32":
        print("1) 系统语音（SAPI）合成测试句……")
        wav_path = tts._sapi_wav_file(SENTENCE)
        try:
            audio = _read_wav(wav_path)
            print(f"   wav 采样点：{audio.size}（{audio.size / asr.SAMPLE_RATE:.1f}s）")
            text = await asr.transcribe(audio)
            _check(text, "SAPI→ASR", errors)
        finally:
            wav_path.unlink(missing_ok=True)

    if tts.piper_ready():
        print("2) piper 合成 → ASR……")
        audio = _wav_bytes_to_audio(tts._piper_wav_bytes(SENTENCE))
        text = await asr.transcribe(audio)
        _check(text, "piper→ASR", errors)
    else:
        print("2) piper 语音模型未就绪，跳过（播报会自动回退系统语音）")

    if os.getenv("NOVA_MIC_TEST") == "1":
        print("3) 麦克风录音 1 秒 → ASR（请对着麦说话）……")
        recorder = asr.get_recorder()
        recorder.start()
        await asyncio.sleep(1.2)
        audio = recorder.stop()
        print(f"   采集采样点：{audio.size}")
        text = await asr.transcribe(audio)
        print(f"[MIC→ASR] {text}")

    if errors:
        print("\n❌ 自测失败：")
        for item in errors:
            print(f" - {item}")
        return 1
    print("\n✅ 语音链路自测通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
