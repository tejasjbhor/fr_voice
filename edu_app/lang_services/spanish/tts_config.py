"""
Spanish TTS config — experimental (ElevenLabs)
==============================================
Set USER_LANGUAGE=es-ES and ELEVENLABS_API_KEY in .env.
Speaker/pace are ignored for ElevenLabs; kept for API compatibility.
"""
TTS_CONFIG = {
    "speaker": "elevenlabs",
    "pace": 0.92,
    "pause_ms": 380,
    "temperature": 0.75,
    # soft_thinking_sounds = the subset that is safe on top of bad news.
    "thinking_sounds": [
        "Hmm...", "Bueno...", "Ah...", "Ya veo..."
    ],
    "soft_thinking_sounds": [
        "Hmm...", "Bueno...", "Ya veo..."
    ],
}
