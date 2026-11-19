"""
audio.py v3 — Async mic recording + overlapped speaker playback
===============================================================
Key improvements over v2:
  1. Async record_audio()  — non-blocking, works with asyncio main loop
  2. AudioPlayer class     — plays queued WAV chunks as they arrive
                             so TTS phrase 1 plays WHILE phrase 2 synthesizes
  3. Pre-buffer 300ms      — never clips first syllable
  4. VAD block 80ms        — finer speech detection
  5. SILENCE_SECONDS 1.2s  — 0.6s faster than original 1.8s
"""

import asyncio
import io
import os
import platform
import subprocess
import threading
import time
from collections import deque

import numpy as np
import soundfile as sf
from colorama import Fore, Style
from dotenv import load_dotenv

# PortAudio is only needed for local mic (python main.py). Render / phone
# calls use Twilio/Exotel WebSockets and must start without a sound card.
try:
    import sounddevice as sd
except (OSError, ImportError):
    sd = None

load_dotenv()

SAMPLE_RATE        = int(os.getenv("AUDIO_SAMPLE_RATE",   16000))
RECORD_SECONDS     = int(os.getenv("RECORD_SECONDS",         12))
RECORD_MAX_SECONDS = int(os.getenv("RECORD_MAX_SECONDS",     40))
SILENCE_SECONDS    = float(os.getenv("SILENCE_SECONDS",    "1.2"))
SILENCE_THRESHOLD  = int(os.getenv("SILENCE_THRESHOLD",     350))
RECORD_MODE        = os.getenv("RECORD_MODE", "vad").lower()
CHANNELS           = 1
PRE_BUFFER_BLOCKS  = 4   # ~320ms look-back before speech
BARGE_IN_ENABLED   = os.getenv("BARGE_IN_ENABLED", "true").lower() == "true"
# Louder than echo from the laptop speaker; speak close to the mic to cut in.
BARGE_IN_THRESHOLD = int(os.getenv("BARGE_IN_THRESHOLD", "900"))
BARGE_IN_CONFIRM_MS = int(os.getenv("BARGE_IN_CONFIRM_MS", "280"))
BARGE_IN_GRACE_S   = float(os.getenv("BARGE_IN_GRACE_S", "0.35"))


def _require_sd():
    """Local speaker/mic only — phone bridge never needs this."""
    if sd is None:
        raise OSError(
            "PortAudio / sounddevice is not available. "
            "Use python main.py on a machine with a microphone."
        )


# ══════════════════════════════════════════════════════════════════
# AUDIO PLAYER — overlapped playback queue
# ══════════════════════════════════════════════════════════════════

