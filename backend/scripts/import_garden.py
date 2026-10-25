"""Import completed garden recording folders into TigerData.

The CSV/JSON files remain the source archive. A whole folder is committed or
rolled back together; garden_imports makes repeat runs idempotent.
"""

import argparse
import csv
import hashlib
import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

ACTIVITY = {
    "apples": "target_reach",
    "butterfly_left": "target_tracking",
    "butterfly_right": "target_tracking",
    "water": "bilateral_control",
}
SAMPLE_COLUMNS = (
    "time", "session_id", "seq", "t_ms", "lx", "ly", "rx", "ry", "connected",
    "activity", "trial_id", "target_lx", "target_ly", "target_rx", "target_ry",
    "cursor_lx", "cursor_ly", "cursor_rx", "cursor_ry",
)
CSV_REQUIRED = {"t_wall", "cursor_lx", "cursor_ly", "cursor_rx", "cursor_ry",
                "target_lx", "target_ly", "target_rx", "target_ry", "trial"}


def optional_number(value):
    if value is None or value == "":
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite CSV number: {value!r}")
    return number


def read_recording(folder, timezone):
    meta = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    if meta.get("game") != "garden" or meta.get("protocol") != "garden-v3":
        raise ValueError("Not a supported garden recording")
    started = datetime.fromisoformat(meta["started"])
    if started.tzinfo is None:
        started = started.replace(tzinfo=ZoneInfo(timezone))
    ended = datetime.fromisoformat(meta["ended"]) if meta.get("ended") else None
    if ended is not None and ended.tzinfo is None:
        ended = ended.replace(tzinfo=ZoneInfo(timezone))
    levels = []
    for item in meta.get("levels", []):
        level_folder = folder / item["folder"]
        level = json.loads((level_folder / "level.json").read_text(encoding="utf-8"))
        if level.get("level") not in ACTIVITY:
            raise ValueError(f"Unsupported level: {level.get('level')}")
        levels.append((level, level_folder / "controller_data.csv"))
    if not levels:
        raise ValueError("Recording has no completed or partial levels")
    return meta, started, ended, levels


def sample_rows(csv_path, started, session_id, level, offset_ms, first_seq):
    count = 0
    last_wall = 0.0
    with csv_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not CSV_REQUIRED.issubset(reader.fieldnames or []):
            raise ValueError(f"Missing garden CSV columns in {csv_path}")
        for row in reader:
            wall = optional_number(row["t_wall"])
            if wall is None or wall < last_wall:
                raise ValueError(f"Invalid or decreasing t_wall in {csv_path}")
            last_wall = wall
            t_ms = offset_ms + wall * 1000
            trial = int(row["trial"]) if row["trial"] else None
            if trial is not None and not 0 <= trial < 1000:
                raise ValueError(f"Invalid trial number in {csv_path}")
            axes = tuple(optional_number(row[name]) for name in
                         ("cursor_lx", "cursor_ly", "cursor_rx", "cursor_ry"))
            if any(axis is None or not -1.001 <= axis <= 1.001 for axis in axes):
                raise ValueError(f"Invalid normalized cursor in {csv_path}")
            yield (
                started + timedelta(milliseconds=t_ms), session_id, first_seq + count,
                t_ms, *axes, True, ACTIVITY[level["level"]],
                level["number"] * 1000 + trial if trial else None,
                *(optional_number(row[name]) for name in
                  ("target_lx", "target_ly", "target_rx", "target_ry",
                   "cursor_lx", "cursor_ly", "cursor_rx", "cursor_ry")),
            )
            count += 1


