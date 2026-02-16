import time
import requests
from db import get_db_connection
from config import DISCOGS_TOKEN, DISCOGS_USER_AGENT, DISCOGS_RATE_LIMIT_DELAY

HEADERS = {
    "Authorization": f"Discogs token={DISCOGS_TOKEN}",
    "User-Agent": DISCOGS_USER_AGENT,
}


def fetch_master_year(master_id):
    """Fetch the original release year from a Discogs master release."""
    url = f"https://api.discogs.com/masters/{master_id}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("year") or None


def sync_master_years(progress_callback=None, batch_size=0):
    """
    Fetch master release years for albums that don't have one yet.

    batch_size: if > 0, stop after this many fetches (useful for incremental runs).
                if 0, fetch all.
    progress_callback(message, current, total) reports progress.
    Returns dict with results.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Find albums with a master_id but no master_year
    cursor.execute(
        """SELECT id, discogs_master_id FROM albums
           WHERE discogs_master_id IS NOT NULL
             AND master_year IS NULL
             AND is_removed = 0
           ORDER BY id"""
    )
    albums = cursor.fetchall()
    total = len(albums)

    if batch_size > 0:
        albums = albums[:batch_size]

    to_fetch = len(albums)
    fetched = 0
    errors = 0

    if progress_callback:
        progress_callback(
            f"Fetching master years for {to_fetch} of {total} albums...", 0, to_fetch
        )

    try:
        for row in albums:
            album_id = row["id"]
            master_id = row["discogs_master_id"]

            try:
                year = fetch_master_year(master_id)
                if year:
                    cursor.execute(
                        """UPDATE albums SET master_year = ?, updated_at = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (year, album_id),
                    )
                fetched += 1
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    # Master doesn't exist — skip it
                    fetched += 1
                elif e.response.status_code == 429:
                    # Rate limited — wait and retry once
                    if progress_callback:
                        progress_callback("Rate limited, waiting 60s...", fetched, to_fetch)
                    time.sleep(60)
                    try:
                        year = fetch_master_year(master_id)
                        if year:
                            cursor.execute(
                                """UPDATE albums SET master_year = ?, updated_at = CURRENT_TIMESTAMP
                                   WHERE id = ?""",
                                (year, album_id),
                            )
                        fetched += 1
                    except Exception:
                        errors += 1
                else:
                    errors += 1
            except Exception:
                errors += 1

            # Commit every 50 records so progress isn't lost on failure
            if fetched % 50 == 0:
                conn.commit()

            if progress_callback and fetched % 10 == 0:
                progress_callback(
                    f"Fetched {fetched}/{to_fetch} master years...", fetched, to_fetch
                )

            time.sleep(DISCOGS_RATE_LIMIT_DELAY)

        conn.commit()

        remaining = total - fetched
        results = {
            "fetched": fetched,
            "errors": errors,
            "remaining": remaining,
        }

        if progress_callback:
            progress_callback(
                f"Done! Fetched {fetched} master years ({errors} errors, {remaining} remaining).",
                to_fetch,
                to_fetch,
            )

        return results

    except requests.exceptions.ConnectionError:
        conn.commit()  # Save what we got so far
        raise RuntimeError(
            "Couldn't reach Discogs — check your internet connection and try again."
        )
    except Exception:
        conn.commit()  # Save what we got so far
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    def print_progress(msg, current, total):
        print(msg)

    batch = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    print("Starting master year sync...")
    if batch:
        print(f"(batch mode: fetching up to {batch})")

    try:
        results = sync_master_years(progress_callback=print_progress, batch_size=batch)
        print(f"\nMaster year sync complete!")
        print(f"  Fetched:   {results['fetched']}")
        print(f"  Errors:    {results['errors']}")
        print(f"  Remaining: {results['remaining']}")
    except Exception as e:
        print(f"\nSync failed: {e}")
