"""
core/tts_service.py — TTS router (Sarvam default, ElevenLabs for Spanish)
"""

import asyncio, base64, io, os, re, time
import aiohttp, numpy as np, soundfile as sf
from colorama import Fore, Style
from dotenv import load_dotenv

from core.elevenlabs_service import uses_elevenlabs_tts, uses_fish_tts

load_dotenv()

SARVAM_KEY      = os.getenv("SARVAM_API_KEY","")
STT_URL         = "https://api.sarvam.ai/speech-to-text"
TTS_URL         = "https://api.sarvam.ai/text-to-speech"
HEADERS         = {"api-subscription-key": SARVAM_KEY}
TTS_SAMPLE_RATE = int(os.getenv("TTS_SAMPLE_RATE","16000"))
TTS_TEMPERATURE = float(os.getenv("TTS_TEMPERATURE","0.75"))
TTS_PAUSE_MS    = int(os.getenv("TTS_PAUSE_MS","420"))
STT_TIMEOUT     = int(os.getenv("STT_TIMEOUT","30"))
TTS_TIMEOUT     = int(os.getenv("TTS_TIMEOUT","30"))


# ── One pooled connection to Sarvam, not one per phrase ───────────
#
# Every TTS and STT call used to open its own aiohttp.ClientSession, which
# means a fresh TCP connect and TLS handshake to api.sarvam.ai each time. A
# greeting is three phrases and an ordinary turn is another two to four, so a
# call paid that handshake a dozen times over. Reusing one pooled session keeps
# the connection alive between phrases and takes the setup cost to zero after
# the first request.
#
# The session is bound to the loop that created it, so it is rebuilt if it is
# ever used from a different one — that only happens in tests, where the old
# session's connector is dropped with the loop it belonged to.
_http_session: aiohttp.ClientSession | None = None
_http_loop = None


def _sarvam_session() -> aiohttp.ClientSession:
    """Shared, keep-alive session for both Sarvam endpoints."""
    global _http_session, _http_loop
    loop = asyncio.get_running_loop()
    if _http_session is None or _http_session.closed or _http_loop is not loop:
        _http_session = aiohttp.ClientSession(
            headers=HEADERS,
            connector=aiohttp.TCPConnector(
                limit=32, ttl_dns_cache=300, keepalive_timeout=90,
            ),
        )
        _http_loop = loop
    return _http_session


async def close_http_session():
    """Release the pooled session. Safe to call when one was never opened."""
    global _http_session, _http_loop
    if _http_session is not None and not _http_session.closed:
        await _http_session.close()
    _http_session = None
    _http_loop = None


async def speech_to_text(audio_path: str, language: str = "fr-FR") -> dict:
    if not SARVAM_KEY: raise ValueError("SARVAM_API_KEY not set!")
    print(f"  {Fore.CYAN}🎙️  STT...{Style.RESET_ALL}",end="",flush=True)
    start = time.time()
    with open(audio_path,"rb") as f: audio_bytes = f.read()
    data = aiohttp.FormData()
    data.add_field("file",audio_bytes,filename=os.path.basename(audio_path),content_type="audio/wav")
    data.add_field("model","saaras:v3"); data.add_field("language_code",language); data.add_field("mode","transcribe")
    try:
        session = _sarvam_session()
        async with session.post(STT_URL,data=data,timeout=aiohttp.ClientTimeout(total=STT_TIMEOUT)) as resp:
            latency = time.time()-start
            if resp.status != 200:
                body = await resp.text()
                print(f"\n  {Fore.RED}❌ STT {resp.status}: {body}{Style.RESET_ALL}")
                return {"transcript":"","error":body}
            body = await resp.json(content_type=None)
            transcript = body.get("transcript","").strip()
            duration   = body.get("duration",0) or 0
            print(f" {Fore.GREEN}✅ {latency:.2f}s{Style.RESET_ALL}")
            if transcript: print(f"  {Fore.YELLOW}📝  \"{transcript}\"{Style.RESET_ALL}")
            else: print(f"  {Fore.YELLOW}⚠️  Empty — speak louder.{Style.RESET_ALL}")
            return {"transcript":transcript,"language":language,"duration":duration,
                    "latency":round(latency,3),"cost_inr":round(duration*(30/3600),4)}
    except asyncio.TimeoutError:
        print(f"\n  {Fore.RED}❌ STT timeout{Style.RESET_ALL}")
        return {"transcript":"","error":"timeout"}
    except Exception as e:
        print(f"\n  {Fore.RED}❌ STT error: {e}{Style.RESET_ALL}")
        return {"transcript":"","error":str(e)}


