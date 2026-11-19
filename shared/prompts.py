"""Build LLM system prompts from language packs."""

# The token she writes to end the call herself.
#
# Exit detection used to be nothing but a per-language keyword list, so anything
# paraphrased — "I should get going", "बरं, मला आता जायचंय" — was missed and the
# caller had to say goodbye two or three times. This rides on the reply that is
# already streaming, so it costs no extra API call and no extra latency.
#
# Lives here, in a leaf module, so both the language packs and
# services/conversation_engine.py can import it without an import cycle.
# strip_end_signal() in conversation_engine.py removes it before TTS.
END_SIGNAL = "<<END>>"


def build_system(lang_svc, user_name: str, ctx: dict, log=None):
    """
    Prefer cacheable system blocks (static persona + small per-turn tail).
    Falls back to the plain string prompt for older language packs.
    """
    builder = getattr(lang_svc, "build_system_blocks", None)
    if callable(builder):
        try:
            return builder(user_name, ctx)
        except Exception as e:
            if log is not None:
                log.warning(f"build_system_blocks failed ({e}); using plain prompt")
    return lang_svc.build_prompt(user_name, ctx)
