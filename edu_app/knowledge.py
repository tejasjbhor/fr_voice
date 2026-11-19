"""
edu/knowledge.py — the institution knowledge block.

Why there is no vector store here
---------------------------------
One institution's answerable facts — fees, dates, eligibility, transport,
timings, process — fit in a few thousand tokens. Retrieval over a corpus that
small costs a round trip per turn and buys nothing, and it introduces a failure
mode (the right chunk not retrieved) that a static block simply does not have.

There is a second reason, specific to this codebase. CLAUDE.md records that the
`cache_control` marker on the persona block only does anything once the block
clears the serving model's minimum cacheable prefix — 4,096 tokens on Haiku
4.5, 1,024 on Sonnet — and that the English persona at 1,849 tokens therefore
never caches today, silently paying full price every turn. Putting the
institution facts in the same static block does two things at once: it makes the
facts available without retrieval, and it pushes the static prefix over the
floor so the whole thing finally caches. A 3k-token knowledge block is not a
cost to be minimised here. It is what makes the persona free from turn two.

Run `python -m edu.tools.prospectus_lint` to see where a given institution
lands against the floor.

Move to retrieval when one institution's corpus genuinely outgrows the block —
a university with 40 departments, say. The seam is `build_knowledge_block()`:
give it a different body and nothing above it changes.

Why the block is written in English regardless of call language
---------------------------------------------------------------
Facts get one representation. Three translated fee tables will diverge the
first time a school changes a number and someone updates two of them. The model
reads English facts and speaks them in the call's language perfectly well —
and Indian parents hear "twenty-five thousand rupees" inside a Marathi sentence
as completely normal. What IS per-language is how she talks, which lives in the
language pack, not here.
"""

from __future__ import annotations

from edu.institution import Institution

# Chars per token, from the measurements in CLAUDE.md. Latin text runs about
# 3.7; Devanagari about 1.4, roughly 2.6x denser. Never estimate prompt size
# from character counts without picking the right divisor.
CHARS_PER_TOKEN_LATIN = 3.7
CHARS_PER_TOKEN_DEVANAGARI = 1.4

# Minimum cacheable prefix by model, as documented in CLAUDE.md. A static block
# shorter than this caches nothing, reports nothing, and raises nothing.
CACHE_FLOOR = {
    "claude-haiku-4-5": 4096,
    "claude-sonnet-4-6": 1024,
    "claude-opus-4-5": 1024,
}
DEFAULT_CACHE_FLOOR = 4096


def estimate_tokens(text: str) -> int:
    """Rough token count that accounts for script density."""
    if not text:
        return 0
    deva = sum(1 for ch in text if "\u0900" <= ch <= "\u097F")
    other = len(text) - deva
    return int(round(deva / CHARS_PER_TOKEN_DEVANAGARI + other / CHARS_PER_TOKEN_LATIN))


def cache_floor_for(model: str | None) -> int:
    if not model:
        return DEFAULT_CACHE_FLOOR
    return CACHE_FLOOR.get(model.strip(), DEFAULT_CACHE_FLOOR)


# ── Rendering ─────────────────────────────────────────────────────


def _line(label: str, value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        value = value.strip()
        return f"{label}: {value}\n" if value else ""
    if isinstance(value, (list, tuple)):
        items = [str(v).strip() for v in value if str(v).strip()]
        return f"{label}: {', '.join(items)}\n" if items else ""
    if isinstance(value, dict):
        rows = [f"  - {k}: {v}" for k, v in value.items() if str(v).strip()]
        return f"{label}:\n" + "\n".join(rows) + "\n" if rows else ""
    return f"{label}: {value}\n"


def _numbered(label: str, items: list) -> str:
    items = [str(v).strip() for v in (items or []) if str(v).strip()]
    if not items:
        return ""
    rows = [f"  {i}. {v}" for i, v in enumerate(items, 1)]
    return f"{label}:\n" + "\n".join(rows) + "\n"


def build_knowledge_block(inst: Institution) -> str:
    """The institution's facts, as the agent is allowed to state them.

    Static for the whole call — no per-turn content may enter this string or
    the prompt cache is invalidated on every turn and the block becomes pure
    cost.
    """
    parts: list[str] = []

    parts.append(
        "INSTITUTION FACTS — THE ONLY THINGS YOU MAY STATE AS FACT\n"
        "Everything below is verified by the institution. Anything not below, "
        "you do not know. There is no shame in not knowing it; there is real "
        "harm in guessing, because a parent will act on what you say.\n"
    )

    body = ""
    body += _line("Name", inst.name)
    body += _line("Type", inst.display_kind())
    body += _line("City", inst.city)
    body += _line("Academic year", inst.academic_year)
    body += _line("Curriculum / board", inst.curriculum)
    body += _line("Grades currently open for admission", inst.grades_open)
    body += _line("Eligibility", inst.eligibility)
    body += _line("Fee structure", inst.fee_structure)
    body += _numbered("Admission process", inst.admission_process)
    body += _line("Documents required", inst.documents_required)
    body += _line("Entrance test", inst.entrance_test)
    body += _line("Application deadline", inst.application_deadline)
    body += _line("School timings", inst.timings)
    body += _line("Transport", inst.transport)
    body += _line("Hostel / boarding", inst.hostel)
    body += _line("Student-teacher ratio", inst.student_teacher_ratio)
    body += _line("Facilities", inst.facilities)
    body += _line("Activities", inst.activities)
    body += _line("Scholarships", inst.scholarships)
    body += _line("Campus visit", inst.campus_visit)
    body += _line("Areas we serve", inst.catchment_areas)
    body += _line("Contact", inst.contact)
    parts.append(body)

    if inst.faqs:
        rows = []
        for item in inst.faqs:
            q = str(item.get("q", "")).strip()
            a = str(item.get("a", "")).strip()
            if q and a:
                rows.append(f"  Q: {q}\n  A: {a}")
        if rows:
            parts.append("ANSWERS THE INSTITUTION HAS ALREADY APPROVED\n" + "\n".join(rows) + "\n")

    unknown = inst.unknown_topics()
    if unknown:
        parts.append(
            "WHAT YOU DO NOT HAVE\n"
            "You have no verified information on: "
            + ", ".join(_readable(u) for u in unknown)
            + ".\n"
            "If a parent asks about any of these, say plainly that you want to "
            "give them the exact answer rather than an approximate one, and that "
            "a counsellor will confirm it. Then carry on. Do not improvise a "
            "figure, a date, or a policy.\n"
        )

    if inst.prohibited_claims:
        parts.append(
            "NEVER SAY, UNDER ANY CIRCUMSTANCES\n"
            + "\n".join(f"  - {c}" for c in inst.prohibited_claims)
            + "\n"
        )

    return "\n".join(p for p in parts if p.strip()).strip()


def _readable(key: str) -> str:
    return key.replace("_", " ")


def knowledge_report(inst: Institution, model: str | None = None) -> dict:
    """Sizing and cache verdict for one institution. Used by prospectus_lint
    and worth calling at startup so a badly-sized block is visible before a
    parent is on the line rather than after a month of bills."""
    block = build_knowledge_block(inst)
    tokens = estimate_tokens(block)
    floor = cache_floor_for(model)
    return {
        "chars": len(block),
        "tokens": tokens,
        "model": model,
        "cache_floor": floor,
        "missing_expected": inst.unknown_topics(),
        "known_topics": inst.known_topics(),
    }
