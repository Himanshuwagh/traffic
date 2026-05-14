"""
fetch_india_districts.py
------------------------
Batch script that fetches OSMnx road segments for all ~766 Indian districts
(sourced from india_districts.py) and writes them into the road_segments table.

Progress tracking:
    Every district's status (running | success | failed | skipped), segment
    count, duration, and ETA are written to the `district_progress` table in
    real time — immediately after each district finishes.  You can query it
    from any Postgres client while the job is running:

        SELECT state, district, status, segments_fetched, duration_seconds
        FROM   district_progress
        ORDER  BY started_at;

State filtering (horizontal scale-out):
    Set the STATE_FILTER env var to a comma-separated list of state names to
    limit which states this instance will process.  For example:
/ 
        STATE_FILTER="A" python fetch_india_districts.py

    Run multiple Railway deploys in parallel, each with a different
    STATE_FILTER, to process all 766 districts concurrently across deploys.

Resume / crash safety:
    On startup the script queries district_progress for rows with
    status='success' and skips those districts.  If Railway kills the
    container mid-run, simply redeploy — only unfinished districts will run.

Pacing:
    After each district (except the last) the script sleeps WAIT_MINUTES
    (default 2, overridable via env var) so OSM/Overpass APIs are not hammered.
    A countdown is logged every minute so Railway logs stay alive.

Usage:
    python fetch_india_districts.py
    WAIT_MINUTES=5 STATE_FILTER="Kerala,Goa" python fetch_india_districts.py
"""

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from statistics import mean

# ---------------------------------------------------------------------------
# Logging — configure before any library import so all loggers inherit format
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Local imports (support both `python fetch_india_districts.py` and package mode)
# ---------------------------------------------------------------------------
try:
    from .fetch_district import fetch_segments_for_district
    from .india_districts import INDIA_DISTRICTS
    from .database import SessionLocal, engine
except ImportError:
    from fetch_district import fetch_segments_for_district  # type: ignore[no-redef]
    from india_districts import INDIA_DISTRICTS             # type: ignore[no-redef]
    from database import SessionLocal, engine               # type: ignore[no-redef]

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WAIT_MINUTES: int = int(os.getenv("WAIT_MINUTES", "2"))
MAX_DISTRICTS_PER_RUN: int = max(0, int(os.getenv("MAX_DISTRICTS_PER_RUN", "0")))
SHARD_INDEX: int = int(os.getenv("SHARD_INDEX", "0"))
SHARD_COUNT: int = max(1, int(os.getenv("SHARD_COUNT", "1")))

# Comma-separated state names, e.g. "Maharashtra,Karnataka"
# If empty / unset, ALL states are processed.
_state_filter_raw: str = os.getenv("STATE_FILTER", "").strip()
STATE_FILTER: list[str] = (
    [s.strip() for s in _state_filter_raw.split(",") if s.strip()]
    if _state_filter_raw
    else []
)
_district_filter_raw: str = os.getenv("DISTRICT_FILTER", "").strip()
DISTRICT_FILTER: list[str] = (
    [s.strip() for s in _district_filter_raw.split(",") if s.strip()]
    if _district_filter_raw
    else []
)

LINE = "=" * 68
THIN = "-" * 68


def _norm_label(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _parse_filter_set(values: list[str]) -> set[str]:
    return {_norm_label(v) for v in values if v.strip()}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_duration(seconds: float) -> str:
    """Turn a raw seconds value into a human-readable string."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}m"


def _fmt_eta(seconds: float) -> str:
    """Format a remaining-seconds value as a human-readable ETA string."""
    if seconds <= 0:
        return "finishing soon"
    return _fmt_duration(seconds)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _ensure_district_progress_table() -> None:
    """Create district_progress (and its index) if they don't already exist."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS district_progress (
                id               SERIAL PRIMARY KEY,
                run_id           TEXT,
                state            TEXT        NOT NULL,
                district         TEXT        NOT NULL,
                status           TEXT        NOT NULL,
                segments_fetched INTEGER,
                started_at       TIMESTAMP,
                finished_at      TIMESTAMP,
                duration_seconds INTEGER,
                error_message    TEXT
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_dp_state_district "
            "ON district_progress (state, district)"
        ))
    log.info("district_progress table ready.")


