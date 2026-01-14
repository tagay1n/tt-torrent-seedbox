from __future__ import annotations



from ttseed.config import load_config
from ttseed.db import connect, init_db, record_action, record_run, set_meta
from ttseed.http_client import build_session
from ttseed.logging_setup import setup_logging
from ttseed.porla_client import PorlaClient
from ttseed.scoring import compute_score, vulnerability_key
from ttseed.util import iso_now, load_pinned_list

ACTIVE_STATES = {"downloading", "queued", "stalled", "checking", "allocating"}


def _is_active(state: str) -> bool:
    lowered = (state or "").lower()
    return any(token in lowered for token in ACTIVE_STATES)


def _is_pinned(row, pinned: set[str]) -> bool:
    if not pinned:
        return False
    if row["topic_url"] in pinned:
        return True
    if row["infohash"] and row["infohash"] in pinned:
        return True
    if row["porla_torrent_id"] and row["porla_torrent_id"] in pinned:
        return True
    return False


def _build_keep_set(rows, pinned: set[str], max_torrents: int, max_total_bytes: int) -> tuple[set[int], int]:
    keep_ids: set[int] = set()
    total_bytes = 0
    count = 0

    for row in rows:
        if _is_pinned(row, pinned):
            keep_ids.add(row["id"])
            if row["size_bytes"]:
                total_bytes += int(row["size_bytes"])
            count += 1

    candidates = []
    for row in rows:
        if row["id"] in keep_ids:
            continue
        if row["size_bytes"] is None:
            continue
        candidates.append(row)

    candidates.sort(
        key=lambda r: vulnerability_key(
            r["seeders"],
            r["leechers"],
            r["discovered_at"],
            r["added_to_porla_at"],
            r["size_bytes"],
        )
    )

    for row in candidates:
        if count >= max_torrents:
            break
        size = int(row["size_bytes"] or 0)
        if total_bytes + size > max_total_bytes:
            continue
        keep_ids.add(row["id"])
        total_bytes += size
        count += 1

    return keep_ids, total_bytes


