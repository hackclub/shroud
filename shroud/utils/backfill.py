from typing import Any

from shroud.utils import db


def backfill() -> None:
    table = db._get_airtable()
    if table is None:
        raise RuntimeError("Airtable is not configured; nothing to backfill from.")

    total = 0
    upserted = 0
    for page in table.iterate():
        for rec in page:
            total += 1
            f: dict[str, Any] = rec.get("fields", {})
            if not f.get("dm_ts") or not f.get("dm_channel"):
                print(f"SKIP {rec['id']}: missing dm_ts/dm_channel")
                continue
            db._execute(
                """
                INSERT INTO reports
                    (dm_ts, dm_channel, forwarded_ts, selection_ts, selection,
                     content, reply_time, resolve_time, merged, legacy_airtable_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (dm_ts) DO UPDATE SET
                    dm_channel   = EXCLUDED.dm_channel,
                    forwarded_ts = COALESCE(EXCLUDED.forwarded_ts, reports.forwarded_ts),
                    selection_ts = COALESCE(EXCLUDED.selection_ts, reports.selection_ts),
                    selection    = COALESCE(EXCLUDED.selection, reports.selection),
                    content      = COALESCE(EXCLUDED.content, reports.content),
                    reply_time   = COALESCE(EXCLUDED.reply_time, reports.reply_time),
                    resolve_time = COALESCE(EXCLUDED.resolve_time, reports.resolve_time),
                    merged       = EXCLUDED.merged,
                    legacy_airtable_id = EXCLUDED.legacy_airtable_id,
                    updated_at   = now()
                """,
                (
                    f.get("dm_ts"),
                    f.get("dm_channel"),
                    f.get("forwarded_ts"),
                    f.get("selection_ts"),
                    f.get("selection"),
                    f.get("content"),
                    f.get("reply_time"),
                    f.get("resolve_time"),
                    bool(f.get("merged", False)),
                    rec["id"],
                ),
            )
            upserted += 1

    print(f"Backfill complete: {upserted}/{total} Airtable records upserted into Postgres.")


if __name__ == "__main__":
    backfill()
