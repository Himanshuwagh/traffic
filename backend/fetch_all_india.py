"""
fetch_all_india.py
------------------
Batch script that fetches OSMnx road segments for ~50 major Indian cities and
writes them into the road_segments table.

Progress tracking:
    Every city's status (skipped | running | success | failed), segment count,
    duration, and ETA are written to the `fetch_progress` table in real time.
    You can query it from any Postgres client while the job is running:

        SELECT city, status, segments_fetched, duration_seconds, started_at
        FROM   fetch_progress
        ORDER  BY started_at;

Resume logic:
    On startup the script queries road_segments for cities that already have
    rows and skips them.  If Railway kills the container mid-run, just redeploy
    and the script picks up exactly where it stopped.

Pacing:
    After each city (except the last) the script waits WAIT_MINUTES (default
    30, overridable via env var) so the Overpass/OSMnx API is not hammered.
    A countdown is logged every minute so Railway logs stay alive.

Usage:
    WAIT_MINUTES=10 python fetch_all_india.py
"""

import logging
import os
import time
import uuid
from datetime import datetime, timezone

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
# Local imports (support both `python fetch_all_india.py` and package mode)
# ---------------------------------------------------------------------------
try:
    from .fetch_segments import fetch_segments_for_city
    from .database import SessionLocal, engine
except ImportError:
    from fetch_segments import fetch_segments_for_city  # type: ignore[no-redef]
    from database import SessionLocal, engine            # type: ignore[no-redef]

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WAIT_MINUTES: int = int(os.getenv("WAIT_MINUTES", "30"))
LINE = "=" * 68
THIN = "-" * 68