def run(config_path: str) -> None:
    logger = setup_logging()
    cfg = load_config(config_path)
    session = build_session(cfg.porla.retry_count)
    porla = PorlaClient(cfg.porla, session)

    conn = connect(cfg.storage.db_path)
    init_db(conn)

    pinned = load_pinned_list(cfg.policy.pinned_list_path)
    rows = conn.execute("SELECT * FROM torrents").fetchall()
    pinned_rows = [row for row in rows if _is_pinned(row, pinned)]
    pinned_bytes = sum(int(row["size_bytes"] or 0) for row in pinned_rows)
    pinned_count = len(pinned_rows)

    for row in rows:
        score = compute_score(
            row["seeders"],
            row["leechers"],
            row["discovered_at"],
            row["added_to_porla_at"],
            row["size_bytes"],
        )
        conn.execute("UPDATE torrents SET score = ? WHERE id = ?", (score, row["id"]))
    conn.commit()

    keep_ids, total_bytes = _build_keep_set(
        rows, pinned, cfg.policy.max_torrents, cfg.policy.max_total_bytes
    )

    started_at = iso_now()
    ok = True
    added = 0
    removed = 0
    skipped = 0

    if pinned_bytes > cfg.policy.max_total_bytes or pinned_count > cfg.policy.max_torrents:
        logger.warning("pinned set exceeds caps")
        record_action(conn, None, "warn", "pinned exceeds caps", iso_now())

    managed = porla.list_torrents(cfg.porla.managed_tag)
    managed_by_id = {t.id: t for t in managed}
    use_db_managed = porla.tag_mode != "porla" or not managed_by_id

    for row in rows:
        if row["id"] in keep_ids:
            if not row["porla_torrent_id"]:
                if not row["magnet_url"] and not row["torrent_url"]:
                    record_action(conn, row["id"], "skip", "missing magnet/torrent", iso_now())
                    skipped += 1
                    continue
                added_torrent = porla.add_torrent(
                    row["magnet_url"], row["torrent_url"], cfg.porla.managed_tag
                )
                if added_torrent:
                    conn.execute(
                        "UPDATE torrents SET porla_torrent_id = ?, porla_name = ?, added_to_porla_at = ?, status = ? WHERE id = ?",
                        (added_torrent.id, added_torrent.name, iso_now(), "queued", row["id"]),
                    )
                    conn.commit()
                    record_action(conn, row["id"], "add", "added to porla", iso_now())
                    added += 1
                else:
                    ok = False
                    record_action(conn, row["id"], "error", "porla add failed", iso_now())
            elif not use_db_managed and row["porla_torrent_id"] not in managed_by_id:
                added_torrent = porla.add_torrent(
                    row["magnet_url"], row["torrent_url"], cfg.porla.managed_tag
                )
                if added_torrent:
                    conn.execute(
                        "UPDATE torrents SET porla_torrent_id = ?, porla_name = ?, added_to_porla_at = ?, status = ? WHERE id = ?",
                        (added_torrent.id, added_torrent.name, iso_now(), "queued", row["id"]),
                    )
                    conn.commit()
                    record_action(conn, row["id"], "add", "re-added to porla", iso_now())
                    added += 1
                else:
                    ok = False
                    record_action(conn, row["id"], "error", "porla re-add failed", iso_now())
            elif use_db_managed:
                existing = porla.get_torrent(row["porla_torrent_id"])
                if not existing:
                    added_torrent = porla.add_torrent(
                        row["magnet_url"], row["torrent_url"], cfg.porla.managed_tag
                    )
                    if added_torrent:
                        conn.execute(
                            "UPDATE torrents SET porla_torrent_id = ?, porla_name = ?, added_to_porla_at = ?, status = ? WHERE id = ?",
                            (added_torrent.id, added_torrent.name, iso_now(), "queued", row["id"]),
                        )
                        conn.commit()
                        record_action(conn, row["id"], "add", "re-added to porla", iso_now())
                        added += 1
                    else:
                        ok = False
                        record_action(conn, row["id"], "error", "porla re-add failed", iso_now())

    if use_db_managed:
        managed_rows = [row for row in rows if row["porla_torrent_id"]]
        for row in managed_rows:
            if row["id"] in keep_ids:
                continue
            if cfg.policy.never_delete_if_pinned and _is_pinned(row, pinned):
                record_action(conn, row["id"], "skip", "pinned", iso_now())
                skipped += 1
                continue
            state = row["status"] or ""
            torrent = porla.get_torrent(row["porla_torrent_id"])
            if torrent:
                state = torrent.state or state
            if _is_active(state):
                record_action(conn, row["id"], "skip", "active download", iso_now())
                skipped += 1
                continue
            removed_ok = porla.remove_torrent(row["porla_torrent_id"], cfg.policy.allow_delete_data)
            if removed_ok:
                removed += 1
                record_action(conn, row["id"], "remove", "not in keep set", iso_now())
                conn.execute(
                    "UPDATE torrents SET status = ?, porla_torrent_id = NULL WHERE id = ?",
                    ("removed", row["id"]),
                )
                conn.commit()
            else:
                ok = False
                record_action(conn, row["id"], "error", "porla remove failed", iso_now())
    else:
        for torrent in managed:
            row = conn.execute(
                "SELECT * FROM torrents WHERE porla_torrent_id = ?",
                (torrent.id,),
            ).fetchone()
            if row and row["id"] in keep_ids:
                continue
            if row and cfg.policy.never_delete_if_pinned and _is_pinned(row, pinned):
                record_action(conn, row["id"], "skip", "pinned", iso_now())
                skipped += 1
                continue
            if _is_active(torrent.state):
                record_action(conn, row["id"] if row else None, "skip", "active download", iso_now())
                skipped += 1
                continue
            removed_ok = porla.remove_torrent(torrent.id, cfg.policy.allow_delete_data)
            if removed_ok:
                removed += 1
                record_action(conn, row["id"] if row else None, "remove", "not in keep set", iso_now())
                if row:
                    conn.execute(
                        "UPDATE torrents SET status = ?, porla_torrent_id = NULL WHERE id = ?",
                        ("removed", row["id"]),
                    )
                    conn.commit()
            else:
                ok = False
                record_action(conn, row["id"] if row else None, "error", "porla remove failed", iso_now())

    set_meta(conn, "last_reconcile_at", iso_now())
    summary = f"added={added} removed={removed} skipped={skipped} keep={len(keep_ids)} bytes={total_bytes}"
    logger.info("reconcile complete %s", summary)
    record_run(conn, "reconcile", started_at, iso_now(), ok, summary)
