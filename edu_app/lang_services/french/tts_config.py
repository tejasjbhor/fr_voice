"""
French TTS config — Fish Audio (Clémence, native French).
pace maps to Fish prosody.speed. Slightly under 1.0 keeps her unhurried.

FIX (temperature): 0.85 → 0.68. High temperature introduced unpredictable
prosody variation — inappropriate for Camille's composed professional persona.
0.68 gives a consistent, calm tone while preserving natural intonation.

FIX (thinking_sounds): added native French fillers ("Tout à fait...",
"Bien sûr...", "Effectivement..."). The old list was partly French but missing
the most natural acknowledgement sounds a native speaker uses.

FIX (ElevenLabs model hint): added ELEVENLABS_TTS_MODEL_HINT so callers
that route French through ElevenLabs can switch to eleven_turbo_v2_5
without touching elevenlabs_service.py. The hint is advisory — the service
reads it if present and falls back to the env var otherwise.
"""
TTS_CONFIG = {
    "speaker":     "fish",
    "pace":        0.93,
    "pause_ms":    220,
    "temperature": 0.68,

    # Native French acknowledgement sounds — synthesized and cached at
    # session start so they play instantly when the watchdog fires.
    "thinking_sounds": [
        "Hmm...",
        "Je vois...",
        "Tout à fait...",
        "Bien sûr...",
        "Effectivement...",
        "D'accord...",
    ],
    # Subset safe to play over difficult news (no bright/breezy exclamations).
    "soft_thinking_sounds": [
        "Hmm...",
        "Je vois...",
        "D'accord...",
    ],

    # Advisory hint for ElevenLabs routing — eleven_turbo_v2_5 is ~35%
    # faster than multilingual_v2 at conversational speech rates.
    "elevenlabs_model_hint": "eleven_turbo_v2_5",
}