async def synthesize_phrase(text: str, language: str = "fr-FR",
                             speaker: str = "priya", pace: float = 0.82,
                             temperature: float | None = None,
                             model_hint: str | None = None) -> bytes | None:
    """
    Synthesize ONE phrase. Routes to Fish → ElevenLabs → Sarvam by language.

    `temperature` comes from the language pack's TTS_CONFIG so each language
    keeps its own tuning (Marathi is deliberately warmer than English).

    `model_hint` is forwarded to ElevenLabs so the French pack can elect
    eleven_turbo_v2_5 (~35% faster) without changing .env.

    Fallback chain
    ──────────────
    Fish failure  → falls back to Sarvam (or ElevenLabs for ES/FR).
    ElevenLabs 4xx/timeout → falls back to Sarvam when SARVAM_KEY is set.
    Sarvam failure → logs and returns None (caller gets silence; acceptable
    once per call, not acceptable as the steady state).

    Before this fix, any provider returning None propagated straight to the
    AudioPlayer queue as empty — the caller heard silence and assumed the call
    dropped.
    """
    if not text or not text.strip():
        return None

    # ── Fish ─────────────────────────────────────────────────────────────
    if uses_fish_tts(language):
        from core.fish_service import synthesize_phrase as fish_tts
        wav = await fish_tts(text, language, pace=pace, temperature=temperature)
        if wav:
            return wav
        # Fish failed — fall through to Sarvam as backup (works for HI/EN/MR;
        # for FR/ES Sarvam won't have the right model, so we log and return None
        # rather than sending broken audio).
        base = (language or "").split("-")[0].lower()
        if base in ("fr", "es"):
            print(f"\n  {Fore.YELLOW}⚠️  Fish TTS failed for {language} — no Sarvam fallback available{Style.RESET_ALL}")
            return None
        print(f"\n  {Fore.YELLOW}⚠️  Fish TTS failed — falling back to Sarvam{Style.RESET_ALL}")

    # ── ElevenLabs ───────────────────────────────────────────────────────
    if uses_elevenlabs_tts(language):
        from core.elevenlabs_service import synthesize_phrase as eleven_tts
        wav = await eleven_tts(text, language, model_hint=model_hint)
        if wav:
            return wav
        # ElevenLabs failed — try Sarvam if we have a key (FR/ES voices won't
        # sound right on Sarvam, but silence is worse than a mismatch voice).
        if not SARVAM_KEY:
            return None
        print(f"\n  {Fore.YELLOW}⚠️  ElevenLabs TTS failed — falling back to Sarvam{Style.RESET_ALL}")

    # ── Sarvam (primary for HI/MR/EN, fallback for others) ──────────────
    temp = TTS_TEMPERATURE if temperature is None else float(temperature)
    payload = {"text": text.strip(), "target_language_code": language,
               "model": "bulbul:v3", "speaker": speaker,
               "speech_sample_rate": str(TTS_SAMPLE_RATE),
               "enable_preprocessing": True, "pace": pace, "temperature": temp}
    for attempt in range(2):
        try:
            s = _sarvam_session()
            async with s.post(TTS_URL, json=payload,
                              timeout=aiohttp.ClientTimeout(total=TTS_TIMEOUT)) as resp:
                if resp.status == 200:
                    body = await resp.json(content_type=None)
                    return base64.b64decode(body.get("audios", [""])[0])
                if resp.status >= 500 and attempt == 0:
                    await asyncio.sleep(0.4)
                    continue
                body = await resp.text()
                print(f"\n  {Fore.RED}❌ TTS {resp.status}: {body}{Style.RESET_ALL}")
                return None
        except asyncio.TimeoutError:
            print(f"\n  {Fore.RED}❌ TTS timeout{Style.RESET_ALL}")
            return None
        except Exception as e:
            print(f"\n  {Fore.RED}❌ TTS: {e}{Style.RESET_ALL}")
            return None
    return None


async def text_to_speech_full(text: str, language: str = "fr-FR",
                               speaker: str = "priya", pace: float = 0.82,
                               temperature: float | None = None,
                               pause_ms: int | None = None,
                               model_hint: str | None = None) -> dict:
    """
    Synthesize full text → merged WAV bytes (for greeting / closing / emergency).

    Sentences are synthesized concurrently — this used to be a serial for-loop,
    which meant the emergency line, the most urgent message in the product, had
    the highest latency.

    `model_hint` is forwarded to synthesize_phrase so French turbo routing
    applies to greeting / closing synthesis as well as mid-call phrases.
    """
    if not text or not text.strip():
        return {"wav_bytes": None, "char_count": 0, "cost_inr": 0}
    print(f"  {Fore.CYAN}🔊  TTS (full)...{Style.RESET_ALL}", end="", flush=True)
    start = time.time()
    sentences = _split_sentences(text)
    results = await asyncio.gather(
        *(synthesize_phrase(s, language, speaker, pace, temperature,
                            model_hint=model_hint) for s in sentences),
        return_exceptions=True,
    )
    parts = [w for w in results if isinstance(w, (bytes, bytearray)) and w]
    if not parts:
        return {"wav_bytes": None, "char_count": 0, "cost_inr": 0}
    gap = TTS_PAUSE_MS if pause_ms is None else int(pause_ms)
    merged = _merge_wav(parts, pause_ms=gap)
    print(f" {Fore.GREEN}✅ {time.time()-start:.2f}s{Style.RESET_ALL}")
    return {"wav_bytes": merged, "char_count": len(text),
            "cost_inr": round(len(text) * (30 / 10000), 4),
            "latency": round(time.time() - start, 3)}