def _record_district_progress(
    run_id: str,
    state: str,
    district: str,
    status: str,
    segments: int | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    duration: int | None = None,
    error: str | None = None,
) -> None:
    """
    Upsert a progress row for (run_id, state, district).

    Tries UPDATE first; if no row exists yet it falls back to INSERT.
    Never raises — logs a warning on any DB error so the main loop continues.
    """
    db = SessionLocal()
    try:
        updated = db.execute(text("""
            UPDATE district_progress
            SET    status           = :status,
                   segments_fetched = COALESCE(:segments,     segments_fetched),
                   finished_at      = COALESCE(:finished_at,  finished_at),
                   duration_seconds = COALESCE(:duration,     duration_seconds),
                   error_message    = COALESCE(:error,        error_message)
            WHERE  run_id = :run_id
              AND  state  = :state
              AND  district = :district
        """), dict(
            run_id=run_id, state=state, district=district, status=status,
            segments=segments, finished_at=finished_at,
            duration=duration, error=error,
        ))

        if updated.rowcount == 0:
            db.execute(text("""
                INSERT INTO district_progress
                    (run_id, state, district, status, segments_fetched,
                     started_at, finished_at, duration_seconds, error_message)
                VALUES
                    (:run_id, :state, :district, :status, :segments,
                     :started_at, :finished_at, :duration, :error)
            """), dict(
                run_id=run_id, state=state, district=district, status=status,
                segments=segments, started_at=started_at,
                finished_at=finished_at, duration=duration, error=error,
            ))

        db.commit()
    except Exception as exc:
        db.rollback()
        log.warning("Could not write to district_progress: %s", exc)
    finally:
        db.close()


