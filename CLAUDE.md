# Sathi — notes for whoever works on this next

A daily voice companion that phones elderly users, talks to them in their own
language, and quietly extracts health signals from the conversation. Four
language packs (`en-IN`, `hi-IN`, `mr-IN`, `es-ES`), Claude for the words,
Sarvam (ElevenLabs for Spanish) for the voice.

Everything below is something you cannot work out by reading the code. The code
explains itself; these are the traps, the reasons, and the rules that outlive
any one file.

## Traps that will cost you an afternoon

**`setup_database()` can mark a database as migrated without migrating it.**
If the tables exist but `alembic_version` does not, it stamps straight to head
on the assumption that the schema is already current — so a database that
predates Alembic gets labelled up to date while missing every column any
migration would have added. On top of that, the whole Alembic call is wrapped in
a bare `except` that falls back to `create_all()`, which creates *missing
tables* but never adds *columns to existing tables*. A missing `alembic` package
therefore looks like a clean startup and silently skips your migration.
`alembic` was in fact absent from the venv for some time; that is how migration
`002` came to be needed by hand. Before trusting any environment, check that
`alembic_version` exists and matches the newest file in `alembic/versions/`.

**The local `alembic/` directory shadows the installed `alembic` package.**
It has no `__init__.py`, so Python treats it as a namespace package — and
because the current directory sits first on `sys.path`, it wins. `from alembic
import command` run from the repo root fails with `unknown location`. Run
Alembic from a different working directory and *append* the repo root to
`sys.path` rather than inserting it.

**Devanagari tokenises about 2.6× denser than Latin text.** Roughly 1.4
characters per token against 3.7. Never reason about prompt size from character
counts: the English persona is 6,814 characters but only 1,849 tokens, while the
Hindi one is 7,814 characters and 5,540 tokens.

**Console output dies on ₹ and Devanagari.** The Windows console defaults to
cp1252. Prefix one-off scripts with `PYTHONIOENCODING=utf-8`; the app itself
handles this through `core/console_utf8.py`.

## Prompt caching — the marker is not the mechanism

`build_system_blocks()` puts a `cache_control` marker on the static persona
block. That marker only does something if the block clears the serving model's
minimum cacheable prefix. Below it the API caches nothing, reports nothing and
raises nothing — the persona is re-billed in full on every turn while the code
reads as though it were cached.

Haiku 4.5 requires 4,096 tokens. As it stands English (1,849) and Spanish (786)
**never cache**; Hindi (5,540) and Marathi (6,323) do. Marathi only qualifies
because `CLAUDE_MODEL_MR` points it at Sonnet 4.6, whose floor is 1,024 — move
it back to Haiku and it still clears 4,096, but a shorter pack in the same
position would not.

Run `python -m tools.prompt_eval.cache_check` after any change to a persona
block or a model override. On a live call, `cache_read_input_tokens` should be
above zero from turn 2 onward for any pack that is supposed to cache.

Note that `input_tokens` from the API is the *uncached remainder*, not the whole
prompt. A working cache and a broken one are indistinguishable from that field
alone — use `UsageMeter.total_prompt_tokens`.

## Cost, and why Marathi is the expensive one

Per 12-turn call, at the rates in `CLAUDE_COST`:

| pack  | ₹/call | why |
|-------|--------|-----|
| en-IN | 2.69   | persona below the cache floor — full price every turn |
| hi-IN | 1.93   | cache works |
| mr-IN | 6.25   | `CLAUDE_MODEL_MR` → Sonnet, ~3× Haiku's input rate |

Marathi on Haiku would be ₹2.08. The override is deliberate — Marathi is
noticeably more accurate on the stronger model, and it is our thinnest-data
language — so treat that ₹4.17 as buying something, not as waste. Just decide it
knowingly, and remember `_rates_for()` bills an unlisted model at Haiku rates
with a warning, so a new override silently under-reports until you add it to
`CLAUDE_COST`.

## Rules for the language packs

**Bump `PROMPT_VERSION` in the same commit as any change to `_persona()`, the
few-shot exchanges, or `_dynamic_tail()`.** It is stamped onto every
`conversations` row. Without it, no measured change in reply quality can be
attributed to a prompt edit, and the eval tooling has nothing to compare across.

**She is female and addresses the user formally.** Feminine self-verbs
throughout, and आप/तुम्ही — never तुम, not once. `fix_honorifics()` rewrites the
oblique forms as a safety net, but it cannot fix a bare subject pronoun because
the verb would have to agree too. These rules are load-bearing; do not soften
them to make a sentence scan better.

**Exit-detection lists take only phrases that cannot occur in ordinary health
talk.** This is why `UNAVAILABLE_WORDS` has no entry for eating, sleeping,
doctors or hospitals: "I'm eating right now" must never end a call. Ending a
call mid-sentence on a lonely person is far worse than one wasted turn, so when
a phrase is arguable, leave it out and let `END_SIGNAL` handle it.

**Never put a bare number in `EMERGENCY_KEYWORDS`.** Matching is by substring,
so `108` fired on "sugar 102" and turned every vital reading into a cardiac
emergency. `_is_symptom_keyword()` now drops number-only entries, but do not
reintroduce them upstream.

**Strip the end signal before TTS, never after.** `strip_end_signal()` must run
ahead of `prepare_for_tts()` — `_clean()` only removes quotes and will happily
send `<<END>>` to the voice.

**`UsageMeter` is per call.** The phone server runs many calls in one process;
anything sharing the process-wide default while another call is live produces
mixed-up totals and wrong `api_costs` rows. Pass `session.usage` into
`stream_tokens()`.

## Commands you would not guess

```bash
./venv/Scripts/python.exe          # the interpreter — Windows venv layout

python -m tools.prompt_eval.cache_check   # do the personas clear the cache floor?
python -m tools.prompt_eval.report        # persona-rule violations over stored calls
python -m tools.prompt_eval.selftest      # do those checkers still detect anything?

python core/database.py            # migrate + seed (read the trap above first)
python smoke_local.py hi           # one local call, no telephony
```

`tools/prompt_eval/` is offline and free to run — it reads the `conversations`
table and calls no model. `selftest` matters more than it looks: a checker that
has quietly stopped matching reports 0.0%, which is indistinguishable from a
rule that is passing.

## Working on this

Prompt changes are evaluated, not argued. Run `report` before and after, on the
same window, and expect the violation rates to move in the direction you claimed
they would. The current worst offenders are English exceeding its three-sentence
cap (26% of replies) and Marathi announcing a hang-up and then carrying on (25%
of calls).

Keep in mind that four language packs means four surfaces. A change to one
pack's persona proves nothing about the other three, and Marathi has both the
worst violation rates and the thinnest data.
