"""Split the BMU's deployer policy into the customer managed policies Operations attaches (deploy/iam/README.md).

    python3 deploy/iam/split-policy.py           # writes deploy/iam/out/bmu-deployer-policy-part<N>.json
    python3 deploy/iam/split-policy.py --check   # only checks that it fits
    python3 deploy/iam/split-policy.py --json    # prints the parts as a JSON list of documents, for ./bmu aws
                                                 # rehearsal-vpc (deploy/terraform/rehearsal, policy_parts)

bmu-deployer-policy.json is the only copy of the policy: the parts are always made from it, never stored (out/ isn't
committed). A customer managed policy holds at most 6,144 characters, whitespace not counted, and a role at most 10
managed policies; the policy is split between whole statements into at most MAX_PARTS parts, each repeating the
region Deny (OnlyItsRegion), so that no part on its own allows anything outside the region.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY = HERE / "bmu-deployer-policy.json"
OUT = HERE / "out"
LIMIT = 6144
MAX_PARTS = 3
REGION_DENY = "OnlyItsRegion"


def size(doc) -> int:
    """The length AWS counts: the JSON without whitespace (no string in the policy contains any)."""
    return len(json.dumps(doc, separators=(",", ":")))


def split(policy: dict) -> list[dict]:
    """First-fit by size, largest statement first; each part keeps the policy's order and starts with the Deny."""
    deny = [s for s in policy["Statement"] if s.get("Sid") == REGION_DENY]
    if len(deny) != 1:
        raise ValueError(f"the policy needs exactly one {REGION_DENY} statement")
    rest = [s for s in policy["Statement"] if s.get("Sid") != REGION_DENY]
    order = {id(s): i for i, s in enumerate(rest)}
    parts: list[list[dict]] = []
    for st in sorted(rest, key=lambda s: -size(s)):
        for part in parts:
            if size(_doc(policy, deny + part + [st])) <= LIMIT:
                part.append(st)
                break
        else:
            if size(_doc(policy, deny + [st])) > LIMIT:
                raise ValueError(f"statement {st.get('Sid')} alone is over {LIMIT} characters")
            parts.append([st])
    if len(parts) > MAX_PARTS:
        raise ValueError(f"the policy needs {len(parts)} parts; Operations attaches at most {MAX_PARTS}")
    return [_doc(policy, deny + sorted(p, key=lambda s: order[id(s)])) for p in parts]


def _doc(policy: dict, statements: list[dict]) -> dict:
    return {"Version": policy["Version"], "Statement": statements}


def main(argv: list[str]) -> int:
    policy = json.loads(POLICY.read_text())
    parts = split(policy)
    if "--json" in argv:
        print(json.dumps([json.dumps(p, separators=(",", ":")) for p in parts]))
        return 0
    print(f"{POLICY.name}: {size(policy)} characters, in {len(parts)} parts of at most {LIMIT}:")
    if "--check" not in argv:
        OUT.mkdir(exist_ok=True)
        for old in OUT.glob("bmu-deployer-policy-part*.json"):
            old.unlink()
    for n, part in enumerate(parts, 1):
        sids = ", ".join(s["Sid"] for s in part["Statement"][1:])
        name = f"bmu-deployer-policy-part{n}.json"
        if "--check" not in argv:
            (OUT / name).write_text(json.dumps(part, indent=2) + "\n")
        print(f"  {name}: {size(part)} characters: {REGION_DENY}, {sids}")
    if "--check" not in argv:
        print(f"Written to {OUT} (not committed).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