class AudioPlayer:
    """
    Thread-safe queue-based audio player.
    Call enqueue(wav_bytes) as each TTS phrase arrives.
    Playback starts immediately — no need to wait for all phrases.
    This gives the user sub-1s first-audio latency.
    """

    def __init__(self, on_enqueue=None):
        self._queue   = asyncio.Queue()
        self._playing = False
        self._task    = None
        self._on_enqueue = on_enqueue  # optional: capture TTS for call recording
        self._halt = threading.Event()
        self._done_speaking = threading.Event()
        self._busy = False
        self.interrupted = False

    async def start(self):
        """Start the background playback loop."""
        self._playing = True
        self._halt.clear()
        self._done_speaking.clear()
        self.interrupted = False
        self._task    = asyncio.create_task(self._play_loop())

    async def enqueue(self, wav_bytes: bytes):
        """Add a WAV chunk to the playback queue."""
        if self._halt.is_set() or not wav_bytes:
            return
        if self._on_enqueue:
            try:
                self._on_enqueue(wav_bytes)
            except Exception:
                pass
        await self._queue.put(wav_bytes)

    async def drain(self):
        """Wait until all queued audio has finished playing."""
        await self._queue.join()
        while self._busy and not self._halt.is_set():
            await asyncio.sleep(0.02)
        self._done_speaking.set()

    async def interrupt(self):
        """Cut playback immediately (barge-in). Safe to call more than once."""
        self.interrupted = True
        self._halt.set()
        if sd is not None:
            try:
                sd.stop()
            except Exception:
                pass
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break
        self._done_speaking.set()

    def request_stop(self):
        """Thread-safe halt from the barge-in mic thread."""
        self.interrupted = True
        self._halt.set()
        if sd is not None:
            try:
                sd.stop()
            except Exception:
                pass

    async def stop(self):
        """Stop the player after queue is empty."""
        self._playing = False
        self._done_speaking.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _play_loop(self):
        while self._playing:
            try:
                wav_bytes = await asyncio.wait_for(
                    self._queue.get(), timeout=0.1)
                if self._halt.is_set():
                    self._queue.task_done()
                    continue
                await asyncio.get_event_loop().run_in_executor(
                    None, self._play_wav, wav_bytes)
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def _play_wav(self, wav_bytes: bytes):
        """Blocking WAV playback — runs in thread pool. Stops if halted."""
        if sd is None or self._halt.is_set():
            return
        self._busy = True
        try:
            data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
            sd.play(data, sr)
            while True:
                if self._halt.is_set():
                    try:
                        sd.stop()
                    except Exception:
                        pass
                    break
                try:
                    stream = sd.get_stream()
                    if stream is None or not stream.active:
                        break
                except Exception:
                    break
                time.sleep(0.02)
        except Exception as e:
            print(f"\n  {Fore.RED}❌ Playback error: {e}{Style.RESET_ALL}")
        finally:
            self._busy = False


# ══════════════════════════════════════════════════════════════════
# VAD RECORDING
# ══════════════════════════════════════════════════════════════════

def _rms(chunk: np.ndarray) -> float:
    if chunk.size == 0:
        return 0.0
    s = chunk.astype(np.float32).flatten()
    return float(np.sqrt(np.mean(s * s)))


def _record_vad_sync(output_path: str, on_pcm=None, stop_early=None) -> str | None:
    """
    Synchronous VAD recording — called via run_in_executor.
    Returns path to saved WAV or None.
    `stop_early()` may return True after a short pause once live STT has a final.
    """
    block_ms          = 80
    block_size        = int(SAMPLE_RATE * block_ms / 1000)
    silence_blocks    = int(SILENCE_SECONDS / (block_ms / 1000))
    early_blocks      = max(3, int(0.40 / (block_ms / 1000)))
    min_speech_blocks = max(1, int(0.35 / (block_ms / 1000)))
    max_blocks        = int(RECORD_MAX_SECONDS / (block_ms / 1000))

    def _emit(frame):
        if not on_pcm:
            return
        try:
            on_pcm(np.ascontiguousarray(frame).tobytes())
        except Exception:
            pass

    pre_buffer    = deque(maxlen=PRE_BUFFER_BLOCKS)
    frames        = []
    silent_run    = 0
    heard_speech  = False
    speech_blocks = 0
    dot_count     = 0

    try:
        _require_sd()
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=block_size,
        ) as stream:
            for _ in range(max_blocks):
                block, _ = stream.read(block_size)
                block     = block.copy()
                loudness  = _rms(block)

                if loudness >= SILENCE_THRESHOLD:
                    if not heard_speech:
                        for pre in pre_buffer:
                            frames.append(pre)
                            _emit(pre)
                        heard_speech = True
                    frames.append(block)
                    _emit(block)
                    speech_blocks += 1
                    silent_run     = 0
                    dot_count      = (dot_count + 1) % 4
                    bar = "●" * (dot_count + 1) + "○" * (3 - dot_count)
                    print(f"  {Fore.CYAN}[{bar}] recording...{Style.RESET_ALL}   ",
                          end="\r", flush=True)
                else:
                    pre_buffer.append(block)
                    if heard_speech:
                        frames.append(block)
                        _emit(block)
                        silent_run += 1
                        rem = max(0, silence_blocks - silent_run)
                        print(
                            f"  {Fore.YELLOW}[····] pause "
                            f"{rem * block_ms / 1000:.1f}s...{Style.RESET_ALL}   ",
                            end="\r", flush=True,
                        )
                        enough = speech_blocks >= min_speech_blocks
                        if silent_run >= silence_blocks and enough:
                            break
                        if (stop_early and enough
                                and silent_run >= early_blocks):
                            try:
                                if stop_early():
                                    break
                            except Exception:
                                pass

        print(f"{'  ' * 25}", end="\r")

        if not frames:
            print(f"  {Fore.YELLOW}⚠️  Nothing detected — speak closer to mic.{Style.RESET_ALL}")
            return None

        audio = np.concatenate(frames, axis=0)
        dur   = len(audio) / SAMPLE_RATE

        if dur < 0.25:
            print(f"  {Fore.YELLOW}⚠️  Too short — say a bit more.{Style.RESET_ALL}")
            return None

        sf.write(output_path, audio, SAMPLE_RATE)
        print(f"  {Fore.GREEN}✅  Captured {dur:.1f}s of speech.{Style.RESET_ALL}")
        return output_path

    except KeyboardInterrupt:
        print(f"\n  {Fore.YELLOW}⏹  Stopped.{Style.RESET_ALL}")
        if frames:
            audio = np.concatenate(frames, axis=0)
            if len(audio) / SAMPLE_RATE >= 0.25:
                sf.write(output_path, audio, SAMPLE_RATE)
                return output_path
        return None

    except Exception as e:
        print(f"\n  {Fore.RED}❌ Recording error: {e}{Style.RESET_ALL}")
        return None


