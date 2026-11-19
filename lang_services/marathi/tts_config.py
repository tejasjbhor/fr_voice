"""
Marathi TTS config v10
Tuned for elderly users — slower, warmer, more pauses.
Speaker: priya (warm care voice — 'anushka' is not on Sarvam Bulbul v3)
Pace slowed for elderly clarity

v10: a prior working-tree edit had quietly drifted pace/pause_ms/temperature
toward English's values (0.90 / 380 / 0.75 — nearly identical to English's
0.92 / 380 / 0.75), undoing the "more expressive, less monotone" tuning from
an earlier commit (temperature 0.75->0.82, pace 0.82->0.78) and making this
the flattest, fastest-talking pack of the three instead of the warmest. Reset
to Hindi's values: same engine, same script family, same speaker, and Hindi
is the one that isn't reported as sounding robotic.
"""
TTS_CONFIG = {
    "speaker":     "priya",
    "pace":        0.80,
    "pause_ms":    500,
    "temperature": 0.87,
    # soft_thinking_sounds = the subset that is safe on top of bad news.
    # "अरे..." / "अच्छा..." are exclamatory and read as breezy when they have
    # just said something painful, so they stay out. See pick_thinking_sound().
    "thinking_sounds": [
        "हं...", "बरं...", "हो...", "अरे...", "अच्छा..."
    ],
    "soft_thinking_sounds": [
        "हं...", "हो...", "बरं..."
    ],
}
