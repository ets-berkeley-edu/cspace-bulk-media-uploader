"""Per-tenant configuration (handling options, filename rule, publish field, vocabularies)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import PurePosixPath
from typing import Any

import yaml

from .filetypes import SUPPORTED_EXTENSIONS, SUPPORTED_HINT


@dataclass(frozen=True)
class Handling:
    id: str
    label: str
    object: str  # existing | create | either | none (see OBJECT_STEP)
    id_rule: str  # object | image
    legacy: str = ""

    @property
    def object_step(self) -> str | None:
        """The row step that finds or creates this handling's Object, or None for media only."""
        return OBJECT_STEP.get(self.object)


# How each handling's object behavior runs (design: Handling per document):
#   existing  the object must exist: "Find object"; none found fails the row (object_gone)
#   create    a new object: "Create object"; one that already exists fails the row (object_exists)
#   either    link to the object if it exists, create it if it doesn't: "Find or create object"
OBJECT_STEP = {"existing": "findObject", "create": "createObject", "either": "findOrCreateObject"}
OBJECT_STEPS = tuple(OBJECT_STEP.values())


@dataclass(frozen=True)
class Option:
    """An option-list value and its display label, as in the tenant's UI configuration."""
    value: str
    label: str


@dataclass(frozen=True)
class Tenant:
    key: str
    name: str
    domain: str
    media_extension: str
    handling: tuple[Handling, ...]
    publish: dict[str, Any]
    filename_hint: str
    filename_pattern: re.Pattern[str]
    media_types: tuple[Option, ...]
    language_default: str
    authorities: dict[str, dict[str, str]]
    authority_fields: dict[str, list[str]] = field(default_factory=dict)
    # From the tenant's UI profile; cspace-ui's defaults are 500 ms and 3 characters
    autocomplete: dict[str, int] = field(default_factory=lambda: {"find_delay_ms": 500, "min_length": 3})
    sensitivity: dict[str, Any] = field(default_factory=dict)  # Object-level rules (design: Protected files)

    @property
    def media_type_values(self) -> set[str]:
        return {o.value for o in self.media_types}

    def handling_by_id(self, hid: str) -> Handling | None:
        return next((h for h in self.handling if h.id == hid), None)

    def public_summary(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "handling": [h.__dict__ for h in self.handling],
            "publish": self.publish,
            "filenameHint": self.filename_hint,
            "filenamePattern": self.filename_pattern.pattern,
            "mediaTypes": [o.__dict__ for o in self.media_types],
            "languageDefault": self.language_default,
            "fileTypes": list(SUPPORTED_EXTENSIONS),
            "fileTypesHint": SUPPORTED_HINT,
            "authorityFields": self.authority_fields,
            "autocomplete": {"findDelayMs": self.autocomplete["find_delay_ms"], "minLength": self.autocomplete["min_length"]},
            "sensitivity": {"summary": self.sensitivity.get("summary", ""), "explain": self.sensitivity.get("explain", [])},
        }


@lru_cache
def load_tenant(key: str) -> Tenant:
    text = resources.files("bmu.tenants").joinpath(f"{key}.yaml").read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    bad = [h["id"] for h in raw["handling"] if h["object"] not in (*OBJECT_STEP, "none")]
    if bad:
        raise ValueError(f"{key}.yaml: unknown object behavior in handling {', '.join(bad)}")
    return Tenant(
        key=raw["key"],
        name=raw["name"],
        domain=raw["domain"],
        media_extension=raw["media_extension"],
        handling=tuple(Handling(**h) for h in raw["handling"]),
        publish=raw["publish"],
        filename_hint=raw["filename"]["hint"],
        filename_pattern=re.compile(raw["filename"]["pattern"]),
        media_types=tuple(Option(m, m) if isinstance(m, str) else Option(m["value"], m.get("label", m["value"]))
                          for m in raw["media_types"]),
        language_default=raw["language"]["default"],
        authorities=raw["authorities"],
        authority_fields=raw.get("authority_fields", {}),
        autocomplete={"find_delay_ms": 500, "min_length": 3, **(raw.get("autocomplete") or {})},
        sensitivity=raw.get("sensitivity") or {},
    )


def parse_filename(tenant: Tenant, filename: str) -> dict[str, Any]:
    """Split a filename into the object number and image number, using the tenant's rule.

    Returns {"ok": bool, "obj": str, "img": str}. The image number is the filename without
    its extension (legacy PAHMA behavior for media-only records).
    """
    base = PurePosixPath(filename).name
    stem = base.rsplit(".", 1)[0] if "." in base else base
    m = tenant.filename_pattern.match(stem)
    if not m:
        return {"ok": False, "obj": "", "img": stem}
    return {"ok": True, "obj": m.group("obj"), "img": stem}
