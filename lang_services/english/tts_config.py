"""
English TTS config v12
Speaker: priya — the SAME voice as Hindi and Marathi, so Sathi is one person
whichever language the call is in. This was 'aditya' (male) while both other
packs used 'priya' (female) and their personas state she is female, so the
agent changed sex depending on the language.

Other female bulbul:v3 speakers if you want a different one: ritu, neha, pooja,
simran, kavya, ishita, shreya, roopa, tanya, shruti, suhani, kavitha, rupali,
niharika. Change it in all three packs together.

`soft_thinking_sounds` is the subset that is safe on top of bad news; the full
list may include brighter sounds. See pick_thinking_sound().
"""
TTS_CONFIG = {
    "speaker":     "priya",
    "pace":        0.92,
    "pause_ms":    380,
    "temperature": 0.55,
    "thinking_sounds": [
        "Hmm...", "Right...", "Ah...", "I see..."
    ],
    "soft_thinking_sounds": [
        "Hmm...", "Right...", "I see..."
    ],
}
