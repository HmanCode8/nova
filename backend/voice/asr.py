"""本地语音识别：sounddevice 录音 + faster-whisper 转写。

- 录音：16kHz / 单声道 / float32，按住说话期间持续采集，停止后一次性转写
- 模型：默认 faster-whisper base（中文）；首次使用自动下载到
  %APPDATA%/NovaSecretary/models/whisper/<size>/
- 下载源：优先 ModelScope 国内镜像（HuggingFace 直连在国内常被墙），
  可用环境变量 NOVA_WHISPER_MODEL / NOVA_WHISPER_MIRROR 覆盖

Windows 坑点：sounddevice 依赖 PortAudio 自带二进制，无需额外安装；
无麦克风或被占用时 InputStream 会抛 PortAudioError，这里统一转成中文提示。
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

from backend.voice import models_dir

SAMPLE_RATE = 16000
MAX_SECONDS = 120  # 单次录音上限，避免内存与转写时间失控
MIN_SECONDS = 0.35

MODEL_SIZE = (os.getenv("NOVA_WHISPER_MODEL") or "base").strip()
MODEL_MIRROR = (os.getenv("NOVA_WHISPER_MIRROR") or "https://modelscope.cn/models").rstrip("/")
MODEL_ROOT = models_dir() / "whisper" / MODEL_SIZE

# ModelScope 上 Systran/faster-whisper-* 为官方仓库镜像，文件结构一致
MODEL_FILES = (
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.txt",
    "preprocessor_config.json",
)

_model = None
_model_lock = threading.Lock()
_recorder: Optional["Recorder"] = None


logger = logging.getLogger("nova.asr")


def _log(message: str) -> None:
    logger.info(message)


def model_dir() -> Path:
    return MODEL_ROOT


def model_ready() -> bool:
    return (MODEL_ROOT / "model.bin").is_file()


def _download_file(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "NovaSecretary/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response, open(temp, "wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    temp.replace(target)


def ensure_model(progress=None) -> Path:
    """确保本地模型文件齐全；缺失时从 ModelScope 下载（阻塞调用）。"""
    if model_ready():
        return MODEL_ROOT
    repo = f"{MODEL_MIRROR}/Systran/faster-whisper-{MODEL_SIZE}/resolve/master"
    _log(f"开始下载 faster-whisper-{MODEL_SIZE} 到 {MODEL_ROOT}")
    for name in MODEL_FILES:
        target = MODEL_ROOT / name
        if target.is_file():
            continue
        url = f"{repo}/{name}"
        try:
            _download_file(url, target)
        except Exception as exc:
            # preprocessor_config.json 在新版 faster-whisper 里可选
            if name == "preprocessor_config.json":
                _log(f"可选文件缺失，跳过：{exc}")
                continue
            raise RuntimeError(
                f"语音模型下载失败（{name}）：{exc}\n"
                f"可手动下载 faster-whisper-{MODEL_SIZE} 模型文件放到：{MODEL_ROOT}"
            ) from exc
        if progress:
            progress(name)
    if not model_ready():
        raise RuntimeError(f"语音模型不完整，请检查目录：{MODEL_ROOT}")
    return MODEL_ROOT


def _load_model():
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        from faster_whisper import WhisperModel

        directory = ensure_model()
        _log(f"加载模型：{directory}")
        _model = WhisperModel(
            str(directory), device="cpu", compute_type="int8", local_files_only=True
        )
        _log("模型加载完成")
    return _model


def warmup() -> None:
    """预加载模型（服务启动后台调用，避免首次说话等待过久）。"""
    try:
        _load_model()
    except Exception as exc:
        _log(f"模型预热失败：{exc}")


def _transcribe_sync(audio: np.ndarray) -> str:
    if audio.size < SAMPLE_RATE * MIN_SECONDS:
        return ""
    model = _load_model()
    segments, _info = model.transcribe(
        audio,
        language="zh",
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
        initial_prompt="以下是普通话内容。",
    )
    return "".join(segment.text for segment in segments).strip()


async def transcribe(audio: np.ndarray) -> str:
    """转写录音数据（float32, 16k, mono），不阻塞事件循环。"""
    if audio is None or audio.size == 0:
        return ""
    return await asyncio.to_thread(_transcribe_sync, audio)


class Recorder:
    """按住说话录音器：start/stop 由 WebSocket 语音指令驱动。"""

    def __init__(self) -> None:
        self._stream: Optional[sd.InputStream] = None
        self._frames: list[np.ndarray] = []
        self._frames_lock = threading.Lock()
        self._level = 0.0
        self._started_at = 0.0
        self._limit_reached = False

    @property
    def recording(self) -> bool:
        return self._stream is not None

    @property
    def level(self) -> float:
        """最近一个音频块的 RMS 强度（0~1），用于前端实时波形。"""
        return self._level

    @property
    def limit_reached(self) -> bool:
        """是否已达单次录音时长上限（上层据此主动收尾转写）。"""
        return self._limit_reached

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._started_at if self._started_at else 0.0

    def start(self) -> None:
        if self._stream is not None:
            return
        self._frames = []
        self._level = 0.0
        self._limit_reached = False

        def callback(indata, _frames, _time_info, status) -> None:  # noqa: ANN001
            if status:  # 溢出等状态不中断录音
                pass
            data = np.asarray(indata, dtype=np.float32).reshape(-1).copy()
            if time.monotonic() - self._started_at > MAX_SECONDS:
                self._limit_reached = True
                return
            with self._frames_lock:
                self._frames.append(data)
            if data.size:
                rms = float(np.sqrt(np.mean(np.square(data))))
                self._level = min(1.0, rms * 6.0)

        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=800,
                callback=callback,
            )
            self._stream.start()
        except Exception as exc:  # 无设备 / 被占用 / 权限
            self._stream = None
            raise RuntimeError(f"无法打开麦克风：{exc}") from exc
        self._started_at = time.monotonic()

    def stop(self) -> np.ndarray:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        with self._frames_lock:
            frames = self._frames
            self._frames = []
        self._level = 0.0
        self._started_at = 0.0
        self._limit_reached = False
        if not frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(frames).astype(np.float32, copy=False)


def get_recorder() -> Recorder:
    global _recorder
    if _recorder is None:
        _recorder = Recorder()
    return _recorder
