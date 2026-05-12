"""
fetch_all_india.py
------------------
Batch script that fetches OSMnx road segments for ~50 major Indian cities and
writes them into the road_segments table.

Resume logic:  On startup the script queries the DB for cities that already
               have rows and skips them automatically.

Pacing:        After each city (except the last) the script waits WAIT_MINUTES
               (default 30, overridable via env var) so that OSMnx / Overpass
               API rate-limits are respected.  A countdown is logged every
               minute so the log stream stays alive and Railway / Render don't
               think the process has hung.

Usage:
    WAIT_MINUTES=10 python fetch_all_india.py
"""

import logging
import os
import time

# ---------------------------------------------------------------------------
# Logging — set up before any other import so library loggers inherit config
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Local imports (support both `python fetch_all_india.py` and package import)
# ---------------------------------------------------------------------------
try:
    from .fetch_segments import fetch_segments_for_city
    from .database import SessionLocal
except ImportError:
    from fetch_segments import fetch_segments_for_city  # type: ignore[no-redef]
    from database import SessionLocal  # type: ignore[no-redef]

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WAIT_MINUTES: int = int(os.getenv("WAIT_MINUTES", "30"))

# ---------------------------------------------------------------------------
# City list — 16 Tier-1 metros (matching fetch_segments.py) + 34 Tier-2 cities
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
# Helpers
# ---------------------------------------------------------------------------

def _short_name(city_query: str) -> str:
    """Return the lowercased first component of a city query string.

    This must match the value that fetch_segments_for_city stores in the
    ``city`` column (i.e. ``city_query.split(',')[0].strip().lower()``).
    """
    return city_query.split(",")[0].strip().lower()


def _get_processed_cities() -> set[str]:
    """Query the DB and return the set of city short-names already present."""
    db = SessionLocal()
    try:
        result = db.execute(text("SELECT DISTINCT city FROM road_segments"))
        return {row[0].lower() for row in result if row[0]}
    except Exception as exc:
        log.warning(f"Could not query existing cities (DB may be empty): {exc}")
        return set()
    finally:
        db.close()


def _countdown_wait(minutes: int, next_city: str) -> None:
    """Sleep for *minutes* minutes, logging a line each minute."""
    log.info(
        f"⏳  Waiting {minutes} minute(s) before next city — {next_city}"
    )
    for remaining in range(minutes, 0, -1):
        if remaining == minutes:
            # Already logged above; just start the first sleep tick
            pass
        else:
            log.info(f"   ⏱  {remaining} minute(s) remaining…")
        time.sleep(60)
    log.info("▶   Wait finished — continuing.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    banner = "=" * 64
    log.info(banner)
    log.info("   🇮🇳  FETCH ALL INDIA — Road Segment Batch Processor")
    log.info(banner)

    # ── Determine which cities still need processing ─────────────────────────
    processed_set = _get_processed_cities()

    already_done  = [c for c in ALL_INDIA_CITIES if _short_name(c) in processed_set]
    remaining     = [c for c in ALL_INDIA_CITIES if _short_name(c) not in processed_set]
    total_cities  = len(ALL_INDIA_CITIES)

    log.info(f"Total cities in master list : {total_cities}")
    log.info(
        f"Already processed           : {len(already_done)}"
        + (f" → {[_short_name(c) for c in already_done]}" if already_done else "")
    )
    log.info(f"Remaining to process        : {len(remaining)}")
    log.info(f"Wait between cities         : {WAIT_MINUTES} minute(s)  "
             f"(override with WAIT_MINUTES env var)")
    log.info(banner)

    if not remaining:
        log.info("✅  All cities already processed. Nothing to do.")
        return

    # ── Process cities one by one ────────────────────────────────────────────
    succeeded: list[str] = []
    failed:    list[str] = []
    n = len(remaining)

    for idx, city in enumerate(remaining, start=1):
        log.info(f"[{idx}/{n}] 🏙   Starting: {city}")

        success: bool
        try:
            result = fetch_segments_for_city(city)
            # fetch_segments_for_city returns True/False; treat None as success
            # (older version of the function) for forward-compatibility.
            success = result is not False
        except Exception as exc:
            log.error(
                f"[{idx}/{n}] ❌  Unexpected exception for {city}: {exc}",
                exc_info=True,
            )
            success = False

        if success:
            succeeded.append(city)
            log.info(f"[{idx}/{n}] ✅  Finished: {city}")
        else:
            failed.append(city)
            log.warning(f"[{idx}/{n}] ❌  Failed:   {city}")

        # Wait between cities — skip the pause after the very last city
        if idx < n:
            _countdown_wait(WAIT_MINUTES, next_city=remaining[idx])  # idx is 0-based here

    # ── Summary ──────────────────────────────────────────────────────────────
    log.info(banner)
    log.info("   📊  BATCH COMPLETE — SUMMARY")
    log.info(banner)
    log.info(f"   ✅  Successfully processed : {len(succeeded)}")
    log.info(f"   ⏭   Skipped (already done) : {len(already_done)}")
    log.info(f"   ❌  Failed                 : {len(failed)}")
    if failed:
        log.info(f"   Failed cities: {[_short_name(c) for c in failed]}")
    log.info(banner)


if __name__ == "__main__":
    main()