# ---------------------------------------------------------------------------
# City list — 16 Tier-1 metros + 34 Tier-2 cities  (50 total)
# ---------------------------------------------------------------------------
ALL_INDIA_CITIES: list[str] = [
    # ── Tier-1 metros ────────────────────────────────────────────────────────
    "Mumbai, India",
    "Delhi, India",
    "Bangalore, India",
    "Hyderabad, India",
    "Ahmedabad, India",
    "Chennai, India",
    "Kolkata, India",
    "Surat, India",
    "Pune, India",
    "Jaipur, India",
    "Lucknow, India",
    "Kanpur, India",
    "Nagpur, India",
    "Indore, India",
    "Thane, India",
    "Bhopal, India",
    # ── Tier-2 cities ────────────────────────────────────────────────────────
    "Visakhapatnam, India",
    "Patna, India",
    "Vadodara, India",
    "Ghaziabad, India",
    "Ludhiana, India",
    "Agra, India",
    "Nashik, India",
    "Faridabad, India",
    "Meerut, India",
    "Rajkot, India",
    "Varanasi, India",
    "Srinagar, India",
    "Aurangabad, India",
    "Dhanbad, India",
    "Amritsar, India",
    "Prayagraj, India",
    "Ranchi, India",
    "Howrah, India",
    "Coimbatore, India",
    "Jabalpur, India",
    "Gwalior, India",
    "Vijayawada, India",
    "Jodhpur, India",
    "Madurai, India",
    "Raipur, India",
    "Kota, India",
    "Chandigarh, India",
    "Guwahati, India",
    "Solapur, India",
    "Hubli, India",
    "Mysore, India",
    "Tiruchirappalli, India",
    "Bareilly, India",
    "Aligarh, India",
    "Moradabad, India",
]

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _short_name(city_query: str) -> str:
    """Lowercased first component — must match what fetch_segments stores."""
    return city_query.split(",")[0].strip().lower()


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
    if seconds <= 0:
        return "finishing soon"
    return _fmt_duration(seconds)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _ensure_progress_table() -> None:
    """Create fetch_progress if it doesn't already exist."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fetch_progress (
                id               SERIAL PRIMARY KEY,
                run_id           TEXT,
                city             TEXT        NOT NULL,
                status           TEXT        NOT NULL,
                segments_fetched INTEGER,
                started_at       TIMESTAMP,
                finished_at      TIMESTAMP,
                duration_seconds INTEGER,
                error_message    TEXT
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_fp_run_city "
            "ON fetch_progress (run_id, city)"
        ))
    log.info("fetch_progress table ready.")


def _record_progress(
    run_id: str,
    city: str,
    status: str,
    segments: int | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    duration: int | None = None,
    error: str | None = None,
) -> None:
    """Upsert a progress row for (run_id, city). Never raises — logs warning on error."""
    db = SessionLocal()
    try:
        updated = db.execute(text("""
            UPDATE fetch_progress
            SET    status           = :status,
                   segments_fetched = COALESCE(:segments,    segments_fetched),
                   finished_at      = COALESCE(:finished_at, finished_at),
                   duration_seconds = COALESCE(:duration,    duration_seconds),
                   error_message    = COALESCE(:error,       error_message)
            WHERE  run_id = :run_id AND city = :city
        """), dict(run_id=run_id, city=city, status=status, segments=segments,
                   finished_at=finished_at, duration=duration, error=error))

        if updated.rowcount == 0:
            db.execute(text("""
                INSERT INTO fetch_progress
                    (run_id, city, status, segments_fetched,
                     started_at, finished_at, duration_seconds, error_message)
                VALUES
                    (:run_id, :city, :status, :segments,
                     :started_at, :finished_at, :duration, :error)
            """), dict(run_id=run_id, city=city, status=status, segments=segments,
                       started_at=started_at, finished_at=finished_at,
                       duration=duration, error=error))
        db.commit()
    except Exception as exc:
        db.rollback()
        log.warning(f"Could not write to fetch_progress: {exc}")
    finally:
        db.close()


def _get_processed_cities() -> set[str]:
    """Return set of city short-names already present in road_segments."""
    db = SessionLocal()
    try:
        rows = db.execute(text("SELECT DISTINCT city FROM road_segments")).fetchall()
        return {row[0].lower() for row in rows if row[0]}
    except Exception as exc:
        log.warning(f"Could not query road_segments (DB may be empty): {exc}")
        return set()
    finally:
        db.close()


def _get_city_segment_count(city_short: str) -> int:
    """Count rows in road_segments for a given city."""
    db = SessionLocal()
    try:
        return db.execute(
            text("SELECT COUNT(*) FROM road_segments WHERE city = :city"),
            {"city": city_short},
        ).scalar() or 0
    except Exception:
        return 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Countdown wait
# ---------------------------------------------------------------------------

def _countdown_wait(
    minutes: int,
    next_city: str,
    total_elapsed: float,
    cities_done: int,
    cities_total: int,
    eta_remaining: float,
) -> None:
    pct = 100 * cities_done / cities_total
    log.info(
        f"⏳  Cooldown {minutes}m  →  next: {next_city}  |  "
        f"{cities_done}/{cities_total} cities done ({pct:.0f}%)  |  "
        f"run elapsed: {_fmt_duration(total_elapsed)}  |  "
        f"job ETA: ~{_fmt_eta(eta_remaining)}"
    )
    for remaining_m in range(minutes - 1, 0, -1):
        time.sleep(60)
        log.info(f"   ⏱  {remaining_m}m left in cooldown…")
    time.sleep(60)
    log.info("▶  Cooldown done.\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    run_id       = uuid.uuid4().hex[:8]          # e.g. "a3f9c21b"
    script_start = time.monotonic()
    wall_start   = datetime.now(timezone.utc)

    log.info(LINE)
    log.info("  🇮🇳  FETCH ALL INDIA — Road Segment Batch Processor")
    log.info(THIN)
    log.info(f"  Run ID   : {run_id}")
    log.info(f"  Started  : {wall_start.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    log.info(f"  Cooldown : {WAIT_MINUTES} min between cities  "
             f"(set WAIT_MINUTES env var to override)")
    log.info(LINE)

    # ── Ensure progress table exists ─────────────────────────────────────────
    _ensure_progress_table()

    # ── Determine what still needs processing ────────────────────────────────
    processed_set = _get_processed_cities()
    already_done  = [c for c in ALL_INDIA_CITIES if _short_name(c) in processed_set]
    remaining     = [c for c in ALL_INDIA_CITIES if _short_name(c) not in processed_set]

    log.info(f"  Total cities    : {len(ALL_INDIA_CITIES)}")
    log.info(f"  Already in DB   : {len(already_done)}")
    log.info(f"  To process now  : {len(remaining)}")
    log.info(LINE)

    # Record already-done cities in the progress table for this run
    for city in already_done:
        seg_count = _get_city_segment_count(_short_name(city))
        _record_progress(run_id, _short_name(city), "skipped", segments=seg_count)
        log.info(f"  ⏭   Skipping {_short_name(city):<25} "
                 f"(already has {seg_count:,} segments in DB)")

    if not remaining:
        log.info("✅  All cities already processed. Nothing to do.")
        return

    if already_done:
        log.info("")  # blank line after skip block

    # ── Process cities ───────────────────────────────────────────────────────
    succeeded:  list[tuple[str, int]] = []   # (city_query, segment_count)
    failed:     list[str]             = []
    city_times: list[float]           = []   # fetch durations for ETA
    n = len(remaining)

    for idx, city in enumerate(remaining, start=1):
        short      = _short_name(city)
        city_start = time.monotonic()
        wall_now   = datetime.now(timezone.utc)

        # ── ETA estimate ─────────────────────────────────────────────────────
        if city_times:
            avg_fetch  = sum(city_times) / len(city_times)
            left       = n - idx          # cities after this one
            eta_secs   = left * avg_fetch + left * WAIT_MINUTES * 60
            eta_str    = f"~{_fmt_eta(eta_secs)}"
        else:
            eta_secs = 0.0
            eta_str  = "calculating…"

        pct = 100 * (idx - 1) / n

        log.info(f"┌{'─' * 66}")
        log.info(f"│  [{idx}/{n}]  ({pct:.0f}%)  🏙  {city}")
        log.info(f"│  Started : {wall_now.strftime('%H:%M:%S UTC')}   "
                 f"ETA to finish all: {eta_str}   "
                 f"Run elapsed: {_fmt_duration(time.monotonic() - script_start)}")
        log.info(f"│")

        _record_progress(run_id, short, "running", started_at=wall_now)

        # ── Fetch ─────────────────────────────────────────────────────────────
        success: bool
        try:
            result  = fetch_segments_for_city(city)
            success = result is not False
        except Exception as exc:
            log.error(f"│  ❌  Unexpected exception: {exc}", exc_info=True)
            success = False

        city_elapsed   = time.monotonic() - city_start
        total_elapsed  = time.monotonic() - script_start
        city_times.append(city_elapsed)

        if success:
            seg_count = _get_city_segment_count(short)
            succeeded.append((city, seg_count))
            _record_progress(
                run_id, short, "success",
                segments=seg_count,
                finished_at=datetime.now(timezone.utc),
                duration=int(city_elapsed),
            )
            log.info(f"│  ✅  Success")
            log.info(f"│  Segments inserted : {seg_count:,}")
            log.info(f"│  City fetch time   : {_fmt_duration(city_elapsed)}")
        else:
            failed.append(city)
            _record_progress(
                run_id, short, "failed",
                finished_at=datetime.now(timezone.utc),
                duration=int(city_elapsed),
                error="fetch_segments_for_city returned False",
            )
            log.warning(f"│  ❌  Failed — will appear in final summary")
            log.warning(f"│  City fetch time   : {_fmt_duration(city_elapsed)}")

        # ── Running tally ─────────────────────────────────────────────────────
        total_segs_so_far = sum(s for _, s in succeeded)
        log.info(f"│")
        log.info(
            f"│  📊 Tally  "
            f"✅ {len(succeeded)} ok  "
            f"❌ {len(failed)} failed  "
            f"| {len(succeeded) + len(failed)}/{n} processed  "
            f"| {total_segs_so_far:,} segments total  "
            f"| run: {_fmt_duration(total_elapsed)}"
        )
        log.info(f"└{'─' * 66}")

        # ── Cooldown before next city ─────────────────────────────────────────
        if idx < n:
            # Recalculate ETA after updating city_times
            avg_fetch  = sum(city_times) / len(city_times)
            left       = n - idx
            eta_secs   = left * avg_fetch + left * WAIT_MINUTES * 60
            log.info("")
            _countdown_wait(
                WAIT_MINUTES,
                next_city=remaining[idx],
                total_elapsed=time.monotonic() - script_start,
                cities_done=idx,
                cities_total=n,
                eta_remaining=eta_secs,
            )

    # ── Final summary ────────────────────────────────────────────────────────
    total_time = time.monotonic() - script_start
    total_segs = sum(s for _, s in succeeded)
    wall_end   = datetime.now(timezone.utc)

    log.info("")
    log.info(LINE)
    log.info(f"  📊  BATCH COMPLETE  —  run: {run_id}")
    log.info(THIN)
    log.info(f"  ✅  Success  : {len(succeeded):>3} cities  |  {total_segs:,} segments inserted")
    log.info(f"  ⏭   Skipped  : {len(already_done):>3} cities  (were already in DB)")
    log.info(f"  ❌  Failed   : {len(failed):>3} cities")
    log.info(THIN)
    log.info(f"  ⏱   Total duration : {_fmt_duration(total_time)}")
    log.info(f"  📅  Started        : {wall_start.strftime('%Y-%m-%d %H:%M UTC')}")
    log.info(f"  📅  Finished       : {wall_end.strftime('%Y-%m-%d %H:%M UTC')}")
    log.info(LINE)

    if succeeded or failed:
        log.info("")
        log.info("  Per-city results:")
        log.info(f"  {'City':<26} {'Segments':>10}  {'Duration':>10}  Status")
        log.info(f"  {THIN}")
        for city_q, segs in succeeded:
            # find duration from the progress table if possible, else show —
            short = _short_name(city_q)
            db = SessionLocal()
            try:
                row = db.execute(
                    text("SELECT duration_seconds FROM fetch_progress "
                         "WHERE run_id=:r AND city=:c LIMIT 1"),
                    {"r": run_id, "c": short},
                ).fetchone()
                dur_str = _fmt_duration(row[0]) if row and row[0] else "—"
            except Exception:
                dur_str = "—"
            finally:
                db.close()
            log.info(f"  {short:<26} {segs:>10,}  {dur_str:>10}  ✅")
        for city_q in failed:
            log.info(f"  {_short_name(city_q):<26} {'—':>10}  {'—':>10}  ❌")

    log.info(LINE)
    if failed:
        log.info(f"  ⚠️  Failed cities: {[_short_name(c) for c in failed]}")
        log.info("  Tip: redeploy to retry — resume logic will skip already-done cities.")
        log.info(LINE)


if __name__ == "__main__":
    main()
