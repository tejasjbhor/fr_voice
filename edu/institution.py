"""
edu/institution.py — the institution record.

This is the only source of fact in the product. The agent is instructed to
state nothing that is not in here, so a missing field is not a cosmetic gap: it
is the difference between "our fee for Grade 5 is X" and a number the model
invented on a recorded call to a parent.

Loaded from JSON in single-institution mode. The dataclass is deliberately flat
and boring so that it maps one-to-one onto table columns when multi-tenancy
lands — `from_row()` is already stubbed for that.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


class InstitutionError(ValueError):
    """Raised when an institution file is missing something the agent needs."""


# Fields without which the agent cannot open a call honestly. A校 with no name
# cannot introduce itself; with no grades it cannot say who it is calling about.
REQUIRED = ("name", "kind", "city", "grades_open")

# Fields the agent will be asked about on nearly every call. Missing ones are
# not fatal — she says a counsellor will confirm — but each one is a question
# she cannot answer, so the loader reports them.
EXPECTED = (
    "curriculum",
    "fee_structure",
    "admission_process",
    "eligibility",
    "documents_required",
    "timings",
    "transport",
    "entrance_test",
    "application_deadline",
    "campus_visit",
)


@dataclass
class Institution:
    # Identity
    name: str
    kind: str                      # school | college | university | coaching
    city: str
    grades_open: list[str] = field(default_factory=list)

    # Agent identity (overrides edu.config defaults when set)
    agent_name: str | None = None
    agent_role: str | None = None

    # Personality overrides (same vocabulary as edu.config)
    personality: dict[str, str] = field(default_factory=dict)

    # Facts. Every one of these is rendered into the cached knowledge block.
    academic_year: str | None = None
    curriculum: str | None = None
    eligibility: dict[str, str] = field(default_factory=dict)
    fee_structure: dict[str, str] = field(default_factory=dict)
    admission_process: list[str] = field(default_factory=list)
    documents_required: list[str] = field(default_factory=list)
    entrance_test: str | None = None
    application_deadline: str | None = None
    timings: str | None = None
    transport: str | None = None
    hostel: str | None = None
    facilities: list[str] = field(default_factory=list)
    activities: list[str] = field(default_factory=list)
    student_teacher_ratio: str | None = None
    campus_visit: str | None = None
    scholarships: str | None = None
    contact: dict[str, str] = field(default_factory=dict)

    # Areas the institution draws from. Doubles as the keyword list the
    # qualification extractor uses to hear where a parent lives, which is why
    # it lives on the institution rather than in a language pack — the answer
    # "Kothrud" is only meaningful next to a school that serves Kothrud.
    catchment_areas: list[str] = field(default_factory=list)

    # Local-script spellings for the areas above, keyed by the canonical name:
    #   {"Kothrud": ["कोथरूड", "कोथरुड"]}
    # Required for any language whose callers do not use Latin script — a
    # Devanagari transcript shares no characters with a Latin area list, so
    # without these the locality slot never fills on Hindi or Marathi calls.
    catchment_aliases: dict[str, list[str]] = field(default_factory=dict)

    # Anything the agent must never say, per the institution. Rendered as hard
    # prohibitions. Use for legal or commercial sensitivities: discounts,
    # comparisons with named competitors, guarantees of admission.
    prohibited_claims: list[str] = field(default_factory=list)

    # Free-text FAQ pairs for anything the structured fields do not cover.
    faqs: list[dict[str, str]] = field(default_factory=list)

    # Populated by the loader; not part of the file.
    source_path: str | None = None
    missing_expected: list[str] = field(default_factory=list)

    # ── Derived ───────────────────────────────────────────────────

    def known_topics(self) -> list[str]:
        """Topics the agent can actually speak to. Rendered into the prompt so
        she knows the edge of her own knowledge rather than discovering it
        mid-sentence."""
        found = []
        for key in EXPECTED:
            if _present(getattr(self, key, None)):
                found.append(key)
        if self.faqs:
            found.append("faqs")
        if _present(self.hostel):
            found.append("hostel")
        if _present(self.facilities) or _present(self.activities):
            found.append("facilities")
        if _present(self.scholarships):
            found.append("scholarships")
        return found

    def unknown_topics(self) -> list[str]:
        return [k for k in EXPECTED if not _present(getattr(self, k, None))]

    def display_kind(self) -> str:
        return {
            "school": "school",
            "college": "college",
            "university": "university",
            "coaching": "coaching institute",
            "software": "software platform",
            "saas": "software platform",
        }.get((self.kind or "").lower(), self.kind or "institution")

    # ── Loaders ───────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str | None = None) -> "Institution":
        missing_required = [k for k in REQUIRED if not _present(data.get(k))]
        if missing_required:
            raise InstitutionError(
                f"institution file is missing required field(s): "
                f"{', '.join(missing_required)}"
            )

        known = {f for f in cls.__dataclass_fields__}  # noqa: SLF001
        # Unknown keys are dropped rather than raising: a school's file will
        # accumulate fields the code does not read yet, and refusing to load on
        # that would make the file harder to edit than it needs to be.
        payload = {k: v for k, v in data.items() if k in known}
        inst = cls(**payload)
        inst.source_path = source
        inst.missing_expected = inst.unknown_topics()
        return inst

    @classmethod
    def load(cls, path: str | None = None) -> "Institution":
        from edu import config

        path = path or config.INSTITUTION_FILE
        if not os.path.exists(path):
            raise InstitutionError(
                f"institution file not found: {path}\n"
                f"Set INSTITUTION_FILE in .env, or copy "
                f"edu/data/institutions/xyz_international_school.json and edit it."
            )
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return cls.from_dict(data, source=path)

    @classmethod
    def from_row(cls, row) -> "Institution":  # pragma: no cover - multi-tenant stub
        """Placeholder for the multi-tenant path. When `institutions` becomes a
        table, this replaces load() and nothing else in edu/ has to change."""
        raise NotImplementedError(
            "multi-tenant loading is not implemented in single-institution mode"
        )


def _present(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


# Module-level cache. The institution file is read once per process; a call
# that re-read it per turn would be re-rendering the cached knowledge block and
# risking a cache miss on a file whose mtime changed mid-call.
_CACHED: Institution | None = None


def get_institution(path: str | None = None, reload: bool = False) -> Institution:
    global _CACHED
    if _CACHED is None or reload or path:
        _CACHED = Institution.load(path)
    return _CACHED
