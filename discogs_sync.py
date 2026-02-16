import json
import time
import requests
from db import get_db_connection
from config import (
    DISCOGS_TOKEN,
    DISCOGS_USERNAME,
    DISCOGS_USER_AGENT,
    DISCOGS_RATE_LIMIT_DELAY,
)

COLLECTION_URL = (
    f"https://api.discogs.com/users/{DISCOGS_USERNAME}/collection/folders/0/releases"
)
HEADERS = {
    "Authorization": f"Discogs token={DISCOGS_TOKEN}",
    "User-Agent": DISCOGS_USER_AGENT,
}


def fetch_collection_page(page=1, per_page=100):
    """Fetch a single page of the user's Discogs collection."""
    params = {"page": page, "per_page": per_page, "sort": "added", "sort_order": "desc"}
    resp = requests.get(COLLECTION_URL, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_release(item):
    """Extract the fields we need from a Discogs collection item."""
    info = item["basic_information"]
    artists_list = info.get("artists", [])
    artist = ", ".join(a["name"] for a in artists_list) if artists_list else "Unknown"

    formats = info.get("formats", [])
    fmt = formats[0]["name"] if formats else None

    return {
        "discogs_release_id": info["id"],
        "discogs_master_id": info.get("master_id") or None,
        "artist": artist,
        "title": info.get("title", ""),
        "release_year": info.get("year") or None,
        "cover_image_url": info.get("cover_image") or info.get("thumb") or None,
        "genres": json.dumps(info.get("genres", [])),
        "styles": json.dumps(info.get("styles", [])),
        "format": fmt,
        "discogs_url": f"https://www.discogs.com/release/{info['id']}",
        "master_url": (
            f"https://www.discogs.com/master/{info['master_id']}"
            if info.get("master_id")
            else None
        ),
    }


def sync_collection(progress_callback=None):
    """
    Sync the full Discogs collection into the database.

    progress_callback(message, current, total) is called to report progress.
    Returns a dict with sync results.
    """
    if not DISCOGS_TOKEN:
        raise ValueError("DISCOGS_TOKEN is not set. Check your .env file.")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Track what's currently in the DB so we can detect removals
    cursor.execute("SELECT discogs_release_id FROM albums WHERE is_removed = 0")
    existing_ids = set(row[0] for row in cursor.fetchall())

    fetched_ids = set()
    added = 0
    updated = 0
    removed = 0
    page = 1
    total_pages = None

    try:
        while True:
            if progress_callback:
                if total_pages:
                    progress_callback(
                        f"Fetching page {page} of {total_pages}...", page, total_pages
                    )
                else:
                    progress_callback(f"Fetching page {page}...", page, 0)

            data = fetch_collection_page(page=page)

            pagination = data.get("pagination", {})
            total_pages = pagination.get("pages", 1)

            releases = data.get("releases", [])
            if not releases:
                break

            for item in releases:
                release = parse_release(item)
                fetched_ids.add(release["discogs_release_id"])

                # Check if this release already exists
                cursor.execute(
                    "SELECT id, is_removed FROM albums WHERE discogs_release_id = ?",
                    (release["discogs_release_id"],),
                )
                row = cursor.fetchone()

                if row is None:
                    # New album — insert
                    cursor.execute(
                        """INSERT INTO albums
                        (discogs_release_id, discogs_master_id, artist, title,
                         release_year, cover_image_url, genres, styles, format,
                         discogs_url, master_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            release["discogs_release_id"],
                            release["discogs_master_id"],
                            release["artist"],
                            release["title"],
                            release["release_year"],
                            release["cover_image_url"],
                            release["genres"],
                            release["styles"],
                            release["format"],
                            release["discogs_url"],
                            release["master_url"],
                        ),
                    )
                    added += 1
                else:
                    # Existing album — update metadata, preserve user data
                    # Check if user has a manual master override
                    cursor.execute(
                        "SELECT master_id_override FROM albums WHERE discogs_release_id = ?",
                        (release["discogs_release_id"],),
                    )
                    override_row = cursor.fetchone()
                    has_override = override_row and override_row["master_id_override"]

                    if has_override:
                        # Skip master_id and master_url — user overrode them
                        cursor.execute(
                            """UPDATE albums SET
                                artist = ?,
                                title = ?,
                                release_year = ?,
                                cover_image_url = ?,
                                genres = ?,
                                styles = ?,
                                format = ?,
                                discogs_url = ?,
                                is_removed = 0,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE discogs_release_id = ?""",
                            (
                                release["artist"],
                                release["title"],
                                release["release_year"],
                                release["cover_image_url"],
                                release["genres"],
                                release["styles"],
                                release["format"],
                                release["discogs_url"],
                                release["discogs_release_id"],
                            ),
                        )
                    else:
                        cursor.execute(
                            """UPDATE albums SET
                                discogs_master_id = ?,
                                artist = ?,
                                title = ?,
                                release_year = ?,
                                cover_image_url = ?,
                                genres = ?,
                                styles = ?,
                                format = ?,
                                discogs_url = ?,
                                master_url = ?,
                                is_removed = 0,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE discogs_release_id = ?""",
                            (
                                release["discogs_master_id"],
                                release["artist"],
                                release["title"],
                                release["release_year"],
                                release["cover_image_url"],
                                release["genres"],
                                release["styles"],
                                release["format"],
                                release["discogs_url"],
                                release["master_url"],
                                release["discogs_release_id"],
                            ),
                        )
                    updated += 1

            if page >= total_pages:
                break

            page += 1
            time.sleep(DISCOGS_RATE_LIMIT_DELAY)

        # Mark albums removed from Discogs (but don't delete history)
        removed_ids = existing_ids - fetched_ids
        if removed_ids:
            placeholders = ",".join("?" for _ in removed_ids)
            cursor.execute(
                f"""UPDATE albums SET is_removed = 1, updated_at = CURRENT_TIMESTAMP
                    WHERE discogs_release_id IN ({placeholders})""",
                list(removed_ids),
            )
            removed = len(removed_ids)

        # Log the sync
        cursor.execute(
            """INSERT INTO sync_log (sync_type, albums_added, albums_updated, albums_removed)
               VALUES ('discogs', ?, ?, ?)""",
            (added, updated, removed),
        )

        conn.commit()

        results = {
            "added": added,
            "updated": updated,
            "removed": removed,
            "total_fetched": len(fetched_ids),
        }

        if progress_callback:
            progress_callback(
                f"Done! Added {added}, updated {updated}, removed {removed}.",
                total_pages,
                total_pages,
            )

        return results

    except requests.exceptions.HTTPError as e:
        conn.rollback()
        raise RuntimeError(f"Discogs API error: {e.response.status_code} — {e.response.text}")
    except requests.exceptions.ConnectionError:
        conn.rollback()
        raise RuntimeError(
            "Couldn't reach Discogs — check your internet connection and try again."
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    def print_progress(msg, current, total):
        print(msg)

    print("Starting Discogs collection sync...")
    try:
        results = sync_collection(progress_callback=print_progress)
        print(f"\nSync complete!")
        print(f"  Added:   {results['added']}")
        print(f"  Updated: {results['updated']}")
        print(f"  Removed: {results['removed']}")
        print(f"  Total:   {results['total_fetched']}")
    except Exception as e:
        print(f"\nSync failed: {e}")
