#!/usr/bin/env python3
"""Change one Tekken Tag Tournament 2 character-rank byte in a TDT file.

The TTT2 rank table begins at offset 0x70.  It has 59 entries, each 0x30
bytes long, and the first byte of each entry is that character's rank ID.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path


RANK_TABLE_OFFSET = 0x70
CHARACTER_RECORD_SIZE = 0x30
CHARACTER_COUNT = 59


def rank_offset(character_id: int) -> int:
    """Return the rank byte offset for a zero-based TTT2 character ID."""
    return RANK_TABLE_OFFSET + character_id * CHARACTER_RECORD_SIZE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Edit one TTT2 character rank in a .tdt file.",
    )
    parser.add_argument("tdt_file", type=Path, help="path to the .tdt file")
    parser.add_argument(
        "--character-id",
        required=True,
        type=int,
        help=f"zero-based character ID (0-{CHARACTER_COUNT - 1})",
    )
    parser.add_argument(
        "--rank-id",
        required=True,
        type=int,
        help="rank byte to write (0-255)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show the pending change without writing a file",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="do not create a .bak backup (not recommended)",
    )
    parser.add_argument(
        "--force-backup",
        action="store_true",
        help="replace an existing .bak backup",
    )
    return parser.parse_args()


def write_atomically(path: Path, content: bytes) -> None:
    """Replace path only after the complete replacement file is written."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    args = parse_args()
    path = args.tdt_file

    if not path.is_file():
        print(f"error: TDT file not found: {path}", file=sys.stderr)
        return 2
    if not 0 <= args.character_id < CHARACTER_COUNT:
        print(
            f"error: --character-id must be between 0 and {CHARACTER_COUNT - 1}",
            file=sys.stderr,
        )
        return 2
    if not 0 <= args.rank_id <= 0xFF:
        print("error: --rank-id must be between 0 and 255", file=sys.stderr)
        return 2

    content = bytearray(path.read_bytes())
    offset = rank_offset(args.character_id)
    if len(content) <= offset:
        print(
            f"error: file is {len(content)} bytes; rank offset 0x{offset:X} is outside it",
            file=sys.stderr,
        )
        return 2

    old_rank_id = content[offset]
    print(f"file: {path}")
    print(f"character ID: {args.character_id}")
    print(f"rank offset: 0x{offset:X}")
    print(f"rank ID: {old_rank_id} -> {args.rank_id}")

    if args.dry_run:
        print("dry run: file was not changed")
        return 0

    backup_path = Path(f"{path}.bak")
    if not args.no_backup:
        if backup_path.exists() and not args.force_backup:
            print(
                f"error: backup already exists: {backup_path}\n"
                "Use --force-backup to replace it, or --no-backup to skip backup creation.",
                file=sys.stderr,
            )
            return 2
        shutil.copy2(path, backup_path)
        print(f"backup: {backup_path}")

    content[offset] = args.rank_id
    write_atomically(path, content)
    print("updated successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
