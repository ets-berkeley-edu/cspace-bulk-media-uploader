"""Per-tenant configuration (handling options, filename rule, publish field, vocabularies)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import PurePosixPath
from typing import Any

import yaml


@dataclass(frozen=True)
class Handling:
    id: str
    label: str
    object: str  # existing | create | none
    id_rule: str  # object | image
    legacy: str = ""


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
            "mediaTypes": [o.__dict__ for o in self.media_types],
            "languageDefault": self.language_default,
            "authorityFields": self.authority_fields,
        }


@lru_cache
def load_tenant(key: str) -> Tenant:
    text = resources.files("bmu.tenants").joinpath(f"{key}.yaml").read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
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
