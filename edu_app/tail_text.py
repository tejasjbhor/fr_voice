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
        "You still do not know which grade or class the child is going into. "
        "Work it out naturally — it is usually the other half of whatever they "
        "just asked about. Ask plainly if it has not come up."
    ),
    "intake": (
        "You do not know whether they are looking at this academic year or the "
        "next one. Find out, lightly."
    ),
    "locality": (
        "You do not know which area they live in. It matters for transport and "
        "for how realistic the commute is, so it is worth asking — and it is a "
        "natural question, not an intrusive one."
    ),
    "child_age": (
        "You do not know the child's age. Ask only if the grade alone has not "
        "made it obvious."
    ),
    "visit_intent": (
        "The conversation has earned it: offer them a campus visit now. Make it "
        "concrete — a day and a rough time — and easy to decline. If they "
        "hesitate at all, offer to have the details sent instead and drop it."
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
        "at all. Do not mention admissions again."
    ),
    "declined": (
        "They do not want these calls. Accept it in one sentence — sorry for the "
        "trouble, you will not call again. No persuading, no explaining what the "
        "call was about, no asking why, no last offer."
    ),
    "wrong_person": (
        "This is not the person you meant to reach. Apologise for the "
        "disturbance and let them go. Do not ask them to pass on a message and "
        "do not say anything about the family or the admission."
    ),
    "bereavement": (
        "Someone has died. One gentle sentence of condolence and nothing else. "
        "No questions, no mention of calling back, nothing about admissions."
    ),
}
