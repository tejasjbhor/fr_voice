"""
core/call_recorder.py — Merge user mic + AI TTS into one call recording
Saved under recordings/ as a single chronological WAV.
"""

import io
import os
from datetime import datetime

import numpy as np
import soundfile as sf
from colorama import Fore, Style
from dotenv import load_dotenv

load_dotenv()

SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
RECORD_CALL = os.getenv("RECORD_CALL", "true").lower() == "true"
RECORDINGS_DIR = os.getenv("RECORDINGS_DIR", "recordings")


class CallRecorder:
    """Appends WAV chunks in call order: greeting → user → sathi → … → closing."""

    def __init__(self, session_id: str, user_name: str = "user"):
        self.enabled = RECORD_CALL
        self.session_id = session_id
        self.user_name = user_name
        self._parts: list[np.ndarray] = []
        self._sr = SAMPLE_RATE
        self._saved_path: str | None = None
        os.makedirs(RECORDINGS_DIR, exist_ok=True)

    def append_silence(self, ms: int = 400):
        if not self.enabled:
            return
        n = int(self._sr * ms / 1000)
        if n > 0:
            self._parts.append(np.zeros(n, dtype=np.float32))

    def append_wav_bytes(self, wav_bytes: bytes | None):
        if not self.enabled or not wav_bytes:
            return
        try:
            data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
            self._append_audio(data, sr)
        except Exception as e:
            print(f"  {Fore.YELLOW}⚠️  Recorder skip chunk: {e}{Style.RESET_ALL}")

    def append_wav_file(self, path: str | None):
        if not self.enabled or not path or not os.path.exists(path):
            return
        try:
            data, sr = sf.read(path, dtype="float32")
            self._append_audio(data, sr)
        except Exception as e:
            print(f"  {Fore.YELLOW}⚠️  Recorder skip file: {e}{Style.RESET_ALL}")

    def _append_audio(self, data: np.ndarray, sr: int):
        if data.ndim > 1:
            data = data.mean(axis=1)
        data = np.asarray(data, dtype=np.float32).flatten()
        if sr != self._sr and len(data) > 0:
            # Simple resample via linear interpolation
            duration = len(data) / float(sr)
            new_len = max(1, int(duration * self._sr))
            x_old = np.linspace(0.0, 1.0, num=len(data), endpoint=False)
            x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
            data = np.interp(x_new, x_old, data).astype(np.float32)
        if len(data) > 0:
            self._parts.append(data)

    def save(self) -> str | None:
        if not self.enabled or not self._parts:
            return self._saved_path
        if self._saved_path:
            return self._saved_path
        audio = np.concatenate(self._parts)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.user_name)
        path = os.path.join(
            RECORDINGS_DIR,
            f"call_{safe_name}_{stamp}_{self.session_id[:8]}.wav",
        )
        sf.write(path, audio, self._sr, subtype="PCM_16")
        dur = len(audio) / float(self._sr)
        self._saved_path = path
        print(f"  {Fore.GREEN}💾  Call recording saved ({dur:.1f}s): {path}{Style.RESET_ALL}")
        return path
