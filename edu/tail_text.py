"""
edu/tail_text.py — the per-turn instructions, shared across languages.

These are behavioural directions to the model, not lines to be spoken, so they
live in English once rather than three times. Same reasoning as the persona
rules in edu/persona.py: a fix to how the visit is offered should land in every
language on the same commit.

Each entry says what to do, never what to say. A tail that supplies the actual
sentence produces a call where every parent hears the identical phrasing at the
identical moment, which is the specific thing that makes an agent sound
scripted. Saathicare learnt this the hard way — see the note in
lang_services/english/personality.py about injecting a rotating first word.
"""

# One per steerable slot. Only ever one is injected per turn.
STEER_QUESTIONS = {
    "grade": (
        "You still do not know whether they are an architect / MOE or a "
        "manufacturer / seller of made-to-measure. Work it out naturally — it "
        "is usually the other half of whatever they just asked about."
    ),
    "intake": (
        "You do not know whether they need this now or are only exploring. "
        "Find out, lightly."
    ),
    "locality": (
        "You do not know where they work — city or region. It is a natural "
        "question, not an intrusive one."
    ),
    "child_age": (
        "You do not know how large the firm is — solo, a small cabinet, or a "
        "larger agency. Ask only if the métier alone has not made pricing "
        "obvious."
    ),
    "visit_intent": (
        "The conversation has earned it: offer the twenty-minute live demo "
        "now. They bring a project address or a few catalogue pages. Easy to "
        "decline. If they hesitate, offer the site link and drop it."
    ),
    "closing": (
        "Bring the call to a close over this turn and the next. Do not open a "
        "new topic."
    ),
}

# One per exit reason from services/conversation_engine.classify_exit, plus the
# plain goodbye. These are the calls where getting it wrong is most visible, so
# each one says explicitly what NOT to do.
FAREWELL = {
    "goodbye": (
        "They are done. Say your goodbye warmly and briefly. If a visit or a "
        "callback was agreed, confirm it in half a sentence. Nothing new."
    ),
    "unavailable": (
        "This is a bad moment for them. Apologise for catching them now, say you "
        "will call another time, and stop. Do not ask when. Do not ask anything "
        "at all. Do not mention Maîtria again."
    ),
    "declined": (
        "They do not want these calls. Accept it in one sentence — sorry for the "
        "trouble, you will not call again. No persuading, no explaining what the "
        "call was about, no asking why, no last offer."
    ),
    "wrong_person": (
        "This is not the person you meant to reach. Apologise for the "
        "disturbance and let them go. Do not ask them to pass on a message and "
        "do not say anything about the firm or the demo."
    ),
    "bereavement": (
        "Someone has died. One gentle sentence of condolence and nothing else. "
        "No questions, no mention of calling back, nothing about Maîtria."
    ),
}
