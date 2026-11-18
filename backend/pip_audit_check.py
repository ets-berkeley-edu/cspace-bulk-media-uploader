"""pip-audit over the pinned requirements files, failing a pull request only for what it changes.

CI runs this in place of pip-audit (ci.yml's `dependencies` job on every pull request and push, audit.yml every
Monday). Run on its own (on pushes to main, every Monday, and by hand), it fails on any known vulnerability in a pinned
package, as plain pip-audit does.

pip-audit asks a live vulnerability database (PyPI's), which changes without any change here: a newly published
vulnerability would otherwise fail every open pull request at once. So on a pull request it runs with
--changed-since <the base commit>, and fails only on a vulnerability in a package whose pinned versions in the four
requirements files the pull request changes (added, removed or moved to another version), or when pip-audit itself
fails. A vulnerability in a package it doesn't change is a warning: a ::warning:: line, and in the job's summary. The
push to main that follows the merge runs the full check, so main still turns red. If the base's requirements files
can't be read, the whole check is strict. (There is no allowlist, unlike frontend/scripts/audit.js.)

    python pip_audit_check.py                         in backend/, with requirements-tools.txt installed
    python pip_audit_check.py --changed-since HEAD^1  (a pull request's checkout is its merge commit; its first
                                                       parent is the base)
"""

import argparse
import json
import os
import re
import subprocess
import sys

# Two runs: the tools file pins click differently (see requirements-tools.in), and pip-audit refuses a package pinned
# twice.
GROUPS = [
    ["requirements.txt", "requirements-dev.txt", "requirements-sim.txt"],
    ["requirements-tools.txt"],
]
FILES = [name for group in GROUPS for name in group]

PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;\\]+)")


def canonical(name):
    """A package's name as PyPI compares names (PEP 503), as pip-audit reports it."""
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned_versions(texts):
    """Each package's pinned versions (name==version lines) across requirements files' texts, by canonical name."""
    versions = {}
    for text in texts:
        for line in text.splitlines():
            match = PIN.match(line.strip())
            if match:
                versions.setdefault(canonical(match.group(1)), set()).add(match.group(2))
    return versions


def changed_packages(base_texts, head_texts):
    """The names of the packages added, removed or moved to another version between two sets of requirements files."""
    base, head = pinned_versions(base_texts), pinned_versions(head_texts)
    return {name for name in base.keys() | head.keys() if base.get(name) != head.get(name)}


def check(reports, changed=None):
    """What fails the check and what is only a warning, from pip-audit's JSON reports (one per run).

    Without `changed`, every vulnerability fails. With changed (the packages a pull request changes), a vulnerability in
    a package it doesn't change is a warning instead.
    """
    failures, warnings = [], []
    seen = set()
    for report in reports:
        for dependency in report.get("dependencies", []):
            name = canonical(dependency["name"])
            for vuln in dependency.get("vulns", []):
                key = (name, dependency["version"], vuln["id"])
                if key in seen:
                    continue
                seen.add(key)
                aliases = [a for a in vuln.get("aliases", []) if a.startswith("GHSA-") or a.startswith("CVE-")]
                fixes = ", ".join(vuln.get("fix_versions", [])) or "none yet"
                problem = (
                    f"{vuln['id']}{' (' + ', '.join(aliases) + ')' if aliases else ''} in {name} "
                    f"{dependency['version']}: fixed in {fixes}"
                )
                if changed is None or name in changed:
                    failures.append(problem)
                else:
                    warnings.append(f"{problem} (in a package this pull request doesn't change)")
    return failures, warnings


def _at_commit(ref, path):
    """A file's text at a git commit (path relative to backend/), or None if git can't give it."""
    run = subprocess.run(["git", "show", f"{ref}:./{path}"], capture_output=True, text=True)
    return run.stdout if run.returncode == 0 else None


def _audit(files):
    command = [sys.executable, "-m", "pip_audit", "--require-hashes", "--disable-pip", "--format", "json",
               "--progress-spinner", "off"]
    for name in files:
        command += ["-r", name]
    run = subprocess.run(command, capture_output=True, text=True)
    try:
        return json.loads(run.stdout), None
    except json.JSONDecodeError:
        return None, f"pip-audit {' '.join(files)} gave no report (exit {run.returncode}):\n{run.stderr}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--changed-since", metavar="REF", help="fail only for packages changed since this git ref")
    args = parser.parse_args(argv)

    notes, changed = [], None
    if args.changed_since:
        base = [_at_commit(args.changed_since, name) for name in FILES]
        if all(text is not None for text in base):
            heads = []
            for name in FILES:
                with open(name, encoding="utf-8") as f:
                    heads.append(f.read())
            changed = changed_packages(base, heads)
            listed = f" ({', '.join(sorted(changed))})" if changed else ""
            notes.append(f"Compared with {args.changed_since}: {len(changed)} pinned package(s) changed{listed}.")
        else:
            notes.append(f"Could not read the requirements files at {args.changed_since}: checking every package, "
                         "as on main.")

    reports, failures = [], []
    for files in GROUPS:
        report, error = _audit(files)
        if error:
            failures.append(error)
        else:
            reports.append(report)
    found, warnings = check(reports, changed)
    failures += found

    for note in notes:
        print(note)
    for warning in warnings:
        print(f"::warning::{warning}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and (failures or warnings or notes):
        def listed(items):
            return "".join(f"- {item}\n" for item in items)
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### pip-audit\n\n" + "".join(f"{note}\n\n" for note in notes))
            if failures:
                f.write(f"Fails the check:\n\n{listed(failures)}\n")
            if warnings:
                f.write("To fix on main, or in the pull request that changes them (they don't fail this one):\n\n"
                        f"{listed(warnings)}\n")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    if warnings:
        print(f"pip-audit: nothing this pull request changes, but {len(warnings)} warning(s) above to fix on main.")
    else:
        print("pip-audit: no known vulnerabilities.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
