"""本地语音合成（TTS）：piper 中文语音优先，系统内置语音兜底。

- 首选 piper（zh_CN-huayan-medium），完全离线；语音模型缓存在
  %APPDATA%/NovaSecretary/models/piper/
- 国内网络访问 HuggingFace 常超时，因此 piper 模型下载放在后台尝试，
  下载成功前自动回退 Windows SAPI（Microsoft Huihui 中文语音）/ macOS say
- 所有合成与播放都在本机完成，不上传云端
"""

from __future__ import annotations

import io
import logging
import os
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path
from typing import Optional

from backend.voice import models_dir

VOICE_NAME = (os.getenv("NOVA_PIPER_VOICE") or "zh_CN-huayan-medium").strip()
MODEL_ROOT = models_dir() / "piper"
VOICE_ONNX = MODEL_ROOT / f"{VOICE_NAME}.onnx"
VOICE_JSON = MODEL_ROOT / f"{VOICE_NAME}.onnx.json"

# 按顺序尝试的下载源；可用 NOVA_PIPER_BASE_URL 指定自建镜像
_VOICE_PATH = f"zh/zh_CN/huayan/medium/{VOICE_NAME}"
MIRRORS = [
    os.getenv("NOVA_PIPER_BASE_URL") or "",
    "https://hf-mirror.com/rhasspy/piper-voices/resolve/main",
    "https://huggingface.co/rhasspy/piper-voices/resolve/main",
]

MAX_SPEAK_CHARS = 600

_voice = None
_voice_lock = threading.Lock()
_play_lock = threading.Lock()
_download_tried = False
_download_lock = threading.Lock()


logger = logging.getLogger("nova.tts")


def _log(message: str) -> None:
    logger.info(message)


def piper_ready() -> bool:
    return VOICE_ONNX.is_file() and VOICE_JSON.is_file()


def _download(url: str, target: Path) -> None:
    import urllib.request

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "NovaSecretary/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response, open(temp, "wb") as handle:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            handle.write(chunk)
    temp.replace(target)


def try_download_voice() -> bool:
    """后台尝试下载 piper 中文语音（多次尝试失败后本进程不再重试）。"""
    global _download_tried
    with _download_lock:
        if piper_ready():
            return True
        if _download_tried:
            return False
        _download_tried = True
    if os.getenv("NOVA_PIPER_DOWNLOAD") == "0":  # 自测 / 离线环境跳过下载
        return False
    for base in MIRRORS:
        if not base:
            continue
        try:
            for suffix, target in ((".onnx", VOICE_ONNX), (".onnx.json", VOICE_JSON)):
                if not target.is_file():
                    _download(f"{base.rstrip('/')}/{_VOICE_PATH}{suffix}", target)
            _log(f"piper 语音已就绪：{VOICE_ONNX}")
            return True
        except Exception as exc:
            _log(f"piper 语音下载失败（{base}）：{exc}")
    _log("piper 语音不可用，将使用系统内置语音播报")
    return False


def _load_voice():
    global _voice
    if _voice is not None:
        return _voice
    with _voice_lock:
        if _voice is None:
            from piper.voice import PiperVoice

            _voice = PiperVoice.load(str(VOICE_ONNX), config_path=str(VOICE_JSON))
    return _voice


def _clean_text(text: str) -> str:
    """去掉 markdown 符号，避免把 #、*、链接地址念出来。"""
    import re

    value = text or ""
    value = re.sub(r"```[\s\S]*?```", " 代码省略。 ", value)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"[*_>#~]+", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > MAX_SPEAK_CHARS:
        value = value[:MAX_SPEAK_CHARS] + "。"
    return value


def _piper_wav_bytes(text: str) -> bytes:
    voice = _load_voice()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)
    return buffer.getvalue()


def _sapi_wav_file(text: str) -> Path:
    """Windows 系统语音（System.Speech）合成到 wav，离线可用。"""
    out = Path(tempfile.gettempdir()) / f"nova_tts_{os.getpid()}_{threading.get_ident()}.wav"
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$zh = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'zh*' }"
        " | Select-Object -First 1;"
        "if ($zh) { $s.SelectVoice($zh.VoiceInfo.Name) };"
        f"$s.SetOutputToWaveFile('{str(out).replace(chr(39), chr(39) * 2)}');"
        "$s.Speak($env:NOVA_TTS_TEXT);"
        "$s.Dispose();"
    )
    env = dict(os.environ, NOVA_TTS_TEXT=text)
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        env=env,
        capture_output=True,
        timeout=90,
    )
    if completed.returncode != 0 or not out.is_file():
        detail = completed.stderr.decode("utf-8", "ignore")[:200]
        raise RuntimeError(f"系统语音合成失败：{detail or '未知错误'}")
    return out


def _play_wav_bytes(data: bytes) -> None:
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
        return
    _play_file_bytes(data)


def _play_file_bytes(data: bytes) -> None:
    suffix = ".wav"
    handle, path = tempfile.mkstemp(suffix=suffix)
    os.close(handle)
    try:
        Path(path).write_bytes(data)
        _play_file(Path(path))
    finally:
        Path(path).unlink(missing_ok=True)


def _play_file(path: Path) -> None:
    if sys.platform == "darwin":
        cmd = ["afplay", str(path)]
    elif sys.platform.startswith("linux"):
        cmd = ["aplay", "-q", str(path)]
    else:
        cmd = ["powershell", "-NoProfile", "-Command", f"(New-Object Media.SoundPlayer '{path}').PlaySync()"]
    subprocess.run(cmd, capture_output=True, timeout=120)


def speak_blocking(text: str) -> str:
    """阻塞播报，返回实际使用的引擎（piper / sapi / say）。"""
    content = _clean_text(text)
    if not content:
        return "skipped"
    with _play_lock:
        if piper_ready():
            audio = _piper_wav_bytes(content)
            _play_wav_bytes(audio)
            return "piper"
        if sys.platform == "win32":
            wav_path = _sapi_wav_file(content)
            try:
                _play_file(wav_path)
            finally:
                wav_path.unlink(missing_ok=True)
            return "sapi"
        if sys.platform == "darwin":
            subprocess.run(["say", "-v", "Tingting", content], capture_output=True, timeout=120)
            return "say"
        raise RuntimeError("当前平台没有可用的本地 TTS 引擎")


def warmup() -> None:
    """服务启动后台预热：尝试补 piper 语音并加载（失败静默回退系统语音）。"""
    try:
        if try_download_voice():
            _load_voice()
    except Exception as exc:
        _log(f"piper 预热失败：{exc}")