def _record_fixed_sync(output_path: str, duration: int) -> str | None:
    print(f"\n  {Fore.GREEN}🎤  Recording {duration}s...{Style.RESET_ALL}\n")
    try:
        _require_sd()
        audio = sd.rec(int(duration * SAMPLE_RATE),
                       samplerate=SAMPLE_RATE,
                       channels=CHANNELS,
                       dtype="int16")
        for i in range(duration, 0, -1):
            print(f"  ⏱  {i}s ...", end="\r", flush=True)
            time.sleep(1)
        sd.wait()
        sf.write(output_path, audio, SAMPLE_RATE)
        print(f"  {Fore.GREEN}✅  Done!{' ' * 20}{Style.RESET_ALL}")
        return output_path
    except Exception as e:
        print(f"\n  {Fore.RED}❌ {e}{Style.RESET_ALL}")
        return None


async def record_audio(output_path: str = "user_input.wav",
                       duration: int = None, on_pcm=None,
                       stop_early=None) -> str | None:
    """
    Async wrapper — runs blocking audio recording in thread pool
    so the asyncio event loop stays free.
    `on_pcm(bytes)` is called from the audio thread for each captured block.
    """
    print(f"\n  {Fore.GREEN}🎤  Listening... speak naturally.{Style.RESET_ALL}")
    print(f"  {Fore.YELLOW}    Stops after {SILENCE_SECONDS:.1f}s pause. "
          f"Ctrl+C to stop early.{Style.RESET_ALL}\n")

    loop = asyncio.get_event_loop()
    if RECORD_MODE == "fixed":
        return await loop.run_in_executor(
            None, _record_fixed_sync, output_path, duration or RECORD_SECONDS)
    return await loop.run_in_executor(
        None, _record_vad_sync, output_path, on_pcm, stop_early)


# ══════════════════════════════════════════════════════════════════
# SIMPLE PLAY (for greeting / closing — single shot)
# ══════════════════════════════════════════════════════════════════

