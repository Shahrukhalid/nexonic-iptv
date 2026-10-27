#!/usr/bin/env python3
"""Review pending channel records (data/pending) and move them to data/approved or data/rejected.

    python scripts/review.py list
    python scripts/review.py approve <id> [--reviewer NAME] [--basis BASIS] [--confirm-screening]
    python scripts/review.py reject <id> --reason "why" [--reviewer NAME]

Approving needs an authorization basis and a passed adult-content screening on the record; if the record does not
have them yet, state them explicitly with --basis and --confirm-screening after checking the evidence. The data is
validated after every change and the change is rolled back if validation fails. Run scripts/generate.py and
scripts/validate.py afterwards (the Generate playlists workflow also does this after a merge).
"""

from __future__ import annotations

import argparse
import sys

import _bootstrap  # noqa: F401

from nexonic import review


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list pending records")
    a = sub.add_parser("approve", help="move a pending record to data/approved")
    a.add_argument("id")
    a.add_argument("--reviewer", default="maintainer", help="name recorded in review.reviewer")
    a.add_argument("--basis", help="authorization_basis to record (see nexonic/models.py)")
    a.add_argument("--confirm-screening", action="store_true", help="record adult_screening: pass after your review")
    a.add_argument("--note", default="", help="replace review.notes")
    r = sub.add_parser("reject", help="move a pending record to data/rejected")
    r.add_argument("id")
    r.add_argument("--reason", required=True)
    r.add_argument("--reviewer", default="maintainer")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "list":
            items = review.list_pending()
            for p in items:
                kind = "auto" if p.automated else "manual"
                print(
                    f"{p.id}\t{p.country}\t{kind}\t{p.file}\tbasis={p.authorization_basis}\tscreen={p.adult_screening}"
                )
                print(f"    {p.name} | {p.broadcaster} | {p.stream_url}")
            print(f"{len(items)} pending record(s).")
            return 0
        if args.cmd == "approve":
            dest = review.approve(
                args.id, args.reviewer, basis=args.basis, confirm_screening=args.confirm_screening, note=args.note
            )
        else:
            dest = review.reject(args.id, args.reason, args.reviewer)
    except review.ReviewError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    print(f"{args.cmd}d {args.id}: now in data/{dest.relative_to(review.DATA).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
