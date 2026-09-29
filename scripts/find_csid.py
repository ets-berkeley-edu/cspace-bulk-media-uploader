#!/usr/bin/env python3
"""Which BMU job created a CollectionSpace record? Looks the CSID up in the audit log's CSID index (design: Reading
the audit log). Works after the job itself is deleted, for about a year.

  cd backend && python ../scripts/find_csid.py <csid> [<csid> ...]

Uses the same BMU_* settings as the web app (tables, region, endpoints).
"""
import sys

sys.path.insert(0, ".")
from bmu.config import get_settings  # noqa: E402
from bmu.storage import Storage  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    storage = Storage(get_settings())
    for csid in sys.argv[1:]:
        e = storage.find_csid(csid)
        if not e:
            print(f"{csid}: not created by the BMU in the last year (or not found)")
            continue
        where = f"row {e['row']} ({e['file']})" if e.get("row") else "the job itself"
        print(f"{csid}: {e['recordType']} created by job {e['job']} “{e.get('jobName', '')}”, run {e['run']}, {where}, step {e['step']}")


if __name__ == "__main__":
    main()
