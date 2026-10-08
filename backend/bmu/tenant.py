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
    # Design (Handling per document): field presets, {field: value} for fields in PRESETTABLE, checked at load
    presets: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

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

# Design (Handling per document): the fields a handling option can preset, as in the UI mockup. Media type and
# language repeat (lists of option values / language refNames); contributor is an authority refName.
PRESETTABLE = ("type", "contributor", "copyright", "language")
PRESET_REPEATING = ("type", "language")

# refNames (design: Authority term fields; Media record fields)
AUTHORITY_REF = re.compile(r"^urn:cspace:(?P<domain>[^:]+):(?P<service>\w+):name\((?P<vocab>[^)]+)\):item:name\((?P<short>[^)]+)\)'(?P<display>.*)'$")
LANGUAGE_REF = re.compile(r"^urn:cspace:[^:]+:vocabularies:name\(languages\):item:name\([^)]+\)'[^']*'$")


def role_name(tenant_id: str, display_name: str) -> str:
    """The roleName CollectionSpace stores for a role created with this display name (design: Job scheduling).
    The UI (cspace-ui.js) sanitizes the display name: upper-case it, turn spaces into underscores, drop every
    character other than A-Z, 0-9 and _, and collapse repeated underscores. The services layer then upper-cases
    it and adds ROLE_<tenantId>_ unless it is already there. "+ cow" in tenant 15 -> "_COW" -> "ROLE_15__COW"
    (the prefix is added after the collapse, so that double underscore stays)."""
    s = re.sub(r"_+", "_", re.sub(r"[^A-Z0-9_]", "", display_name.upper().replace(" ", "_"))).upper()
    prefix = f"ROLE_{tenant_id}_"
    return s if s.startswith(prefix) else prefix + s


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
    # Display names of the CollectionSpace roles that make a user BMU staff or a BMU intern (design: Roles). The
    # roles carry no permissions; they only tell the BMU what the user may do in the BMU.
    staff_roles: tuple[str, ...] = ()
    intern_roles: tuple[str, ...] = ()
    # What a staff account must be allowed to do in CollectionSpace to sign in: resource -> action letters
    # (C)reate (R)ead (U)pdate, as accounts/0/accountperms reports them.
    staff_permissions: dict[str, str] = field(default_factory=dict)
    # Whether the tenant's Media extension has primaryDisplay, which the BMU sets to false (UCJEPS's has none).
    primary_display: bool = True

    @property
    def media_type_values(self) -> set[str]:
        return {o.value for o in self.media_types}

    def handling_by_id(self, hid: str) -> Handling | None:
        return next((h for h in self.handling if h.id == hid), None)

    def preset_value(self, hid: str, name: str) -> Any:
        """What a handling's presets put in a field (design: Handling per document): its preset, else, for
        Language, the tenant's default language, else empty."""
        h = self.handling_by_id(hid)
        v = (h.presets if h else {}).get(name)
        if name == "language" and not v:
            v = [self.language_default]
        if name in PRESET_REPEATING:
            return list(v or [])
        return v or ""

    def role_of(self, tenant_id: str, role_names: list[str]) -> str:
        """Design (Roles): "staff" if any of the user's roleNames (from accounts/0/accountroles) is the roleName of
        one of the tenant's staff_roles, else "intern" if one is an intern role, else "" (not a BMU user). Staff
        wins when a user has both. Compared case-insensitively (see role_name)."""
        have = {(r or "").strip().upper() for r in role_names}
        for role, names in (("staff", self.staff_roles), ("intern", self.intern_roles)):
            if tenant_id and have & {role_name(tenant_id, n).upper() for n in names}:
                return role
        return ""

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
    return parse_tenant(yaml.safe_load(text), key)


def parse_tenant(raw: dict[str, Any], key: str) -> Tenant:
    """A tenant from its configuration (the parsed yaml), checked; raises ValueError naming what's wrong."""
    bad = [h["id"] for h in raw["handling"] if h["object"] not in (*OBJECT_STEP, "none")]
    if bad:
        raise ValueError(f"{key}.yaml: unknown object behavior in handling {', '.join(bad)}")
    tenant = Tenant(
        key=raw["key"],
        name=raw["name"],
        domain=raw["domain"],
        media_extension=raw["media_extension"],
        handling=tuple(Handling(**{**h, "presets": dict(h.get("presets") or {})}) for h in raw["handling"]),
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
        staff_roles=tuple((raw.get("roles") or {}).get("staff") or ()),
        intern_roles=tuple((raw.get("roles") or {}).get("intern") or ()),
        staff_permissions={str(k): str(v).upper() for k, v in (raw.get("staff_permissions") or {}).items()},
        primary_display=bool(raw.get("primary_display", True)),
    )
    values = tenant.publish.get("values")
    if values is not None and not (isinstance(values, list) and len(values) == 2 and all(isinstance(v, str) and v for v in values)):
        raise ValueError(f"{key}.yaml: publish.values must be two words, for public and not public, such as ['yes', 'no'] (quoted: YAML reads a bare yes or no as true or false)")
    for h in tenant.handling:
        problems = preset_problems(tenant, h)
        if problems:
            raise ValueError(f"{key}.yaml: presets of handling {h.id}: {'; '.join(problems)}")
    return tenant


def preset_problems(tenant: Tenant, h: Handling) -> list[str]:
    """Design (Handling per document): presets must resolve to values in the tenant's option lists, vocabularies
    and authorities. Checked at load for their form: media types from the tenant's option list, languages as
    refNames of the languages vocabulary, the contributor as a refName of one of the field's authority sources.
    Whether the terms still exist in CollectionSpace is checked with the rows (validation while editing)."""
    out = []
    unknown = sorted(set(h.presets) - set(PRESETTABLE))
    if unknown:
        out.append(f"{', '.join(unknown)} can't be preset (only {', '.join(PRESETTABLE)})")
    for name, v in h.presets.items():
        if name in PRESET_REPEATING and not (isinstance(v, list) and all(isinstance(x, str) and x for x in v)):
            out.append(f"{name} must be a list")
        elif name == "type":
            out += [f"media type {x!r} isn't in media_types" for x in v if x not in tenant.media_type_values]
        elif name == "language":
            out += [f"language {x!r} isn't a refName of {tenant.domain}'s languages vocabulary" for x in v
                    if not LANGUAGE_REF.match(x) or not x.startswith(f"urn:cspace:{tenant.domain}:")]
        elif name == "contributor":
            sources = [tenant.authorities[s] for s in tenant.authority_fields.get(name, tenant.authorities) if s in tenant.authorities]
            m = AUTHORITY_REF.match(v) if isinstance(v, str) else None
            if not m or m["domain"] != tenant.domain or not any(
                    m["service"] == s["service"] and m["vocab"] == s["vocabulary"] for s in sources):
                out.append(f"contributor must be the full refName of a term in one of its authorities "
                           f"({', '.join(s['service'] + '/' + s['vocabulary'] for s in sources)})")
        elif name == "copyright" and not isinstance(v, str):
            out.append("copyright must be text")
    return out


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
