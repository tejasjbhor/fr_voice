"""Provider-agnostic phone call session loop."""

import asyncio
import os
import re
import tempfile
import time

from fastapi import WebSocket, WebSocketDisconnect

from core.call_recorder import CallRecorder, RECORD_CALL
from core.alert_engine import analyse
from core.database import (
    get_session_history,
    save_alert,
    save_api_cost,
    save_conversation,
    save_health_record,
)
from core.extractor import deep_extract
from core.gladia_service import GLADIA_LIVE, LiveSession, is_french_language
from core.llm_service import stream_tokens
from core.stt_service import transcribe
from core.tts_service import (
    prewarm_phrases,
    synthesize_cached,
    text_to_speech_full,
)
from services.conversation_engine import (
    OrderedTtsQueue,
    ThinkingWatchdog,
    _clean,
    _split,
    announced_hangup,
    classify_exit,
    is_emergency,
    pick_thinking_sound,
    strip_end_signal,
    thinking_sounds_for,
)
from services.session_manager import MAX_CALL_SECONDS, SessionManager
from shared.lang import load_lang_service, voice_language
from shared.prompts import build_system
from edu import config as edu_config
from telephony.audio_utils import is_silence, pcm_8k_to_wav_16k
from telephony.barge_in import BargeInMonitor, PHONE_BARGE_IN_ENABLED, run_until_barge
from telephony.streaming_tts import StreamingTtsQueue
from core.elevenlabs_service import uses_fish_tts
from telephony.config import (
    CHUNK_SIZE,
    PHONE_SAMPLE_RATE,
    SILENCE_HANGUP_CHUNKS,
    SILENCE_PROMPT_CHUNKS,
    THINKING_MS,
    VAD_ABANDON_CHUNKS,
    VAD_LIVE_SILENCE_CHUNKS,
    VAD_MIN_SPEECH_CHUNKS,
    VAD_SILENCE_CHUNKS,
)
from telephony.log import setup_logging
from telephony.players.exotel import ExotelAudioPlayer
from telephony.players.frejun import FreJunAudioPlayer
from telephony.players.plivo import PlivoAudioPlayer
from telephony.players.twilio import TwilioAudioPlayer
from telephony.receivers.exotel import ExotelPcmReceiver
from telephony.receivers.frejun import receive_pcm_from_frejun
from telephony.receivers.plivo import PlivoPcmReceiver
from telephony.receivers.twilio import TwilioPcmReceiver

log = setup_logging()

# Runaway guard only. This used to be 2, which cut ordinary replies off
# mid-thought and silently dropped the unfinished sentence; the prompt's own
# "two sentences, three at most" discipline governs normal length.
MAX_PHRASES = int(os.getenv("MAX_REPLY_PHRASES", "4"))

# The goodbye turn is the last thing standing between the caller and the line
# dropping, so it gets a tighter cap — every extra sentence here is audio that
# has to be synthesized and played out in full before we can hang up.
FAREWELL_MAX_PHRASES = int(os.getenv("FAREWELL_MAX_PHRASES", "2"))

# Two of the farewell reasons get one sentence, not two. Somebody who has asked
# not to be called again, or who has just told us a death, does not want a
# second sentence from her — anything after the first one reads as arguing or
# as prying. The reasons are set by conversation_engine.classify_exit().
_ONE_SENTENCE_REASONS = ("declined", "bereavement")


PHONE_TTS_STREAMING = os.getenv("PHONE_TTS_STREAMING", "true").lower() == "true"


def _tts_queue(player, voice_lang: str):
    """Stream Fish audio straight to the line where the player supports it."""
    if (PHONE_TTS_STREAMING and hasattr(player, "enqueue_pcm")
            and uses_fish_tts(voice_lang)):
        return StreamingTtsQueue(player, sample_rate=PHONE_SAMPLE_RATE)
    return OrderedTtsQueue(player)


def _farewell_cap(session) -> int:
    """Sentence ceiling for the last turn, by why the call is ending."""
    if session.farewell_reason in _ONE_SENTENCE_REASONS:
        return 1
    return FAREWELL_MAX_PHRASES


# Starlette raises RuntimeError (not WebSocketDisconnect) when we touch a socket
# the caller has already dropped. These are the phrasings it uses.
_CLOSED_SOCKET_HINTS = (
    "not connected",
    "disconnect message",
    "close message",
    "websocket is closed",
)