def import_one(conn, folder, source_group, timezone, participant_id=None):
    """Import one folder. With participant_id, the session belongs to that resident
    instead of an anonymous per-recording profile. Returns (status, rows, started, ended, session_id)."""
    source_hash = hashlib.sha256(str(folder.resolve()).encode("utf-8")).hexdigest()
    existing = conn.execute(
        """SELECT s.session_id, s.started_at, COALESCE(s.completed_at, s.started_at + INTERVAL '10 minutes') AS ended_at
           FROM garden_imports i JOIN sessions s ON s.session_id = i.session_id
           WHERE i.source_hash = %s""", (source_hash,)
    ).fetchone()
    if existing:
        return "skipped", 0, existing["started_at"], existing["ended_at"], existing["session_id"]
    meta, started, ended, levels = read_recording(folder, timezone)
    session_id = uuid4()
    alias = f"Garden recording {source_hash[:12]}"
    with conn.transaction():
        if participant_id is None:
            participant_id = conn.execute(
                """INSERT INTO participants (alias, dominant_hand) VALUES (%s, 'unknown')
                   ON CONFLICT (alias) DO UPDATE SET alias = EXCLUDED.alias
                   RETURNING participant_id""", (alias,)
            ).fetchone()["participant_id"]
        conn.execute(
            """INSERT INTO sessions
               (session_id, participant_id, mode, protocol_version, controller_id,
                connection, placement, status, quality, is_synthetic, started_at, completed_at)
               VALUES (%s, %s, 'free_play', %s, %s, %s, 'other', %s, NULL, %s, %s, %s)""",
            (session_id, participant_id, meta["protocol"], meta.get("controller"),
             "simulated" if meta.get("is_synthetic") else "usb",
             "completed" if meta.get("completed") else "abandoned",
             bool(meta.get("is_synthetic")), started, ended),
        )
        count = 0
        offset_ms = 0.0
        with conn.cursor() as cur:
            with cur.copy(
                f"COPY raw_samples ({', '.join(SAMPLE_COLUMNS)}) FROM STDIN"
            ) as copy:
                for level, csv_path in levels:
                    level_count = 0
                    last_wall = 0.0
                    for sample in sample_rows(csv_path, started, session_id, level, offset_ms, count):
                        copy.write_row(sample)
                        level_count += 1
                        last_wall = sample[3] - offset_ms
                    if level_count != level.get("rows"):
                        raise ValueError(f"CSV row count mismatch in {csv_path}: {level_count} != {level.get('rows')}")
                    count += level_count
                    # t_wall includes pauses within a level. The original files do
                    # not record the gaps between levels, so use a 1s display gap.
                    offset_ms += max(last_wall, float(level.get("duration_s", 0)) * 1000) + 1000
        for level, _ in levels:
            conn.execute(
                """INSERT INTO garden_level_results
                   (session_id, level_number, level_name, completed, sample_count,
                    duration_s, params, results)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (session_id, level["number"], level["level"], level["completed"],
                 level["rows"], level["duration_s"], Jsonb(level["params"]),
                 Jsonb(level["results"])),
            )
            conn.execute(
                """INSERT INTO session_events (event_id, session_id, t_ms, event_type, payload)
                   VALUES (%s, %s, %s, 'garden_level_imported', %s)""",
                (uuid4(), session_id, 0, Jsonb({"level": level["level"],
                                                "completed": level["completed"]})),
            )
        conn.execute(
            """INSERT INTO session_summaries (session_id, metrics, code_version)
               VALUES (%s, %s, 'garden-csv-import-v1')""",
            (session_id, Jsonb({"levels_completed": sum(bool(x[0]["completed"]) for x in levels),
                                "source": "garden_csv", "raw_sample_count": count})),
        )
        conn.execute(
            """INSERT INTO garden_imports (source_hash, session_id, source_group, sample_count)
               VALUES (%s, %s, %s, %s)""",
            (source_hash, session_id, source_group, count),
        )
    return "imported", count, started, started + timedelta(milliseconds=offset_ms), session_id


def folders_under(root):
    if (root / "session.json").is_file():
        return [root]
    return sorted(path.parent for path in root.rglob("session.json"))


def run(root, timezone, dry_run=False):
    folders = folders_under(root)
    print(f"Found {len(folders)} garden recording folders in {root}")
    if dry_run:
        for folder in folders:
            meta, _, _, levels = read_recording(folder, timezone)
            print(f"  {folder}: {sum(level['rows'] for level, _ in levels)} samples, "
                  f"{len(levels)} levels, completed={bool(meta.get('completed'))}")
        return
    from app.db import DATABASE_URL

    earliest = latest = None
    imported = skipped = failed = 0
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True) as conn:
        schema_ready = conn.execute(
            "SELECT to_regclass('garden_imports') AS imports, "
            "to_regclass('garden_sample_seconds') AS timeline"
        ).fetchone()
        if not all(schema_ready.values()):
            raise RuntimeError("Apply backend/sql/schema.sql to TigerData before importing recordings")
        for folder in folders:
            try:
                group = str(folder.parent.relative_to(root)) if folder != root else None
                status, count, start, end, _ = import_one(conn, folder, group, timezone)
                if status == "imported":
                    imported += 1
                else:
                    skipped += 1
                earliest = start if earliest is None else min(earliest, start)
                latest = end if latest is None else max(latest, end)
                print(f"{status}: {folder} ({count} samples)")
            except (OSError, ValueError, KeyError, psycopg.Error) as exc:
                failed += 1
                print(f"FAILED: {folder}: {exc}")
        if earliest is not None:
            # The policy only refreshes recent data. Backfill historic buckets now.
            start = earliest.replace(microsecond=0) - timedelta(seconds=1)
            end = latest.replace(microsecond=0) + timedelta(seconds=2)
            conn.execute("CALL refresh_continuous_aggregate('garden_sample_seconds', %s, %s)",
                         (start, end))
    print(f"Finished: {imported} imported, {skipped} already imported, {failed} failed")
    if failed:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description="Import garden CSV/JSON recordings into TigerData")
    parser.add_argument("path", type=Path, help="a recording folder or a data root")
    parser.add_argument("--timezone", default=os.environ.get("GARDEN_RECORDING_TIMEZONE", "America/Toronto"),
                        help="timezone used by naive session.json timestamps")
    parser.add_argument("--dry-run", action="store_true", help="inspect folders without connecting to TigerData")
    args = parser.parse_args()
    if not args.path.exists():
        parser.error(f"path does not exist: {args.path}")
    run(args.path.resolve(), args.timezone, args.dry_run)


if __name__ == "__main__":
    main()
