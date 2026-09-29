"""Object-level sensitivity (design: Protected files). The web app reads the Object record a document links
to and applies the tenant's rules: a "protect" rule makes the document a protected file, a "warn" rule is a
soft signal that only raises a warning. The rules are tenant configuration (tenants/<key>.yaml), not code.
"""
from __future__ import annotations

from typing import Any, Iterable
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":")[-1]


def _values(scope: Element, name: str) -> list[str]:
    return [(e.text or "").strip() for e in scope.iter() if _local(e.tag) == name and (e.text or "").strip()]


def _cond(scope: Element, c: dict[str, Any]) -> bool:
    vals = _values(scope, c["element"])
    if c.get("present"):
        return bool(vals)
    if "contains" in c:
        return any(c["contains"].lower() in v.lower() for v in vals)
    if "equals" in c:
        return any(v.lower() == str(c["equals"]).lower() for v in vals)
    if "in" in c:
        wanted = {str(x).lower() for x in c["in"]}
        return any(v.lower() in wanted for v in vals)
    raise ValueError(f"sensitivity condition needs present, contains, equals or in: {c}")


def _scopes(root: Element, within: str | None) -> Iterable[Element]:
    return (e for e in root.iter() if _local(e.tag) == within) if within else [root]


def _matches(root: Element, rule: dict[str, Any]) -> bool:
    return any(all(_cond(scope, c) for c in rule["all"]) for scope in _scopes(root, rule.get("within")))


def evaluate(config: dict[str, Any] | None, object_xml: bytes) -> dict[str, Any]:
    """{"protect": [reasons], "warn": [reasons], "hides": bool} for an Object record."""
    out: dict[str, Any] = {"protect": [], "warn": [], "hides": False}
    if not config:
        return out
    root = SafeET.fromstring(object_xml)
    for rule in config.get("protect", []):
        if _matches(root, rule):
            out["protect"].append(rule["reason"])
            out["hides"] = out["hides"] or bool(rule.get("hides"))
    if not out["protect"]:  # a soft signal matters only when the file isn't protected anyway
        out["warn"] = [r["reason"] for r in config.get("warn", []) if _matches(root, r)]
    return out
