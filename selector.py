import json
import random
from datetime import datetime, timezone
from db import get_db_connection


def get_display_year(album):
    """Return the best available year for display, per spec priority."""
    return album["big_board_year"] or album["master_year"] or album["release_year"]


def get_eligible_albums(conn):
    """Load all albums eligible for selection (not excluded, not removed)."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, artist, title, release_year, master_year, big_board_year,
                  cover_image_url, genres, styles, format, big_board_rank,
                  discogs_url, master_url
           FROM albums
           WHERE is_excluded = 0 AND is_removed = 0"""
    )
    return cursor.fetchall()


def get_listen_history(conn, album_id):
    """Get the most recent listen and total play count for an album."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT selected_at, did_listen, skipped FROM listens
           WHERE album_id = ?
           ORDER BY selected_at DESC LIMIT 1""",
        (album_id,),
    )
    last = cursor.fetchone()

    cursor.execute(
        "SELECT COUNT(*) FROM listens WHERE album_id = ?",
        (album_id,),
    )
    count = cursor.fetchone()[0]

    return last, count


def get_recent_selections(conn, n=10):
    """Get the last n selected albums with their metadata."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT a.artist, a.genres, a.big_board_year, a.master_year, a.release_year
           FROM listens l
           JOIN albums a ON l.album_id = a.id
           ORDER BY l.selected_at DESC
           LIMIT ?""",
        (n,),
    )
    return cursor.fetchall()


def calculate_weights(conn):
    """
    Calculate selection weights for all eligible albums.
    Returns list of (album_row, weight) tuples.
    """
    albums = get_eligible_albums(conn)
    if not albums:
        return []

    total_eligible = len(albums)

    # Get max Big Board rank for normalization
    ranked = [a["big_board_rank"] for a in albums if a["big_board_rank"] is not None]
    max_rank = max(ranked) if ranked else 1

    # Get recent selections for variety bonus
    recent = get_recent_selections(conn, n=10)
    recent_decades = set()
    recent_genres = set()
    recent_artists = set()

    for r in recent:
        year = r["big_board_year"] or r["master_year"] or r["release_year"]
        if year:
            recent_decades.add((year // 10) * 10)
        genres = json.loads(r["genres"]) if r["genres"] else []
        for g in genres:
            recent_genres.add(g)
        recent_artists.add(r["artist"])

    # Pre-fetch all listen data in bulk for performance
    cursor = conn.cursor()
    cursor.execute(
        """SELECT album_id, MAX(selected_at) as last_selected, COUNT(*) as play_count
           FROM listens
           GROUP BY album_id"""
    )
    listen_data = {}
    for row in cursor.fetchall():
        listen_data[row["album_id"]] = {
            "last_selected": row["last_selected"],
            "play_count": row["play_count"],
        }

    now = datetime.now(timezone.utc)
    cycle_length = total_eligible / 1.5

    results = []

    for album in albums:
        # --- Base weight (from Big Board ranking) ---
        if album["big_board_rank"] is not None:
            base_weight = ((max_rank - album["big_board_rank"] + 1) / max_rank) ** 0.5
        else:
            base_weight = 0.4

        # --- Recency factor ---
        album_listens = listen_data.get(album["id"])
        if album_listens and album_listens["last_selected"]:
            last_str = album_listens["last_selected"]
            try:
                last_dt = datetime.fromisoformat(last_str).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                last_dt = datetime.strptime(last_str, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
            days_since = (now - last_dt).total_seconds() / 86400
            recency_factor = min(1.0, (days_since / cycle_length) ** 1.5)
        else:
            recency_factor = 1.0

        # --- Variety bonus ---
        variety_bonus = 1.0

        display_year = get_display_year(album)
        if display_year:
            album_decade = (display_year // 10) * 10
            if album_decade not in recent_decades:
                variety_bonus *= 1.3

        album_genres = json.loads(album["genres"]) if album["genres"] else []
        if album_genres and not any(g in recent_genres for g in album_genres):
            variety_bonus *= 1.2

        if album["artist"] in recent_artists:
            variety_bonus *= 0.3

        # --- Never-played bonus ---
        if not album_listens:
            never_played_bonus = 1.5
        else:
            never_played_bonus = 1.0

        # --- Final weight ---
        final_weight = base_weight * recency_factor * variety_bonus * never_played_bonus
        results.append((album, final_weight))

    return results


def select_next_album():
    """
    Select the next album to play using weighted random selection.
    Returns a dict with album info, or None if no eligible albums.
    """
    conn = get_db_connection()

    try:
        weighted = calculate_weights(conn)
        if not weighted:
            return None

        albums, weights = zip(*weighted)
        selected = random.choices(albums, weights=weights, k=1)[0]

        # Get play history for this album
        last_listen, times_played = get_listen_history(conn, selected["id"])

        # Record the selection in listens table
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO listens (album_id) VALUES (?)",
            (selected["id"],),
        )
        listen_id = cursor.lastrowid
        conn.commit()

        display_year = get_display_year(selected)
        genres = json.loads(selected["genres"]) if selected["genres"] else []
        styles = json.loads(selected["styles"]) if selected["styles"] else []

        return {
            "album_id": selected["id"],
            "listen_id": listen_id,
            "artist": selected["artist"],
            "title": selected["title"],
            "display_year": display_year,
            "release_year": selected["release_year"],
            "master_year": selected["master_year"],
            "cover_image_url": selected["cover_image_url"],
            "genres": genres,
            "styles": styles,
            "format": selected["format"],
            "big_board_rank": selected["big_board_rank"],
            "discogs_url": selected["discogs_url"],
            "master_url": selected["master_url"],
            "times_played": times_played,
            "last_played": (
                last_listen["selected_at"] if last_listen else None
            ),
        }
    finally:
        conn.close()


if __name__ == "__main__":
    print("Testing selection algorithm...\n")

    # Run a few selections to see variety
    for i in range(5):
        result = select_next_album()
        if result:
            rank = f"#{result['big_board_rank']}" if result["big_board_rank"] else "unranked"
            year = result["display_year"] or "?"
            genres = ", ".join(result["genres"][:2]) if result["genres"] else "?"
            print(f"  {i+1}. {result['artist']} — {result['title']} ({year})")
            print(f"     {genres} | Big Board: {rank} | Played: {result['times_played']}x")
            print()
        else:
            print("  No eligible albums found!")
            break
