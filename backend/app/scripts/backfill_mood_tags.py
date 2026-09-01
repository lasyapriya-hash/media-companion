"""Backfill mood_tags for media items added while the classifier was disabled.

Usage (from backend/, venv active, an LLM provider configured — GEMINI_API_KEY):
    python -m app.scripts.backfill_mood_tags [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import or_, select

from app.db import SessionLocal
from app.models.media import MediaItem
from app.services import mood_tags


def backfill(limit: int | None = None, dry_run: bool = False) -> int:
    if not mood_tags.is_enabled():
        print("No LLM provider configured (GEMINI_API_KEY) — nothing to do.", file=sys.stderr)
        return 0

    updated = 0
    with SessionLocal() as db:
        stmt = select(MediaItem).where(
            or_(MediaItem.mood_tags == [], MediaItem.mood_tags.is_(None))
        )
        if limit:
            stmt = stmt.limit(limit)

        for item in db.scalars(stmt):
            tags = mood_tags.classify_mood_tags(
                title=item.title,
                description=item.description,
                genres=list(item.genres or []),
                media_type=item.type.value,
            )
            if not tags:
                continue
            print(f"{item.title!r:50} -> {tags}")
            if not dry_run:
                item.mood_tags = tags
                updated += 1

        if not dry_run:
            db.commit()

    print(f"{'Would update' if dry_run else 'Updated'} {updated} item(s).")
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill media_item.mood_tags")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    backfill(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
