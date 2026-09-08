"""One-time claim of pre-Phase-8.2 library data for a real registered account
(spec §6.1, plan.md Phase 8.2).

The `47cf8fa2576e` migration adds `library_entry.user_id` as nullable and
never guesses or invents an owner for pre-existing rows — this script is the
deliberate, human-triggered step that does that instead. Run it once, after
registering the real account that should own the pre-existing data:

    python -m app.scripts.claim_legacy_library --email you@example.com [--dry-run]

It claims every row still at `user_id IS NULL` for that account. It is
idempotent: a second run (e.g. to confirm nothing was missed) finds zero
rows and does nothing. It never touches `media_item` or `series_progress`
directly — `series_progress` inherits ownership automatically through its
1:1 `library_entry_id` FK.

If `--email` is omitted, it looks for exactly one existing `user` row and
uses that (the common personal-project case); with zero or more than one,
it refuses and asks for an explicit `--email` rather than guessing.
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models.library import LibraryEntry
from app.models.user import User


def _resolve_user(db, email: str | None) -> User | None:
    if email:
        return db.scalar(select(User).where(User.email == email.strip().lower()))

    users = db.scalars(select(User)).all()
    if len(users) == 1:
        return users[0]
    if not users:
        print("No registered users found — register your account first "
              "(POST /auth/register), then re-run with --email.", file=sys.stderr)
    else:
        print(f"{len(users)} users exist — pass --email to pick one explicitly.",
              file=sys.stderr)
    return None


def claim(email: str | None = None, dry_run: bool = False) -> int:
    with SessionLocal() as db:
        user = _resolve_user(db, email)
        if user is None:
            return 0

        # LibraryEntry.media is lazy="joined", so `entry.media.title` below
        # doesn't trigger extra per-row queries.
        orphaned = list(
            db.scalars(select(LibraryEntry).where(LibraryEntry.user_id.is_(None)))
        )
        if not orphaned:
            print(f"Nothing to claim — no unowned library_entry rows found "
                  f"(target account: {user.email}).")
            return 0

        for entry in orphaned:
            print(f"{entry.media.title!r:50} ({entry.media.type.value}) -> {user.email}")
            if not dry_run:
                entry.user_id = user.id

        if not dry_run:
            db.commit()

        print(f"{'Would claim' if dry_run else 'Claimed'} {len(orphaned)} "
              f"row(s) for {user.email}.")
        return len(orphaned)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assign pre-Phase-8.2 library_entry rows (user_id IS NULL) "
                     "to a real registered account."
    )
    parser.add_argument("--email", default=None,
                         help="Email of the already-registered account to claim into. "
                              "Optional if exactly one user exists.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    claim(email=args.email, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