# ── Fixed-phrase cache ───────────────────────────────────────────
# Thinking sounds ("हं...", "Right...") are a tiny fixed set that used to be
# re-synthesized over the network every time the watchdog fired — a full TTS
# round trip on top of the silence that had already elapsed. Caching them makes
# the filler instant, which is the whole point of having one.

_PHRASE_CACHE: dict[tuple, bytes] = {}


def _cache_key(text, language, speaker, pace, temperature, model_hint=None):
    return (text.strip(), language, speaker, round(float(pace), 3),
            None if temperature is None else round(float(temperature), 3),
            (model_hint or "").strip() or None)


async def synthesize_cached(text: str, language: str = "fr-FR",
                             speaker: str = "priya", pace: float = 0.82,
                             temperature: float | None = None,
                             model_hint: str | None = None) -> bytes | None:
    """synthesize_phrase() for short, repeated, fixed strings."""
    if not text or not text.strip():
        return None
    key = _cache_key(text, language, speaker, pace, temperature, model_hint)
    hit = _PHRASE_CACHE.get(key)
    if hit is not None:
        return hit
    wav = await synthesize_phrase(text, language, speaker, pace, temperature,
                                  model_hint=model_hint)
    if wav:
        _PHRASE_CACHE[key] = wav
    return wav


async def prewarm_phrases(texts, language: str = "fr-FR",
                           speaker: str = "priya", pace: float = 0.82,
                           temperature: float | None = None,
                           model_hint: str | None = None) -> int:
    """
    Synthesize a set of fixed phrases up front so the first use costs nothing.
    Safe to call more than once — already-cached phrases are skipped.
    Failures are swallowed: a cold cache only means the old (slower) behaviour.
    `model_hint` is forwarded to synthesize_phrase so French turbo caching
    uses the same model the live call will use (cache key includes the hint).
    """
    todo = [t for t in dict.fromkeys(texts or []) if t and t.strip()
            and _cache_key(t, language, speaker, pace, temperature, model_hint)
            not in _PHRASE_CACHE]
    if not todo:
        return 0
    await asyncio.gather(
        *(synthesize_cached(t, language, speaker, pace, temperature, model_hint)
          for t in todo),
        return_exceptions=True,
    )
    return sum(
        1 for t in todo
        if _cache_key(t, language, speaker, pace, temperature, model_hint) in _PHRASE_CACHE
    )


_SENT = re.compile(r"(?<=[.!?।…])\s+")

# Common abbreviations whose trailing dot must NOT be treated as a sentence
# boundary. Covers French (M., Mme., Dr., etc.), English (Mr., Mrs., Dr., St.),
# Spanish (Sr., Sra., Dr.) and Hindi/Marathi romanised titles.
_ABBREV = re.compile(
    r"\b(M|Mme|Mlle|Dr|Me|Prof|Sr|Sra|Mr|Mrs|Ms|St|Etc|etc|vs|Jr|Yr|no|No)\.$",
    re.IGNORECASE,
)


def _split_sentences(text, max_chars=490):
    """
    Split `text` into synthesisable phrases at sentence boundaries.

    Abbreviation guard: a dot that ends a known abbreviation (M., Dr., etc.)
    is NOT treated as a sentence boundary — we re-join the fragment with the
    next part before emitting. Without this, "M. Dupont a confirmé." split
    into ["M.", "Dupont a confirmé."], and TTS gave "M." its own sentence-final
    intonation contour, sounding clipped and broken.
    """
    raw_parts = [p.strip() for p in _SENT.split(text.strip()) if p.strip()]
    if not raw_parts:
        return _chunk(text, max_chars)

    # Re-join fragments that ended with an abbreviation dot.
    merged: list[str] = []
    pending = ""
    for part in raw_parts:
        if pending:
            part = pending + " " + part
            pending = ""
        if _ABBREV.search(part):
            pending = part          # hold — this dot wasn't a sentence end
        else:
            merged.append(part)
    if pending:                     # trailing abbreviation — keep as-is
        merged.append(pending)

    if not merged:
        return _chunk(text, max_chars)

    result = []
    for p in merged:
        result.extend([p] if len(p) <= max_chars else _chunk(p, max_chars))
    return result

def _chunk(text,max_chars=490):
    if len(text)<=max_chars: return [text]
    chunks,cur = [],""
    for w in text.split():
        if len(cur)+len(w)+1<=max_chars: cur += (" "+w) if cur else w
        else: chunks.append(cur); cur=w
    if cur: chunks.append(cur)
    return chunks

def _merge_wav(wav_list,pause_ms=420):
    if not wav_list: return b""
    if len(wav_list)==1: return wav_list[0]
    segs,sr = [],None
    for raw in wav_list:
        data,r = sf.read(io.BytesIO(raw),dtype="float32")
        if sr is None: sr=r
        if data.ndim>1: data=data.mean(axis=1)
        segs.append(data)
        segs.append(np.zeros(int(sr*pause_ms/1000),dtype=np.float32))
    segs.pop()
    buf = io.BytesIO()
    sf.write(buf,np.concatenate(segs),sr,format="WAV",subtype="PCM_16")
    return buf.getvalue()
