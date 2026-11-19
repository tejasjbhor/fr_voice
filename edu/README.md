# edu/ — Education voice product on the Saathicare engine

An AI admissions counsellor. Calls a school's admission leads, answers parents'
questions from a verified fact sheet, quietly qualifies the lead, and either
books a campus visit or hands off to a human.

Built as an additive package. Nothing in the existing tree is modified;
integration is two lines behind `PRODUCT=education`. See `INTEGRATION.md`.

---

## The one architectural decision that matters

Saathicare fuses three things inside each `lang_services/<lang>/personality.py`:
who she is, what domain she works in, and how the language behaves. Those files
run 650–750 lines each. Adding a second domain that way would have meant eight
of them, and every behavioural fix would need applying four times.

This package splits them:

```
edu/persona.py       WHO SHE IS + WHAT SHE DOES     one copy, all languages
edu/packs/*.py       SCRIPT, VOICE, WORD LISTS      one small file per language
edu/knowledge.py     WHAT IS TRUE                   one copy, per institution
```

`edu/pack_factory.py` composes the three into an object exposing exactly the
names `services/conversation_engine.py` and `telephony/session.py` already
reach for. That is why the integration is two lines: the engine cannot tell the
difference.

The packs *import* `EXIT_WORDS`, `UNAVAILABLE_WORDS`, `SELF_EXIT_BLOCKERS` and
Marathi's `fix_honorifics` from `lang_services/*`. Those were tuned against real
calls and were never health-specific — which is itself the clearest evidence
they should not have been living inside a health persona file.

**Behavioural rules are in English; few-shots are in the target language.** The
rules are constraints, and one copy means a fix to objection handling lands in
all three languages on the same commit. The few-shots carry the register, and
that is the part that cannot survive translation.

## Why there is no vector store

One school's answerable facts fit in about 1,400 tokens. Retrieval over a corpus
that small costs a round trip per turn and adds a failure mode (wrong chunk) that
a static block does not have.

There is a second reason, specific to this repo. `CLAUDE.md` documents that
`cache_control` does nothing until the static prefix clears the model's minimum
cacheable length — 4,096 tokens on Haiku 4.5 — and that the English health
persona at 1,849 tokens therefore **never caches**, silently paying full price
every turn. Folding the institution facts into the same static block makes them
available without retrieval *and* pushes the prefix over the floor:

```
lang       static prefix   floor                 model  verdict
en-IN               4344    4096      claude-haiku-4-5  caches
hi-IN               4651    4096      claude-haiku-4-5  caches
mr-IN               4636    4096      claude-haiku-4-5  caches
```

A 1,400-token knowledge block is not a cost here. It is what makes the persona
free from turn two. Move to retrieval when one institution genuinely outgrows
the block; the seam is `build_knowledge_block()`.

## Qualification is Saathicare's extractor, renamed

`core/extractor.py` already collects named slots across a free conversation and
decides turn by turn whether to nudge toward a missing one. That is lead
qualification wearing a stethoscope. `edu/qualification.py` keeps the shape and
swaps the slots:

```
grade · child_age · locality · intake · visit_intent      (critical)
board_pref · boarding · decision_stage · fee_concern · callback_time
```

Two rules are genuinely different, both because of who called whom:

- **Answer-first.** No steering on any turn where the parent asked something.
  Saathicare rings a lonely person and gently steers; here the parent has
  questions, and nudging over an unanswered one is the most irritating thing
  this agent can do.
- **No slot is worth the call.** Steering is capped at five and gives up early.
  A parent who never mentions their area is still a good lead.

## Files

| File | What it does |
|---|---|
| `config.py` | Env-driven settings. Becomes a DB row under multi-tenancy. |
| `institution.py` | The fact record. Validates, reports gaps. |
| `knowledge.py` | Renders facts into the cached block. Token/cache maths. |
| `persona.py` | Who she is. Personality knobs → behavioural sentences. |
| `tail_text.py` | Per-turn steering and farewell instructions. |
| `pack_factory.py` | Composes persona + language + facts into a pack. |
| `packs/*.py` | Per-language mechanics, word lists, few-shots, numerals. |
| `lang_loader.py` | Drop-in for `shared/lang.py`. Caches packs per process. |
| `qualification.py` | Slot extraction and steering rules. |
| `escalation.py` | When a human counsellor takes over. |
| `outcome.py` | Disposition, score, next action. |
| `compliance.py` | Calling window, attempt caps, suppression. |
| `lead_store.py` | `edu_leads` + `edu_call_outcomes`, on their own tables. |
| `session_manager.py` | `EduSessionManager` — the four overrides that matter. |
| `tools/prospectus_lint.py` | Fact coverage + cache-floor verdict. |
| `tools/smoke_edu.py` | Scripted call, offline, end to end. |
| `tools/eval_rules.py` | Education-specific persona checkers + selftest. |

## Personality knobs

```json
{ "tone": "warm", "formality": "medium", "verbosity": "concise",
  "sales": "low", "patience": "high" }
```

Set per institution in the JSON, or globally via env. Each knob maps to a
*sentence* in the persona, not a bare adjective — `"warmth: high"` pasted into a
prompt does close to nothing, whereas the clause it renders to does. That table
is in `edu/persona.py` and is what a future settings UI writes into.

## Grounding

The agent may state only what is in the institution file. Missing facts produce
a fixed deferral phrase, which is counted — and three deferrals in one call
triggers a counsellor handoff.

That counter is also the most useful report this system produces in its first
month: a ranked list of the questions parents actually ask that your institution
file cannot answer.

`prohibited_claims` in the JSON renders as hard prohibitions. The sample file
forbids guaranteeing a seat, quoting scholarship amounts, naming competitors and
implying scarcity. `tools/eval_rules.py` checks transcripts for all four.

## Known limitations

- No barge-in. A parent cannot interrupt her mid-answer.
- No mid-call language switching — blocked at the STT layer, not the prompt.
- No outbound dialler. The compliance gate exists; the campaign runner does not.
- Single institution.
- `invented_fact` catches digits, not numbers she spelled out in Devanagari
  words. It reports a floor, not a total. Read Marathi transcripts by hand.

## Quick start

```bash
cp -r edu/ /path/to/sathicare/
echo "PRODUCT=education" >> .env
python -m edu.tools.prospectus_lint
python -m edu.tools.smoke_edu en-IN
```
