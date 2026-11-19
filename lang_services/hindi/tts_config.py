"""
Hindi TTS config v9
Speaker: priya (warm care voice — 'meera' is no longer on Sarvam Bulbul)
Pace slowed for elderly clarity
"""
TTS_CONFIG = {
    "speaker":     "priya",
    "pace":        0.80,
    "pause_ms":    500,
    "temperature": 0.87,
    # soft_thinking_sounds = the subset that is safe on top of bad news.
    # "अच्छा..." / "ठीक है..." read as breezy when they've just said something
    # painful, so they stay out of it. See pick_thinking_sound().
    "thinking_sounds": [
        "हाँ...", "अच्छा...", "हम्म...", "ओह...", "ठीक है..."
    ],
    "soft_thinking_sounds": [
        "हम्म...", "ओह...", "हाँ..."
    ],
}
