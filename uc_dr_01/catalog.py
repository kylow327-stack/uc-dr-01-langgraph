"""Load PACK-v1, the taxonomy, breaker defaults, and named case fixtures."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from uc_dr_01.errors import DemoError

NAMED_CASES: dict[str, str] = {
    "CASE-2041": "cases/case-low-complete.json",
    "CASE-2077": "cases/case-med-gap.json",
    "CASE-2118": "cases/case-high-confidence.json",
    "CASE-PASTE": "cases/case-paste.json",
}

ProfileId = Literal["individual_onboarding", "sme_onboarding"]
BreakerState = Literal["closed", "half-open", "open"]


class FieldValue(BaseModel):
    id: str
    label: str
    value: str
    confidence: float = Field(ge=0, le=1)
    page: int = Field(ge=1)


class FixtureDocument(BaseModel):
    docId: str
    fileName: str
    classifiedType: str
    pages: int = Field(ge=1)
    fields: list[FieldValue]


class FixtureNarrative(BaseModel):
    """Briefing text. A tier key, if present, is kept only so grounding can ignore it."""

    model_config = ConfigDict(extra="allow")

    summary: str
    factors: list[dict[str, Any]]


class CaseFixture(BaseModel):
    model_config = ConfigDict(extra="ignore")

    caseId: str = Field(min_length=1)
    folderPath: str = Field(min_length=1)
    profile: ProfileId
    title: str
    demoScript: str = ""
    subjectLabel: str
    blurb: str = ""
    identityConflict: bool = False
    conflictNote: str | None = None
    elevatedIndicators: list[str] = Field(default_factory=list)
    documents: list[FixtureDocument]
    fixtureNarrative: FixtureNarrative


class PackProfile(BaseModel):
    label: str
    requiredDocs: list[str]
    requiredFields: dict[str, list[str]]


class PackV1(BaseModel):
    packId: Literal["PACK-v1"]
    confidenceFloor: float = Field(gt=0, le=1)
    allowPrefix: str
    profiles: dict[str, PackProfile]


class TaxonomyEntry(BaseModel):
    id: str
    label: str
    description: str


class TaxonomyFile(BaseModel):
    taxonomyId: str
    entries: list[TaxonomyEntry]


class BreakerDef(BaseModel):
    id: str
    name: str
    trip: str
    degrade: str
    defaultState: BreakerState
    exampleSignal: str


class BreakerFile(BaseModel):
    caption: str
    breakers: list[BreakerDef]


def fixtures_root() -> Path:
    override = os.environ.get("UC_DR_01_FIXTURES")
    if override:
        root = Path(override)
        if (root / "pack-v1.json").is_file():
            return root
        raise DemoError(f"UC_DR_01_FIXTURES={override} does not contain pack-v1.json.")
    candidates = [
        Path(__file__).resolve().parents[1] / "fixtures",
        Path.cwd() / "fixtures",
    ]
    for candidate in candidates:
        if (candidate / "pack-v1.json").is_file():
            return candidate
    raise DemoError(
        "PACK-v1 fixtures not found. Run from the repository root, or set UC_DR_01_FIXTURES."
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DemoError(f"Missing fixture file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DemoError(f"{path} is not valid JSON: {exc.msg} (line {exc.lineno}).") from exc


def _validate(model: type[BaseModel], data: Any, label: str) -> dict[str, Any]:
    try:
        return model.model_validate(data).model_dump()
    except ValidationError as exc:
        lines = []
        for err in exc.errors()[:6]:
            loc = ".".join(str(part) for part in err["loc"]) or model.__name__
            lines.append(f"{loc}: {err['msg']}")
        detail = "\n".join(lines)
        raise DemoError(f"{label} failed validation:\n{detail}") from exc


@lru_cache(maxsize=1)
def load_pack() -> dict[str, Any]:
    return _validate(PackV1, _read_json(fixtures_root() / "pack-v1.json"), "PACK-v1")


@lru_cache(maxsize=1)
def load_taxonomy() -> dict[str, Any]:
    return _validate(TaxonomyFile, _read_json(fixtures_root() / "taxonomy.json"), "TAX-v1")


@lru_cache(maxsize=1)
def load_breaker_file() -> dict[str, Any]:
    return _validate(BreakerFile, _read_json(fixtures_root() / "breakers.json"), "breakers")


def taxonomy_ids() -> list[str]:
    return [entry["id"] for entry in load_taxonomy()["entries"]]


def breaker_states(overrides: dict[str, str] | None = None) -> list[dict[str, str]]:
    overrides = overrides or {}
    allowed = {"closed", "half-open", "open"}
    rows: list[dict[str, str]] = []
    for breaker in load_breaker_file()["breakers"]:
        state = overrides.get(breaker["id"], breaker["defaultState"])
        if state not in allowed:
            raise DemoError(f"Breaker {breaker['id']} state must be closed, half-open, or open.")
        rows.append({"id": breaker["id"], "state": state})
    unknown = sorted(set(overrides) - {row["id"] for row in rows})
    if unknown:
        raise DemoError(f"Unknown breaker id(s): {', '.join(unknown)}.")
    return rows


def parse_case(data: Any, label: str = "case fixture") -> dict[str, Any]:
    if not isinstance(data, dict):
        raise DemoError(f"{label} must be a JSON object.")
    return _validate(CaseFixture, data, label)


def load_case(case_id: str) -> dict[str, Any]:
    relative = NAMED_CASES.get(case_id)
    if relative is None:
        known = ", ".join(NAMED_CASES)
        raise DemoError(f"Unknown case {case_id!r}. Known cases: {known}.")
    return parse_case(_read_json(fixtures_root() / relative), case_id)


def load_fixture(path: str | Path) -> dict[str, Any]:
    fixture_path = Path(path)
    if not fixture_path.is_file():
        raise DemoError(f"Fixture file not found: {fixture_path}")
    return parse_case(_read_json(fixture_path), str(fixture_path))