def _barge_in_sync(player: AudioPlayer, output_path: str) -> str | None:
    """
    Listen on the mic while she talks. If the caller speaks over her, stop
    playback and capture the rest of their utterance.
    """
    if not BARGE_IN_ENABLED or sd is None:
        while not player._done_speaking.wait(0.05):
            if player._halt.is_set():
                return None
        return None

    block_ms = 80
    block_size = int(SAMPLE_RATE * block_ms / 1000)
    confirm_blocks = max(2, int(BARGE_IN_CONFIRM_MS / block_ms))
    silence_blocks = int(SILENCE_SECONDS / (block_ms / 1000))
    min_speech_blocks = max(1, int(0.30 / (block_ms / 1000)))
    max_blocks = int(RECORD_MAX_SECONDS / (block_ms / 1000))

    grace_until = time.time() + BARGE_IN_GRACE_S
    loud_run = 0
    capturing = False
    frames = []
    silent_run = 0
    speech_blocks = 0

    try:
        _require_sd()
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=block_size,
        ) as stream:
            for _ in range(max_blocks):
                if player._done_speaking.is_set() and not capturing:
                    return None
                block, _ = stream.read(block_size)
                block = block.copy()
                loudness = _rms(block)

                if not capturing:
                    if time.time() < grace_until:
                        continue
                    if loudness >= BARGE_IN_THRESHOLD:
                        loud_run += 1
                        if loud_run >= confirm_blocks:
                            capturing = True
                            player.request_stop()
                            frames.append(block)
                            speech_blocks = 1
                            print(f"\n  {Fore.CYAN}⏩  Interrupted — listening.{Style.RESET_ALL}")
                    else:
                        loud_run = 0
                    continue

                if loudness >= SILENCE_THRESHOLD:
                    frames.append(block)
                    speech_blocks += 1
                    silent_run = 0
                else:
                    frames.append(block)
                    silent_run += 1
                    if silent_run >= silence_blocks and speech_blocks >= min_speech_blocks:
                        break

        if not capturing or not frames:
            return None
        audio = np.concatenate(frames, axis=0)
        if len(audio) / SAMPLE_RATE < 0.25:
            return None
        sf.write(output_path, audio, SAMPLE_RATE)
        print(f"  {Fore.GREEN}✅  Captured {len(audio) / SAMPLE_RATE:.1f}s (barge-in).{Style.RESET_ALL}")
        return output_path
    except Exception as e:
        print(f"\n  {Fore.RED}❌ Barge-in: {e}{Style.RESET_ALL}")
        return None


async def listen_while_playing(player: AudioPlayer, output_path: str) -> str | None:
    """Watch the mic during TTS. Returns a WAV path if the caller cut in."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _barge_in_sync, player, output_path)


async def play_wav_bytes(wav_bytes: bytes):
    """Play a single WAV (async wrapper)."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _play_bytes_sync, wav_bytes)


def _play_bytes_sync(wav_bytes: bytes):
    if sd is None:
        return
    try:
        data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        sd.play(data, sr)
        sd.wait()
    except Exception as e:
        system = platform.system()
        tmp = "_tmp_play.wav"
        with open(tmp, "wb") as f:
            f.write(wav_bytes)
        try:
            if system == "Windows":
                os.startfile(tmp); time.sleep(3)
            elif system == "Darwin":
                subprocess.call(["afplay", tmp])
            else:
                subprocess.call(["aplay", tmp])
        except Exception:
            print(f"  {Fore.RED}❌ Playback error: {e}{Style.RESET_ALL}")
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


def get_audio_duration(path: str) -> float:
    try:
        return round(sf.info(path).duration, 2)
    except Exception:
        return 0.0


def check_microphone() -> bool:
    if sd is None:
        print(f"{Fore.YELLOW}⚠️  No PortAudio — skipping mic check (phone/cloud mode).{Style.RESET_ALL}")
        return False
    try:
        devs = sd.query_devices()
        if any(d["max_input_channels"] > 0 for d in devs):
            d = sd.query_devices(kind="input")
            print(f"{Fore.GREEN}✅ Microphone: {d['name']}{Style.RESET_ALL}")
            return True
        print(f"{Fore.RED}❌ No microphone found!{Style.RESET_ALL}")
        return False
    except Exception as e:
        print(f"{Fore.RED}❌ Mic check failed: {e}{Style.RESET_ALL}")
        return False