def _is_closed_socket(exc: BaseException) -> bool:
    """True when this RuntimeError is just 'the caller is gone', not a real bug."""
    return any(hint in str(exc).lower() for hint in _CLOSED_SOCKET_HINTS)


def _build_greeting(lang_svc, name: str, history_summary) -> str:
    """Context-aware greeting, falling back to the plain constant."""
    builder = getattr(lang_svc, "build_greeting", None)
    if callable(builder):
        try:
            return builder(name, history_summary)
        except Exception as e:
            log.warning(f"build_greeting failed ({e}); using GREETING")
    return lang_svc.GREETING.format(name=name)


def _build_closing(lang_svc, name: str, context) -> str:
    """Closing matched to how the call went, falling back to the constant."""
    builder = getattr(lang_svc, "build_closing", None)
    if callable(builder):
        try:
            return builder(name, context)
        except Exception as e:
            log.warning(f"build_closing failed ({e}); using CLOSING")
    return lang_svc.CLOSING.format(name=name)


def _recovery_line(lang_svc, name: str, misses: int) -> str:
    """First miss gets 'say that again?'; the next gets 'are you still there?'."""
    if misses <= 1:
        line = getattr(lang_svc, "FALLBACK", "") or ""
    else:
        line = getattr(lang_svc, "STILL_THERE", "") or getattr(lang_svc, "FALLBACK", "") or ""
    return line.format(name=name) if "{name}" in line else line


