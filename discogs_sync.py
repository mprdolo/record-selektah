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

def _get_active_username():
    """Return username from DB settings if set, otherwise fall back to config."""
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = 'discogs_username'")
            row = cursor.fetchone()
            if row and row["value"]:
                return row["value"]
        finally:
            conn.close()
    except Exception:
        pass
    return DISCOGS_USERNAME


def _make_headers():
    return {
        "Authorization": f"Discogs token={DISCOGS_TOKEN}",
        "User-Agent": DISCOGS_USER_AGENT,
    }


def _make_collection_url(username=None):
    u = username or _get_active_username()
    return f"https://api.discogs.com/users/{u}/collection/folders/0/releases"


def fetch_collection_page(page=1, per_page=100, username=None):
    """Fetch a single page of the user's Discogs collection."""
    params = {"page": page, "per_page": per_page, "sort": "added", "sort_order": "desc"}
    resp = requests.get(_make_collection_url(username), headers=_make_headers(), params=params, timeout=30)
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


def _upsert_release(cursor, release):
    """Insert or update one collection release. Returns (album_id, was_added)."""
    cursor.execute(
        "SELECT id, master_id_override, release_id_override FROM albums WHERE discogs_release_id = ?",
        (release["discogs_release_id"],),
    )
    row = cursor.fetchone()

    if row is None:
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
        return cursor.lastrowid, True

    # Existing album: refresh metadata, but never overwrite what the user set
    # by hand. A master override owns the master link and the cover; a
    # release override owns the release link, year and cover.
    fields = {
        "artist": release["artist"],
        "title": release["title"],
        "genres": release["genres"],
        "styles": release["styles"],
        "format": release["format"],
    }
    if not row["master_id_override"]:
        fields["discogs_master_id"] = release["discogs_master_id"]
        fields["master_url"] = release["master_url"]
    if not row["release_id_override"]:
        fields["release_year"] = release["release_year"]
        fields["discogs_url"] = release["discogs_url"]
    if not row["master_id_override"] and not row["release_id_override"]:
        fields["cover_image_url"] = release["cover_image_url"]

    assignments = ", ".join(f"{col} = ?" for col in fields)
    cursor.execute(
        f"""UPDATE albums SET {assignments}, is_removed = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?""",
        [*fields.values(), row["id"]],
    )
    return row["id"], False


def _carry_over_replaced_pressings(cursor, removed_ids, added_ids):
    """
    When a record leaves the collection and a record with the same artist and
    title arrives in the same sync, it's almost always the same album under a
    different pressing (you swapped it in Discogs). Keep the original row,
    with its play history, exclusions, overrides and Big Board link, and
    point it at the new release instead of starting the album over.

    Returns the number of albums carried over.
    """
    if not removed_ids or not added_ids:
        return 0

    def by_name(ids):
        groups = {}
        placeholders = ",".join("?" for _ in ids)
        cursor.execute(
            f"SELECT * FROM albums WHERE id IN ({placeholders})", list(ids)
        )
        for row in cursor.fetchall():
            key = (row["artist"].strip().lower(), row["title"].strip().lower())
            groups.setdefault(key, []).append(row)
        return groups

    removed_by_name = by_name(removed_ids)
    added_by_name = by_name(added_ids)

    carried = 0
    for key, old_rows in removed_by_name.items():
        new_rows = added_by_name.get(key, [])
        # Only pair them up when it's unambiguous.
        if len(old_rows) != 1 or len(new_rows) != 1:
            continue
        old, new = old_rows[0], new_rows[0]

        cursor.execute("DELETE FROM albums WHERE id = ?", (new["id"],))
        fields = {
            "discogs_release_id": new["discogs_release_id"],
            "release_year": new["release_year"],
            "genres": new["genres"],
            "styles": new["styles"],
            "format": new["format"],
            "discogs_url": new["discogs_url"],
            "release_id_override": None,
        }
        if not old["master_id_override"]:
            fields["discogs_master_id"] = new["discogs_master_id"]
            fields["master_url"] = new["master_url"]
            fields["cover_image_url"] = new["cover_image_url"]
            # The master may have changed; let "Fetch Master Years" redo it.
            if new["discogs_master_id"] != old["discogs_master_id"]:
                fields["master_year"] = None
        assignments = ", ".join(f"{col} = ?" for col in fields)
        cursor.execute(
            f"""UPDATE albums SET {assignments}, is_removed = 0, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?""",
            [*fields.values(), old["id"]],
        )
        carried += 1
    return carried


def sync_collection(progress_callback=None):
    """
    Sync the full Discogs collection into the database.

    progress_callback(message, current, total) is called to report progress.
    Returns a dict with sync results.
    """
    if not DISCOGS_TOKEN:
        raise ValueError("DISCOGS_TOKEN is not set. Check your .env file.")

    username = _get_active_username()

    conn = get_db_connection()
    cursor = conn.cursor()

    # Track what's currently in the DB so we can detect removals
    cursor.execute("SELECT id, discogs_release_id FROM albums WHERE is_removed = 0")
    existing = {row["discogs_release_id"]: row["id"] for row in cursor.fetchall()}

    fetched_ids = set()
    added_album_ids = set()
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

            data = fetch_collection_page(page=page, username=username)

            pagination = data.get("pagination", {})
            total_pages = pagination.get("pages", 1)

            releases = data.get("releases", [])
            if not releases:
                break

            for item in releases:
                release = parse_release(item)
                fetched_ids.add(release["discogs_release_id"])
                album_id, was_added = _upsert_release(cursor, release)
                if was_added:
                    added_album_ids.add(album_id)
                    added += 1
                else:
                    updated += 1

            if page >= total_pages:
                break

            page += 1
            time.sleep(DISCOGS_RATE_LIMIT_DELAY)

        # Mark albums removed from Discogs (but don't delete history). If
        # Discogs handed back nothing at all, that's a glitch or a wrong
        # username, not an empty collection, so don't wipe everything.
        removed_album_ids = (
            {existing[rid] for rid in existing.keys() - fetched_ids} if fetched_ids else set()
        )
        if removed_album_ids:
            placeholders = ",".join("?" for _ in removed_album_ids)
            cursor.execute(
                f"""UPDATE albums SET is_removed = 1, updated_at = CURRENT_TIMESTAMP
                    WHERE id IN ({placeholders})""",
                list(removed_album_ids),
            )

        carried_over = _carry_over_replaced_pressings(cursor, removed_album_ids, added_album_ids)
        added -= carried_over
        removed = len(removed_album_ids) - carried_over

        # Log the sync
        cursor.execute(
            """INSERT INTO sync_log (sync_type, albums_added, albums_updated, albums_removed, notes)
               VALUES ('discogs', ?, ?, ?, ?)""",
            (
                added, updated, removed,
                f"{carried_over} replaced pressings carried over" if carried_over else None,
            ),
        )

        conn.commit()

        results = {
            "added": added,
            "updated": updated,
            "removed": removed,
            "replaced": carried_over,
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