def _get_successful_districts() -> set[tuple[str, str]]:
    """
    Return a set of (state_lower, district_lower) pairs that are already
    marked status='success' in district_progress (from any previous run).
    """
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT DISTINCT state, district
            FROM district_progress
            WHERE status = 'success'
        """)).fetchall()
        return {(row[0].lower(), row[1].lower()) for row in rows if row[0] and row[1]}
    except Exception as exc:
        log.warning("Could not query district_progress (table may be new): %s", exc)
        return set()
    finally:
        db.close()


def _get_district_segment_count(short_district: str) -> int:
    """Return the number of road_segments rows stored for this district."""
    db = SessionLocal()
    try:
        return db.execute(
            text("SELECT COUNT(*) FROM road_segments WHERE city = :city"),
            {"city": short_district},
        ).scalar() or 0
    except Exception:
        return 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Cooldown countdown
# ---------------------------------------------------------------------------

def _countdown_wait(
    minutes: int,
    next_label: str,
    total_elapsed: float,
    done: int,
    total: int,
    eta_remaining: float,
) -> None:
    """Sleep for `minutes` minutes, logging a countdown every 60 s."""
    pct = 100 * done / total
    log.info(
        "⏳  Cooldown %dm  →  next: %s  |  "
        "%d/%d districts done (%.0f%%)  |  "
        "run elapsed: %s  |  job ETA: ~%s",
        minutes, next_label,
        done, total, pct,
        _fmt_duration(total_elapsed),
        _fmt_eta(eta_remaining),
    )
    for remaining_m in range(minutes - 1, 0, -1):
        time.sleep(60)
        log.info("   ⏱  %dm left in cooldown…", remaining_m)
    time.sleep(60)
    log.info("▶  Cooldown done.\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:  # noqa: C901 — complexity is inherent in a batch runner
    run_id       = uuid.uuid4().hex[:8]          # short human-readable id
    script_start = time.monotonic()
    wall_start   = datetime.now(timezone.utc)

    # ── Banner ────────────────────────────────────────────────────────────────
    log.info(LINE)
    log.info("  🇮🇳  FETCH INDIA DISTRICTS — Road Segment Batch Processor")
    log.info(THIN)
    log.info("  Run ID       : %s", run_id)
    log.info("  Started      : %s", wall_start.strftime("%Y-%m-%d %H:%M:%S UTC"))
    log.info(
        "  Cooldown     : %d min between districts  "
        "(set WAIT_MINUTES env var to override)",
        WAIT_MINUTES,
    )
    if SHARD_COUNT > 1:
        log.info("  Shard        : %d / %d", SHARD_INDEX + 1, SHARD_COUNT)
    if MAX_DISTRICTS_PER_RUN > 0:
        log.info("  Max districts: %d", MAX_DISTRICTS_PER_RUN)
    if STATE_FILTER:
        log.info("  STATE_FILTER : %s", ", ".join(STATE_FILTER))
    else:
        log.info("  STATE_FILTER : (all states)")
    if DISTRICT_FILTER:
        log.info("  DISTRICT_FILTER : %s", ", ".join(DISTRICT_FILTER))
    log.info(LINE)

    # ── Ensure progress table exists ─────────────────────────────────────────
    _ensure_district_progress_table()

    # ── Build the filtered working set ───────────────────────────────────────
    if SHARD_INDEX < 0 or SHARD_INDEX >= SHARD_COUNT:
        raise ValueError(f"SHARD_INDEX must be between 0 and {SHARD_COUNT - 1}, got {SHARD_INDEX}")

    state_filter_set = _parse_filter_set(STATE_FILTER) if STATE_FILTER else set()
    district_filter_set = _parse_filter_set(DISTRICT_FILTER) if DISTRICT_FILTER else set()

    all_pairs: list[tuple[str, str]] = []   # (state, district)
    for state, districts in INDIA_DISTRICTS.items():
        if state_filter_set and _norm_label(state) not in state_filter_set:
            continue
        for district in districts:
            if district_filter_set and _norm_label(district) not in district_filter_set:
                continue
            all_pairs.append((state, district))

    if SHARD_COUNT > 1:
        all_pairs = [pair for idx, pair in enumerate(all_pairs) if idx % SHARD_COUNT == SHARD_INDEX]

    if MAX_DISTRICTS_PER_RUN > 0:
        all_pairs = all_pairs[:MAX_DISTRICTS_PER_RUN]

    total_districts = len(all_pairs)

    log.info("  Districts in scope : %d", total_districts)
    if state_filter_set:
        log.info(
            "  States in scope    : %s  (%d total)",
            ", ".join(sorted({state for state, _ in all_pairs})),
            len({state for state, _ in all_pairs}),
        )
    if district_filter_set:
        log.info("  District filter count: %d", len(district_filter_set))
    log.info(LINE)

    if total_districts == 0:
        log.warning(
            "No districts matched the current filters. "
            "Check spelling — example states: %s",
            list(INDIA_DISTRICTS.keys())[:5],
        )
        return

    # ── Load already-successful districts ────────────────────────────────────
    done_set = _get_successful_districts()  # {(state_lower, district_lower)}

    already_done: list[tuple[str, str]] = [
        (s, d) for s, d in all_pairs
        if (s.lower(), d.lower()) in done_set
    ]
    remaining: list[tuple[str, str]] = [
        (s, d) for s, d in all_pairs
        if (s.lower(), d.lower()) not in done_set
    ]

    log.info("  Already successful : %d", len(already_done))
    log.info("  To process now     : %d", len(remaining))
    log.info(LINE)

    # Record already-done districts for this run (as 'skipped')
    for state, district in already_done:
        short = district.strip().lower()
        seg_count = _get_district_segment_count(short)
        _record_district_progress(run_id, state, district, "skipped", segments=seg_count)
        log.info(
            "  ⏭   Skipping %-28s  (%s, %d segs in DB)",
            district, state, seg_count,
        )

    if not remaining:
        log.info("✅  All districts already processed. Nothing to do.")
        return

    if already_done:
        log.info("")  # blank separator after the skip block

    # ── Process remaining districts ───────────────────────────────────────────
    succeeded:      list[tuple[str, str, int]] = []   # (state, district, seg_count)
    failed:         list[tuple[str, str]]      = []   # (state, district)
    district_times: list[float]                = []   # fetch durations for ETA

    n            = len(remaining)
    last_state   = ""                                  # tracks state changes for header

    for idx, (state, district) in enumerate(remaining, start=1):
        short         = district.strip().lower()
        district_start = time.monotonic()
        wall_now       = datetime.now(timezone.utc)

        # ── State-level separator (logged once per new state) ─────────────────
        if state != last_state:
            log.info("")
            log.info("━" * 68)
            log.info("  📍  STATE: %s", state)
            log.info("━" * 68)
            last_state = state

        # ── ETA estimate ──────────────────────────────────────────────────────
        if district_times:
            avg_fetch = mean(district_times)
            left      = n - idx           # districts after this one
            eta_secs  = left * (avg_fetch + WAIT_MINUTES * 60)
            eta_str   = f"~{_fmt_eta(eta_secs)}"
        else:
            eta_secs = 0.0
            eta_str  = "calculating…"

        pct = 100 * (idx - 1) / n

        log.info("┌%s", "─" * 66)
        log.info(
            "│  [%d/%d]  (%.0f%%)  🏘  %s,  %s",
            idx, n, pct, district, state,
        )
        log.info(
            "│  Started : %s   ETA to finish all: %s   Run elapsed: %s",
            wall_now.strftime("%H:%M:%S UTC"),
            eta_str,
            _fmt_duration(time.monotonic() - script_start),
        )
        log.info("│")

        # Write "running" row immediately so a crash mid-fetch is visible
        _record_district_progress(
            run_id, state, district, "running", started_at=wall_now,
        )

        # ── Fetch ─────────────────────────────────────────────────────────────
        success: bool
        error_msg: str | None = None
        try:
            result  = fetch_segments_for_district(district, state)
            success = result is not False
        except Exception as exc:
            log.error("│  ❌  Unexpected exception for %s: %s", district, exc, exc_info=True)
            success   = False
            error_msg = str(exc)

        district_elapsed = time.monotonic() - district_start
        total_elapsed    = time.monotonic() - script_start
        district_times.append(district_elapsed)

        # ── Record result ─────────────────────────────────────────────────────
        if success:
            seg_count = _get_district_segment_count(short)
            succeeded.append((state, district, seg_count))
            _record_district_progress(
                run_id, state, district, "success",
                segments=seg_count,
                finished_at=datetime.now(timezone.utc),
                duration=int(district_elapsed),
            )
            log.info("│  ✅  Success")
            log.info("│  Segments inserted   : %d", seg_count)
            log.info("│  District fetch time : %s", _fmt_duration(district_elapsed))
        else:
            failed.append((state, district))
            _record_district_progress(
                run_id, state, district, "failed",
                finished_at=datetime.now(timezone.utc),
                duration=int(district_elapsed),
                error=error_msg or "fetch_segments_for_district returned False",
            )
            log.warning("│  ❌  Failed — will appear in final summary")
            log.warning("│  District fetch time : %s", _fmt_duration(district_elapsed))

        # ── Running tally ─────────────────────────────────────────────────────
        total_segs_so_far = sum(s for _, _, s in succeeded)
        log.info("│")
        log.info(
            "│  📊 Tally  ✅ %d ok  ❌ %d failed  "
            "| %d/%d processed  | %d segs total  | run: %s",
            len(succeeded), len(failed),
            len(succeeded) + len(failed), n,
            total_segs_so_far,
            _fmt_duration(total_elapsed),
        )
        log.info("└%s", "─" * 66)

        # ── Cooldown before next district ─────────────────────────────────────
        if idx < n:
            avg_fetch = mean(district_times)
            left      = n - idx
            eta_secs  = left * (avg_fetch + WAIT_MINUTES * 60)
            log.info("")
            _countdown_wait(
                WAIT_MINUTES,
                next_label=f"{remaining[idx][1]}, {remaining[idx][0]}",
                total_elapsed=time.monotonic() - script_start,
                done=idx,
                total=n,
                eta_remaining=eta_secs,
            )

    # ── Final summary ─────────────────────────────────────────────────────────
    total_time = time.monotonic() - script_start
    total_segs = sum(s for _, _, s in succeeded)
    wall_end   = datetime.now(timezone.utc)

    log.info("")
    log.info(LINE)
    log.info("  📊  BATCH COMPLETE  —  run: %s", run_id)
    log.info(THIN)
    log.info(
        "  ✅  Success  : %3d districts  |  %d segments inserted",
        len(succeeded), total_segs,
    )
    log.info(
        "  ⏭   Skipped  : %3d districts  (were already in DB)",
        len(already_done),
    )
    log.info("  ❌  Failed   : %3d districts", len(failed))
    log.info(THIN)
    log.info("  ⏱   Total duration : %s", _fmt_duration(total_time))
    log.info("  📅  Started        : %s", wall_start.strftime("%Y-%m-%d %H:%M UTC"))
    log.info("  📅  Finished       : %s", wall_end.strftime("%Y-%m-%d %H:%M UTC"))
    log.info(LINE)

    # Per-district results table
    if succeeded or failed:
        log.info("")
        log.info("  Per-district results:")
        log.info("  %-30s %-24s %10s  %10s  Status", "District", "State", "Segments", "Duration")
        log.info("  %s", THIN)

        for st, dist, segs in succeeded:
            short = dist.strip().lower()
            db = SessionLocal()
            try:
                row = db.execute(
                    text(
                        "SELECT duration_seconds FROM district_progress "
                        "WHERE run_id=:r AND state=:s AND district=:d LIMIT 1"
                    ),
                    {"r": run_id, "s": st, "d": dist},
                ).fetchone()
                dur_str = _fmt_duration(row[0]) if row and row[0] else "—"
            except Exception:
                dur_str = "—"
            finally:
                db.close()
            log.info(
                "  %-30s %-24s %10d  %10s  ✅",
                dist[:30], st[:24], segs, dur_str,
            )

        for st, dist in failed:
            log.info("  %-30s %-24s %10s  %10s  ❌", dist[:30], st[:24], "—", "—")

    log.info(LINE)

    if failed:
        log.info(
            "  ⚠️   Failed districts: %s",
            [(d, s) for s, d in failed],
        )
        log.info(
            "  Tip: redeploy to retry — resume logic will skip already-done districts.",
        )
        log.info(LINE)


if __name__ == "__main__":
    main()