async def handle_call_session(
    websocket: WebSocket,
    user: dict,
    session_id: str,
    provider: str,
    stream_sid: str = "",
):
    language = user.get("language", "hi-IN")
    name = user.get("name", "Ji")
    from inbound import config as inbound_config

    if inbound_config.IS_INBOUND:
        from inbound.lang_loader import load_inbound_lang_service
        lang_svc = load_inbound_lang_service(language or inbound_config.DEFAULT_LANGUAGE)
    elif edu_config.IS_EDUCATION:
        from edu.lang_loader import load_edu_lang_service
        lang_svc = load_edu_lang_service(language or edu_config.DEFAULT_LANGUAGE)
    else:
        lang_svc = load_lang_service(language)
    voice_lang = voice_language(lang_svc)

    tts_cfg = lang_svc.TTS_CONFIG
    # SessionManager brings its own UsageMeter. There is deliberately no
    # reset_costs() here — it used to zero the shared counters and take every
    # other call in this process down with it.
    if inbound_config.IS_INBOUND:
        from inbound.session_manager import InboundSessionManager
        session = InboundSessionManager(user, lang_svc)
    elif edu_config.IS_EDUCATION:
        from edu.session_manager import EduSessionManager
        session = EduSessionManager(user, lang_svc)
    else:
        session = SessionManager(user, lang_svc)

    log.info(
        f"Call started | provider={provider} | user={name} | "
        f"lang={language} | session={session_id[:16]}"
    )

    twilio_rx = None
    plivo_rx = None
    exotel_rx = None
    if provider == "frejun":
        player = FreJunAudioPlayer(websocket)
        recv_pcm = receive_pcm_from_frejun
    elif provider == "twilio":
        player = TwilioAudioPlayer(websocket, stream_sid)
        twilio_rx = TwilioPcmReceiver()
        recv_pcm = twilio_rx
    elif provider == "plivo":
        player = PlivoAudioPlayer(websocket, stream_sid)
        plivo_rx = PlivoPcmReceiver()
        recv_pcm = plivo_rx
    else:
        player = ExotelAudioPlayer(websocket, stream_sid)
        exotel_rx = ExotelPcmReceiver()
        recv_pcm = exotel_rx

    await player.start()

    barge_rx = twilio_rx or plivo_rx
    monitor = (
        BargeInMonitor(websocket, barge_rx, player)
        if barge_rx is not None and PHONE_BARGE_IN_ENABLED else None
    )

    async def tts_for_thinking(text: str):
        # Cached: the fillers are a tiny fixed set, and a filler that needs a
        # network round trip defeats its own purpose.
        return await synthesize_cached(
            text, language=voice_lang,
            speaker=tts_cfg["speaker"], pace=tts_cfg["pace"],
            temperature=tts_cfg.get("temperature"),
        )

    async def _after_sathi_spoke():
        await player.drain()
        # The monitor is reading the socket; it will hand over what it heard.
        if monitor is not None and monitor.active:
            return
        if twilio_rx is not None:
            await twilio_rx.discard_pending(websocket)
        if plivo_rx is not None:
            await plivo_rx.discard_pending(websocket)
        if exotel_rx is not None:
            await exotel_rx.discard_pending(websocket)

    async def _say(text: str):
        """
        Speak a fixed line (greeting / recovery / closing) and settle.

        The phrases are synthesized concurrently and played in order, the same
        way a streamed reply is. They used to be synthesized one after another,
        so the greeting — three phrases — cost three round trips to Sarvam back
        to back before the caller heard anything, which is most of the silence
        people noticed right after picking up. OrderedTtsQueue starts playback
        as soon as phrase one lands and keeps the order regardless of which
        request finishes first.
        """
        if not text or not text.strip():
            return
        parts = [
            p.strip() for p in re.split(r"(?<=[.!?।…])\s+", text.strip()) if p.strip()
        ] or [text]
        if hasattr(lang_svc, "prepare_for_tts"):
            parts = [lang_svc.prepare_for_tts(p) for p in parts]
        parts = [p for p in parts if p and p.strip()]

        ordered = _tts_queue(player, voice_lang)

        async def _speak():
            await asyncio.gather(
                *(
                    ordered.synthesize_and_enqueue(i, phrase, voice_lang, tts_cfg)
                    for i, phrase in enumerate(parts)
                ),
                return_exceptions=True,
            )
            await _after_sathi_spoke()

        if await run_until_barge(_speak(), monitor):
            await player.clear()

    # Warm the filler cache while the greeting is being spoken, so the first
    # "hmm..." costs nothing. Failure here is harmless — it just isn't cached.
    warm = asyncio.create_task(
        prewarm_phrases(
            thinking_sounds_for(tts_cfg), language=voice_lang,
            speaker=tts_cfg["speaker"], pace=tts_cfg["pace"],
            temperature=tts_cfg.get("temperature"),
        )
    )

    use_live = GLADIA_LIVE and is_french_language(voice_lang)
    live = None
    live_start = None

    async def _drop_live():
        nonlocal live, live_start
        if live_start is not None and not live_start.done():
            live_start.cancel()
        if live is not None:
            await live.close()
        live = None
        live_start = None

    try:
        greeting = _build_greeting(lang_svc, name, session.history_summary)
        log.info(f"Greeting: {greeting}")
        if RECORD_CALL:
            session.call_recorder = CallRecorder(session_id, user_name=user.get("name", "user"))
        # Timed on purpose: this is the silence the caller sits through after
        # picking up, and it is the number to watch if it creeps back up.
        t_greet = time.time()
        if monitor is not None:
            monitor.start()
        try:
            await _say(greeting)
        finally:
            seed = await monitor.stop() if monitor is not None else None
        log.info(f"Greeting spoken in {time.time() - t_greet:.2f}s")
        save_conversation(user["id"], session_id, "sathi", greeting,
                          language=session.language,
                          prompt_version=session.prompt_version)
        session.record_sathi_turn(greeting)

        try:
            cached = await warm
            log.info(f"Thinking sounds cached: {cached}")
        except Exception as e:
            log.warning(f"Filler prewarm failed ({e}) — fillers will synthesize on demand")

        audio_buffer = bytearray()
        silent_chunks = 0
        speech_chunks = 0
        hearing_speech = False
        pre_buffer = bytearray()
        pre_buf_max = CHUNK_SIZE * 3
        # Silence with no speech in it at all — see SILENCE_*_CHUNKS.
        quiet_chunks = 0
        quiet_prompted = False
        # One set of thresholds for every provider — twilio/exotel used to be
        # hardcoded to 15/8 here, ignoring the config and adding 0.5s to every turn.
        min_speech = VAD_MIN_SPEECH_CHUNKS
        silence_needed = VAD_SILENCE_CHUNKS
        log.info(
            f"VAD: reply after {silence_needed * 100}ms silence"
            + (f" ({VAD_LIVE_SILENCE_CHUNKS * 100}ms once live STT is final)" if use_live else "")
            + f", min speech {min_speech * 100}ms"
        )

        while True:
            if seed:
                # She was interrupted: what the caller said over her is the
                # start of this turn, already known to be speech.
                audio_buffer = bytearray(seed)
                pre_buffer = bytearray()
                silent_chunks = 0
                speech_chunks = max(min_speech, len(seed) // CHUNK_SIZE)
                hearing_speech = True
                quiet_chunks = 0
                quiet_prompted = False
                if use_live:
                    live = LiveSession(sample_rate=PHONE_SAMPLE_RATE)
                    live_start = asyncio.create_task(live.start())
                    live.feed(bytes(seed))
                seed = None

            try:
                chunk = await recv_pcm(websocket)
            except asyncio.TimeoutError:
                log.info("Call timeout — ending session")
                break
            except WebSocketDisconnect:
                log.info("WebSocket disconnected")
                break
            except Exception as e:
                log.warning(f"Receive error: {e}")
                break

            if not chunk:
                continue

            # Hard backstop for a turn that never returns. The soft cap in
            # SessionManager.is_call_done() ends the call cleanly at the end of
            # a turn; this only fires if that never happens.
            if session.out_of_time() and session.elapsed() > MAX_CALL_SECONDS + 30:
                log.warning("Call ran past the wall-clock cap — closing")
                break

            if is_silence(chunk):
                pre_buffer.extend(chunk)
                if len(pre_buffer) > pre_buf_max:
                    pre_buffer = pre_buffer[-pre_buf_max:]

                if not hearing_speech:
                    # Dead air. Ask once, then let them go.
                    quiet_chunks += 1
                    if quiet_chunks >= SILENCE_HANGUP_CHUNKS:
                        log.warning(
                            f"Silent for {quiet_chunks * 100 / 1000:.0f}s — closing"
                        )
                        break
                    if quiet_chunks >= SILENCE_PROMPT_CHUNKS and not quiet_prompted:
                        quiet_prompted = True
                        line = _recovery_line(lang_svc, session.user_name, 2)
                        if line:
                            log.info(f"Dead air — asking: {line}")
                            await _say(line)

                if hearing_speech:
                    silent_chunks += 1
                    audio_buffer.extend(chunk)
                    if live is not None:
                        live.feed(chunk)

                    # A blip of noise that never became real speech — re-arm
                    # instead of buffering it forever (which used to leave the
                    # call silently stuck until the 30s websocket timeout).
                    if silent_chunks >= VAD_ABANDON_CHUNKS and speech_chunks < min_speech:
                        audio_buffer = bytearray()
                        silent_chunks = 0
                        speech_chunks = 0
                        hearing_speech = False
                        await _drop_live()
                        continue

                    live_final = (
                        live is not None and live.has_final
                        and silent_chunks >= VAD_LIVE_SILENCE_CHUNKS
                    )
                    if (silent_chunks >= silence_needed or live_final) and speech_chunks >= min_speech:
                        log.info(f"VAD: silence after {speech_chunks} speech chunks")

                        # Start the acknowledgement clock NOW, before STT — this is
                        # the moment the caller falls silent. It used to start only
                        # after STT returned, so the "hmm..." could not arrive until
                        # ~3.6s, by which point the real reply was already coming.
                        def _next_ack_sound() -> str:
                            sound = pick_thinking_sound(
                                tts_cfg, session.last_user_msg, lang_svc,
                                avoid=session.last_thinking_sound,
                            )
                            session.last_thinking_sound = sound
                            return sound

                        ack_sound = _next_ack_sound()
                        watchdog = ThinkingWatchdog(
                            player=player, tts_fn=tts_for_thinking,
                            sound=ack_sound, sound_fn=_next_ack_sound,
                            threshold_ms=THINKING_MS,
                        )
                        await watchdog.start()

                        audio_data = bytes(pre_buffer) + bytes(audio_buffer)
                        wav_bytes_in = pcm_8k_to_wav_16k(audio_data)

                        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                            tmp.write(wav_bytes_in)
                            wav_path = tmp.name

                        turn_live, turn_live_start = live, live_start
                        live, live_start = None, None
                        if monitor is not None:
                            monitor.start()
                        captured = None
                        try:
                            result = await _process_turn(
                                player=player,
                                tts_fn=tts_for_thinking,
                                say=_say,
                                watchdog=watchdog,
                                wav_path=wav_path,
                                user=user,
                                session=session,
                                session_id=session_id,
                                language=language,
                                voice_lang=voice_lang,
                                lang_svc=lang_svc,
                                tts_cfg=tts_cfg,
                                live=turn_live,
                                live_start=turn_live_start,
                                speech_s=len(audio_data) / (PHONE_SAMPLE_RATE * 2),
                                monitor=monitor,
                            )
                        finally:
                            if monitor is not None:
                                captured = await monitor.stop()
                            if turn_live is not None:
                                await turn_live.close()
                            try:
                                os.unlink(wav_path)
                            except Exception:
                                pass

                        # Nothing to settle on the turn we are hanging up on —
                        # discard_pending costs LISTEN_SETTLE_S, and the caller
                        # is only waiting for the line to drop by this point.
                        if not result:
                            break

                        if captured:
                            seed = captured
                            continue

                        if twilio_rx is not None:
                            await twilio_rx.discard_pending(websocket)
                        if plivo_rx is not None:
                            await plivo_rx.discard_pending(websocket)
                        if exotel_rx is not None:
                            await exotel_rx.discard_pending(websocket)

                        audio_buffer = bytearray()
                        pre_buffer = bytearray()
                        silent_chunks = 0
                        speech_chunks = 0
                        hearing_speech = False
                        quiet_chunks = 0
                        quiet_prompted = False
            else:
                if not hearing_speech:
                    if use_live and live is None:
                        # Connect while they are still talking; feed() queues
                        # audio until the socket is up.
                        live = LiveSession(sample_rate=PHONE_SAMPLE_RATE)
                        live_start = asyncio.create_task(live.start())
                        if pre_buffer:
                            live.feed(bytes(pre_buffer))
                    audio_buffer.extend(pre_buffer)
                    pre_buffer = bytearray()
                    hearing_speech = True
                audio_buffer.extend(chunk)
                if live is not None:
                    live.feed(chunk)
                speech_chunks += 1
                silent_chunks = 0
                quiet_chunks = 0
                quiet_prompted = False

    except (WebSocketDisconnect, RuntimeError) as e:
        # The caller hung up. Every one of player.drain(), discard_pending() and
        # recv_pcm() raises from inside the loop body, and falling out of the
        # function here used to skip _end_of_call entirely — so the commonest
        # way a call ends threw away the health record, the cost row and the
        # alert. The finally below now runs whatever happened.
        if isinstance(e, RuntimeError) and not _is_closed_socket(e):
            raise
        log.info(f"Caller disconnected mid-call ({type(e).__name__}) — saving what we have")
    finally:
        # A hang-up during the greeting leaves the prewarm still in flight.
        if not warm.done():
            warm.cancel()
        await _drop_live()

        # Order matters: everything the caller can hear happens first, then we
        # drop the line, and only then do the bookkeeping. It used to be the
        # other way round, which held them on an open silent line through a
        # deep_extract LLM call, three DB writes and the alert engine.
        connected = websocket.client_state.name == "CONNECTED"
        if connected:
            try:
                await _speak_closing(user, session, lang_svc, player,
                                     voice_lang=voice_lang)
                await player.drain()
            except Exception:
                # A caller who hung up mid-closing is normal, not an error.
                log.info("Closing line not delivered — caller already gone")
        await player.stop()

        try:
            await websocket.close()
        except Exception:
            pass
        log.info(f"Line closed after {session.elapsed():.1f}s "
                 f"({session.turn_number} turns) — saving")

        try:
            await _persist_call(user, session, session_id, lang_svc)
        except Exception:
            # Never let bookkeeping mask the reason the call ended.
            log.error("End-of-call processing failed", exc_info=True)


async def _live_transcript(live, live_start, speech_s: float) -> dict | None:
    """Finish a Gladia live session; None means fall back to batch STT."""
    if live is None or live_start is None:
        return None
    t = time.time()
    try:
        ok = await asyncio.wait_for(live_start, timeout=3.0)
    except Exception:
        ok = False
    if not ok:
        log.warning(f"Live STT unavailable ({live.error}) — batch fallback")
        return None
    text = await live.finish(wait_s=1.0)
    latency = time.time() - t
    if not text:
        log.info("Live STT empty — batch fallback")
        return None
    print(f"  🎙️  STT (Gladia / live) ✅ {latency:.2f}s")
    print(f"  📝  \"{text}\"")
    return {"transcript": text, "duration": speech_s, "latency": latency}


async def _process_turn(
    player, tts_fn, say, wav_path, user, session, session_id,
    language, voice_lang, lang_svc, tts_cfg, watchdog=None,
    live=None, live_start=None, speech_s: float = 0.0, monitor=None,
) -> bool:
    t0 = time.time()
    session.start_turn()

    # The caller starts this the moment the caller falls silent so the
    # acknowledgement overlaps STT. Fall back to starting it here if not.
    if watchdog is None:
        def _next_ack_sound() -> str:
            sound = pick_thinking_sound(
                tts_cfg, session.last_user_msg, lang_svc,
                avoid=session.last_thinking_sound,
            )
            session.last_thinking_sound = sound
            return sound

        watchdog = ThinkingWatchdog(
            player=player, tts_fn=tts_fn,
            sound=_next_ack_sound(), sound_fn=_next_ack_sound,
            threshold_ms=THINKING_MS,
        )
        await watchdog.start()

    stt = await _live_transcript(live, live_start, speech_s)
    if stt is None:
        stt = await transcribe(wav_path, language=voice_lang)
    rec = getattr(session, "call_recorder", None)
    if rec:
        rec.append_wav_file(wav_path)
    user_text = stt.get("transcript", "").strip()
    stt_sec = stt.get("duration", 0)

    # Nothing heard. Say so, instead of leaving them in silence wondering
    # whether the line dropped.
    if not user_text:
        await watchdog.cancel()
        misses = session.note_miss()
        if session.gave_up_hearing():
            log.warning(f"Nothing heard {misses}x in a row — closing the call")
            return False
        line = _recovery_line(lang_svc, session.user_name, misses)
        log.warning(f"Empty transcript ({misses}) — saying: {line}")
        await say(line)
        return True

    session.note_heard()
    log.info(f"Turn {session.turn_number} | User: {user_text}")

    session.record_user_turn(user_text, audio_duration=stt_sec)
    save_conversation(user["id"], session_id, "user", user_text, audio_duration=stt_sec,
                      language=session.language,
                      prompt_version=session.prompt_version)

    # An emergency is spoken from the fixed script — but the call stays open so
    # they can answer ("it's just gas", "my son is here"). It used to hang up.
    if session.phase != "emergency_followup" and is_emergency(user_text, lang_svc):
        log.warning("EMERGENCY detected!")
        await watchdog.cancel()
        emrg = await text_to_speech_full(
            lang_svc.EMERGENCY, language=voice_lang,
            speaker=tts_cfg["speaker"], pace=tts_cfg["pace"],
            temperature=tts_cfg.get("temperature"),
            pause_ms=tts_cfg.get("pause_ms"),
        )
        if emrg.get("wav_bytes"):
            await player.enqueue(emrg["wav_bytes"])
            await player.drain()
        session.record_sathi_turn(lang_svc.EMERGENCY, tts_chars=len(lang_svc.EMERGENCY))
        save_conversation(user["id"], session_id, "sathi", lang_svc.EMERGENCY,
                          char_count=len(lang_svc.EMERGENCY),
                          language=session.language,
                          prompt_version=session.prompt_version)
        session.begin_emergency_followup()
        return True

    # Every reason to stop still earns one reply — she used to just vanish
    # mid-conversation. The reason decides what that last reply sounds like.
    exit_reason = classify_exit(user_text, lang_svc)
    if exit_reason:
        # An opt-out or a death is worth finding in the log later, both to
        # honour the request by hand and to spot a mishearing that ended a
        # call it should not have. The rest are ordinary and stay at info.
        line = f"Exit intent '{exit_reason}' — one last turn, then closing: {user_text}"
        if exit_reason in ("declined", "bereavement"):
            log.warning(line)
        else:
            log.info(line)
        session.begin_farewell(exit_reason)

    ctx = session.build_llm_context()
    system_prompt = build_system(lang_svc, session.user_name, ctx, log=log)
    messages = session.get_llm_messages(max_turns=8)

    # Ordered enqueue: TTS runs in parallel but playback stays in sentence
    # order. Without this a short sentence 2 can overtake a long sentence 1.
    ordered = _tts_queue(player, voice_lang)
    sathi_sentences = []
    tts_chars = 0
    pending_tts = []
    phrase_seq = 0
    first_token = False
    t_first_token = None
    token_buffer = ""
    truncated = False
    end_signalled = False
    interrupted = False

    def _emit(phrase: str):
        nonlocal phrase_seq, tts_chars
        sathi_sentences.append(phrase)
        log.info(f"  Sathi phrase: {phrase}")
        slips = getattr(lang_svc, "honorific_slips", None)
        if callable(slips):
            found = slips(phrase)
            if found:
                log.warning(f"  Informal address survived: {', '.join(found)}")
        pending_tts.append(asyncio.create_task(
            ordered.synthesize_and_enqueue(phrase_seq, phrase, voice_lang, tts_cfg)
        ))
        phrase_seq += 1
        tts_chars += len(phrase)

    def _accept(raw: str):
        """
        Clean one phrase, pull out the end-of-call signal, speak what is left.

        The signal must come off BEFORE prepare_for_tts — _clean() only strips
        quotes and would send "<<END>>" straight to the voice.
        """
        nonlocal end_signalled
        text, ended = strip_end_signal(raw)
        if ended:
            end_signalled = True
        text = _clean(text.strip())
        if not text or len(text) < 2:
            return
        _emit(lang_svc.prepare_for_tts(text))

    stream = stream_tokens(system_prompt, messages, language=language,
                           meter=session.usage)
    try:
        async for token in stream:
            if not token:
                continue
            if not first_token:
                await watchdog.cancel()
                first_token = True
                t_first_token = time.time()

            token_buffer += token
            # Comma-split only before the first phrase — see _split().
            phrases, token_buffer = _split(
                token_buffer, allow_early=not sathi_sentences,
            )

            for phrase in phrases:
                _accept(phrase)

            if monitor is not None and monitor.fired.is_set():
                interrupted = True
                break

            # She has said her goodbye — nothing follows the signal, so stop
            # reading the stream instead of holding the connection open.
            if end_signalled:
                break

            # Only ever cut on a completed sentence, never mid-thought. The
            # farewell turn gets a tighter cap so the last words are short.
            cap = _farewell_cap(session) if session.phase == "farewell" else MAX_PHRASES
            if len(sathi_sentences) >= cap:
                truncated = True
                log.warning(f"Reply hit the {cap}-sentence runaway guard")
                break
    finally:
        await stream.aclose()
        await watchdog.cancel()

    # Whatever is left in the buffer is the final sentence — speak it. Skipped
    # only after a runaway break, where the leftover is a stray fragment.
    if interrupted:
        pass
    elif token_buffer.strip():
        if not truncated:
            _accept(token_buffer)
        else:
            # The fragment is not worth speaking, but the end signal lives at
            # the very end of the reply — which is exactly what the runaway
            # break leaves behind. Reading it here is the difference between
            # hanging up and running the call on for another turn.
            _, ended = strip_end_signal(token_buffer)
            if ended:
                end_signalled = True

    # The sentinel is the intended path, but models drop it, and a dropped
    # sentinel used to leave the call running after she had already said
    # goodbye — the caller hears "alright, I'm hanging up" and then sits on an
    # open line. Reading her own words back is the net under that.
    if not end_signalled and announced_hangup(" ".join(sathi_sentences), lang_svc):
        log.info("She announced the hang-up in her own words — closing")
        end_signalled = True

    if not interrupted:
        async def _finish_playback():
            if pending_tts:
                await asyncio.gather(*pending_tts, return_exceptions=True)
            await player.drain()

        interrupted = await run_until_barge(_finish_playback(), monitor)

    if interrupted:
        for task in pending_tts:
            task.cancel()
        await asyncio.gather(*pending_tts, return_exceptions=True)
        await player.clear()
        # She never finished — a goodbye she was cut off in does not end the call.
        end_signalled = False
        log.info("Interrupted — listening to the caller")

    if end_signalled and session.phase != "farewell":
        log.info("She ended the call herself (end signal)")
        session.begin_farewell()

    sathi_full = " ".join(sathi_sentences).strip()
    session.record_sathi_turn(sathi_full, tts_chars=tts_chars)
    if sathi_full:
        save_conversation(user["id"], session_id, "sathi", sathi_full, char_count=len(sathi_full),
                          language=session.language,
                          prompt_version=session.prompt_version)

    total = time.time() - t0
    ft = f"{t_first_token - t0:.2f}s" if t_first_token is not None else "n/a"
    fa = f"{ordered.first_enqueued_at - t0:.2f}s" if ordered.first_enqueued_at is not None else "n/a"
    log.info(f"Turn done in {total:.2f}s | STT {stt.get('latency', 0):.2f}s | "
             f"first_token {ft} | first_audio {fa} | fillers {watchdog.fire_count}")

    if session.is_call_done():
        return False
    return True


async def _speak_closing(user, session, lang_svc, player, voice_lang=None):
    """
    Say the fixed closing line. Needs a live line, so it is the only part of
    ending a call that has to happen before we hang up.
    """
    # She has already said goodbye in her own words on a farewell turn; adding
    # the fixed closing on top would have her say goodbye twice.
    if session.phase == "farewell":
        return

    if voice_lang is None:
        voice_lang = voice_language(lang_svc)
    tts_cfg = lang_svc.TTS_CONFIG
    closing = _build_closing(lang_svc, user.get("name", "Ji"),
                             session.build_llm_context())
    log.info(f"Closing: {closing}")
    close_r = await text_to_speech_full(
        closing, language=voice_lang,
        speaker=tts_cfg["speaker"], pace=tts_cfg["pace"],
        temperature=tts_cfg.get("temperature"),
        pause_ms=tts_cfg.get("pause_ms"),
    )
    if close_r.get("wav_bytes"):
        await player.enqueue(close_r["wav_bytes"])


async def _persist_call(user, session, session_id, lang_svc):
    """
    Persist everything the call produced.

    None of this needs the caller on the line — deep_extract alone is a
    non-streaming LLM round trip with a 30s timeout, and it used to run with
    the line still open, so the caller sat listening to silence through it.
    It now runs after the hang-up.

    Runs on every exit path, including a mid-turn hang-up: dropping it there is
    what used to throw away the health record, the cost row and the alert.
    """
    rec = getattr(session, "call_recorder", None)
    if rec:
        rec.save()
    history = get_session_history(session_id, user["id"])

    from inbound import config as inbound_config

    if inbound_config.IS_INBOUND or edu_config.IS_EDUCATION:
        # Helpline / admissions: no health extract. Persist product outcome only.
        try:
            session.persist_outcome()
        except Exception as e:
            log.warning(f"persist_outcome skipped: {e}")
        save_api_cost(
            user["id"], session_id,
            session.total_stt_sec, session.total_tts_chars, session.total_tokens,
            llm_cost_inr=session.llm_cost_inr,
            llm_cache_write_tokens=session.llm_cache_write_tokens,
            llm_cache_read_tokens=session.llm_cache_read_tokens,
        )
        log.info(
            f"Usage: {session.usage.input_tokens} in / {session.usage.output_tokens} out "
            f"| ₹{session.llm_cost_inr:.4f}"
        )
        return

    # A call that ended before the caller said anything (hung up during the
    # greeting) has nothing to extract — don't pay for an LLM round trip to
    # read back our own greeting.
    if any(h["role"] == "user" for h in history):
        conv_text = "\n".join(
            f"{'User' if h['role'] == 'user' else 'Sathi'}: {h['message']}"
            for h in history
        )
        health = await deep_extract(conv_text, lang_svc.NAME)
    else:
        log.info("No user turns on this call — skipping deep extraction")
        health = {}

    fast = session.extracted
    final = {**fast, **{k: v for k, v in health.items() if v is not None and v is not False}}
    if final:
        save_health_record(user["id"], session_id, final)
        log.info(f"Health saved: {final}")

    # This call's own meter — never the process-wide one, which on a busy
    # server holds whatever the other live calls happen to have accumulated.
    save_api_cost(
        user["id"], session_id,
        session.total_stt_sec, session.total_tts_chars, session.total_tokens,
        llm_cost_inr=session.llm_cost_inr,
        llm_cache_write_tokens=session.llm_cache_write_tokens,
        llm_cache_read_tokens=session.llm_cache_read_tokens,
    )
    log.info(
        f"Usage: {session.usage.input_tokens} in / {session.usage.output_tokens} out "
        f"| ₹{session.llm_cost_inr:.4f}"
    )

    level, reason = analyse(user["id"])
    log.info(f"Alert: {level} — {reason}")
    if level in ("yellow", "orange", "red", "emergency"):
        family = user.get("family_name", "Family")
        save_alert(
            user["id"],
            session_id,
            level,
            reason,
            message=reason,
            sent_to=user.get("family_contact") or family,
        )
        log.warning(f"⚠️  NOTIFY {family}: {reason}")
