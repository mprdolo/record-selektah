import json
import threading
from flask import Flask, jsonify, request, render_template
from config import SECRET_KEY
from db import init_db, get_db_connection
from selector import select_next_album

app = Flask(__name__)
app.secret_key = SECRET_KEY

# Track sync state
sync_status = {"in_progress": False, "type": None, "message": "", "current": 0, "total": 0}
sync_lock = threading.Lock()


def api_response(success=True, data=None, message="", status_code=200):
    """Standard JSON response wrapper."""
    return jsonify({"success": success, "data": data, "message": message}), status_code


# --- Pages ---

@app.route("/")
def index():
    return render_template("index.html")


# --- Selection API ---

@app.route("/api/next")
def next_album():
    result = select_next_album()
    if result is None:
        return api_response(
            False,
            message="No eligible albums found. Sync your collection or un-exclude some albums.",
            status_code=404,
        )
    return api_response(data=result)


@app.route("/api/previous")
def previous_album():
    """Return the most recent listen entry so the user can go back and mark it."""
    listen_id = request.args.get("before_listen_id", type=int)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if listen_id:
            # Get the listen entry just before the given one
            cursor.execute(
                """SELECT l.id, l.album_id, l.did_listen, l.skipped
                   FROM listens l WHERE l.id < ? ORDER BY l.id DESC LIMIT 1""",
                (listen_id,),
            )
        else:
            # Get the most recent listen entry
            cursor.execute(
                """SELECT l.id, l.album_id, l.did_listen, l.skipped
                   FROM listens l ORDER BY l.id DESC LIMIT 1"""
            )

        listen = cursor.fetchone()
        if not listen:
            return api_response(False, message="No previous selection found.", status_code=404)

        cursor.execute(
            """SELECT id, artist, title, release_year, master_year, big_board_year,
                      master_year_override, cover_image_url, genres, styles, format,
                      big_board_rank, discogs_url, master_url
               FROM albums WHERE id = ?""",
            (listen["album_id"],),
        )
        album = cursor.fetchone()
        if not album:
            return api_response(False, message="Album not found.", status_code=404)

        display_year = album["master_year_override"] or album["big_board_year"] or album["master_year"] or album["release_year"]
        genres = json.loads(album["genres"]) if album["genres"] else []
        styles = json.loads(album["styles"]) if album["styles"] else []

        cursor.execute(
            "SELECT COUNT(*) FROM listens WHERE album_id = ?",
            (album["id"],),
        )
        times_played = cursor.fetchone()[0]

        return api_response(data={
            "album_id": album["id"],
            "listen_id": listen["id"],
            "artist": album["artist"],
            "title": album["title"],
            "display_year": display_year,
            "release_year": album["release_year"],
            "master_year": album["master_year"],
            "cover_image_url": album["cover_image_url"],
            "genres": genres,
            "styles": styles,
            "format": album["format"],
            "big_board_rank": album["big_board_rank"],
            "discogs_url": album["discogs_url"],
            "master_url": album["master_url"],
            "times_played": times_played,
            "did_listen": bool(listen["did_listen"]),
            "skipped": bool(listen["skipped"]),
        })
    finally:
        conn.close()


@app.route("/api/listened/<int:album_id>", methods=["POST"])
def mark_listened(album_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Update the most recent listen entry for this album
        cursor.execute(
            """UPDATE listens SET did_listen = 1, skipped = 0
               WHERE id = (
                   SELECT id FROM listens WHERE album_id = ?
                   ORDER BY selected_at DESC LIMIT 1
               )""",
            (album_id,),
        )
        if cursor.rowcount == 0:
            return api_response(False, message="No selection found for this album.", status_code=404)
        conn.commit()
        return api_response(message="Marked as listened.")
    finally:
        conn.close()


@app.route("/api/skipped/<int:album_id>", methods=["POST"])
def mark_skipped(album_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE listens SET skipped = 1, did_listen = 0
               WHERE id = (
                   SELECT id FROM listens WHERE album_id = ?
                   ORDER BY selected_at DESC LIMIT 1
               )""",
            (album_id,),
        )
        if cursor.rowcount == 0:
            return api_response(False, message="No selection found for this album.", status_code=404)
        conn.commit()
        return api_response(message="Marked as skipped.")
    finally:
        conn.close()


@app.route("/api/exclude/<int:album_id>", methods=["POST"])
def exclude_album(album_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE albums SET is_excluded = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (album_id,),
        )
        if cursor.rowcount == 0:
            return api_response(False, message="Album not found.", status_code=404)
        conn.commit()
        return api_response(message="Album excluded from future selections.")
    finally:
        conn.close()


@app.route("/api/unexclude/<int:album_id>", methods=["POST"])
def unexclude_album(album_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE albums SET is_excluded = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (album_id,),
        )
        if cursor.rowcount == 0:
            return api_response(False, message="Album not found.", status_code=404)
        conn.commit()
        return api_response(message="Album re-included in selections.")
    finally:
        conn.close()


# --- History & Stats ---

@app.route("/api/history")
def listening_history():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    per_page = min(per_page, 100)
    offset = (page - 1) * per_page

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM listens WHERE did_listen = 1 OR skipped = 1")
        total = cursor.fetchone()[0]

        cursor.execute(
            """SELECT l.id, l.album_id, l.selected_at, l.did_listen, l.skipped,
                      a.artist, a.title, a.release_year, a.master_year,
                      a.big_board_year, a.master_year_override, a.cover_image_url,
                      a.genres, a.big_board_rank
               FROM listens l
               JOIN albums a ON l.album_id = a.id
               WHERE l.did_listen = 1 OR l.skipped = 1
               ORDER BY l.selected_at DESC
               LIMIT ? OFFSET ?""",
            (per_page, offset),
        )
        rows = cursor.fetchall()

        history = []
        for row in rows:
            display_year = row["master_year_override"] or row["big_board_year"] or row["master_year"] or row["release_year"]
            genres = json.loads(row["genres"]) if row["genres"] else []
            history.append({
                "listen_id": row["id"],
                "album_id": row["album_id"],
                "selected_at": row["selected_at"],
                "did_listen": bool(row["did_listen"]),
                "skipped": bool(row["skipped"]),
                "artist": row["artist"],
                "title": row["title"],
                "display_year": display_year,
                "cover_image_url": row["cover_image_url"],
                "genres": genres,
                "big_board_rank": row["big_board_rank"],
            })

        return api_response(data={
            "history": history,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page if total else 0,
        })
    finally:
        conn.close()


@app.route("/api/stats")
def collection_stats():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM albums WHERE is_removed = 0")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM albums WHERE is_excluded = 1 AND is_removed = 0")
        excluded = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM albums WHERE is_removed = 1")
        removed = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM albums WHERE big_board_rank IS NOT NULL AND is_removed = 0")
        ranked = cursor.fetchone()[0]

        cursor.execute(
            """SELECT COUNT(DISTINCT album_id) FROM listens WHERE did_listen = 1"""
        )
        unique_listened = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM listens WHERE did_listen = 1")
        total_listens = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM listens WHERE skipped = 1")
        total_skips = cursor.fetchone()[0]

        cursor.execute(
            "SELECT synced_at FROM sync_log WHERE sync_type = 'discogs' ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        last_discogs_sync = row["synced_at"] if row else None

        cursor.execute(
            "SELECT synced_at FROM sync_log WHERE sync_type = 'big_board' ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        last_bigboard_sync = row["synced_at"] if row else None

        return api_response(data={
            "total_albums": total,
            "excluded": excluded,
            "removed": removed,
            "big_board_ranked": ranked,
            "unique_listened": unique_listened,
            "total_listens": total_listens,
            "total_skips": total_skips,
            "last_discogs_sync": last_discogs_sync,
            "last_bigboard_sync": last_bigboard_sync,
        })
    finally:
        conn.close()


@app.route("/api/bigboard")
def bigboard():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Get owned albums with big_board_rank
        cursor.execute(
            """SELECT id, big_board_rank, artist, title,
                      big_board_year, master_year, release_year,
                      master_year_override, cover_image_url, genres
               FROM albums
               WHERE big_board_rank IS NOT NULL AND is_removed = 0
               ORDER BY big_board_rank"""
        )
        rows = cursor.fetchall()

        entries = []
        for row in rows:
            display_year = row["master_year_override"] or row["big_board_year"] or row["master_year"] or row["release_year"]
            genres = json.loads(row["genres"]) if row["genres"] else []
            entries.append({
                "rank": row["big_board_rank"],
                "artist": row["artist"],
                "title": row["title"],
                "year": display_year,
                "cover_image_url": row["cover_image_url"],
                "genres": genres,
                "owned": True,
                "album_id": row["id"],
            })

        owned_ranks = {e["rank"] for e in entries}

        # Get unmatched entries from the most recent big_board sync
        cursor.execute(
            """SELECT unmatched_entries FROM sync_log
               WHERE sync_type = 'big_board' AND unmatched_entries IS NOT NULL
               ORDER BY id DESC LIMIT 1"""
        )
        row = cursor.fetchone()
        if row and row["unmatched_entries"]:
            unmatched = json.loads(row["unmatched_entries"])
            for u in unmatched:
                if u["rank"] not in owned_ranks:
                    entries.append({
                        "rank": u["rank"],
                        "artist": u["artist"],
                        "title": u["title"],
                        "year": u.get("year"),
                        "cover_image_url": None,
                        "genres": [],
                        "owned": False,
                    })

        entries.sort(key=lambda e: e["rank"])
        return api_response(data=entries)
    finally:
        conn.close()


@app.route("/api/library")
def library():
    sort = request.args.get("sort", "artist")
    order = request.args.get("order", "asc")

    if sort not in ("title", "artist", "master_year", "release_year"):
        sort = "artist"
    if order not in ("asc", "desc"):
        order = "asc"

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, artist, title, release_year, master_year, big_board_year,
                      master_year_override, cover_image_url, genres, format, big_board_rank
               FROM albums WHERE is_removed = 0
               ORDER BY artist, title"""
        )
        rows = cursor.fetchall()

        albums = []
        for row in rows:
            display_year = row["master_year_override"] or row["big_board_year"] or row["master_year"] or row["release_year"]
            genres = json.loads(row["genres"]) if row["genres"] else []
            albums.append({
                "album_id": row["id"],
                "artist": row["artist"],
                "title": row["title"],
                "release_year": row["release_year"],
                "master_year": row["master_year"],
                "display_year": display_year,
                "cover_image_url": row["cover_image_url"],
                "genres": genres,
                "format": row["format"],
                "big_board_rank": row["big_board_rank"],
            })

        # Sort in Python
        reverse = order == "desc"
        if sort == "artist":
            albums.sort(key=lambda a: _strip_article(a["artist"]).lower(), reverse=reverse)
        elif sort == "title":
            albums.sort(key=lambda a: _strip_article(a["title"]).lower(), reverse=reverse)
        elif sort == "master_year":
            albums.sort(
                key=lambda a: (a["master_year"] or a["release_year"] or 0, a["artist"].lower()),
                reverse=reverse,
            )
        elif sort == "release_year":
            albums.sort(
                key=lambda a: (a["release_year"] or 0, a["artist"].lower()),
                reverse=reverse,
            )

        return api_response(data={"albums": albums, "total": len(albums)})
    finally:
        conn.close()


def _strip_article(name):
    """Strip leading 'The ' or 'A ' for sorting."""
    if not name:
        return ""
    lower = name.lower()
    if lower.startswith("the "):
        return name[4:]
    if lower.startswith("a "):
        return name[2:]
    return name


@app.route("/api/listening-stats")
def listening_stats():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT a.id, a.artist, a.title, a.release_year, a.master_year,
                      a.big_board_year, a.master_year_override, a.cover_image_url,
                      a.genres, a.big_board_rank, COUNT(l.id) as listen_count,
                      MIN(l.selected_at) as first_listened,
                      MAX(l.selected_at) as last_listened
               FROM albums a
               JOIN listens l ON l.album_id = a.id AND l.did_listen = 1
               WHERE a.is_removed = 0
               GROUP BY a.id
               ORDER BY listen_count DESC, a.artist, a.title"""
        )
        rows = cursor.fetchall()

        albums = []
        for row in rows:
            display_year = row["master_year_override"] or row["big_board_year"] or row["master_year"] or row["release_year"]
            genres = json.loads(row["genres"]) if row["genres"] else []
            albums.append({
                "album_id": row["id"],
                "artist": row["artist"],
                "title": row["title"],
                "display_year": display_year,
                "cover_image_url": row["cover_image_url"],
                "genres": genres,
                "big_board_rank": row["big_board_rank"],
                "listen_count": row["listen_count"],
                "first_listened": row["first_listened"],
                "last_listened": row["last_listened"],
            })

        return api_response(data={"albums": albums, "total": len(albums)})
    finally:
        conn.close()


@app.route("/api/excluded")
def excluded_albums():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, artist, title, release_year, master_year, big_board_year,
                      master_year_override, cover_image_url, genres, format, big_board_rank
               FROM albums WHERE is_excluded = 1 AND is_removed = 0
               ORDER BY artist, title"""
        )
        rows = cursor.fetchall()

        albums = []
        for row in rows:
            display_year = row["master_year_override"] or row["big_board_year"] or row["master_year"] or row["release_year"]
            genres = json.loads(row["genres"]) if row["genres"] else []
            albums.append({
                "album_id": row["id"],
                "artist": row["artist"],
                "title": row["title"],
                "display_year": display_year,
                "cover_image_url": row["cover_image_url"],
                "genres": genres,
                "format": row["format"],
                "big_board_rank": row["big_board_rank"],
            })

        return api_response(data=albums)
    finally:
        conn.close()


# --- Album Detail & Master Correction ---

@app.route("/api/album/<int:album_id>")
def album_detail(album_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, artist, title, release_year, master_year, big_board_year,
                      master_year_override, cover_image_url, genres, styles, format,
                      big_board_rank, discogs_url, master_url, discogs_master_id,
                      master_id_override
               FROM albums WHERE id = ?""",
            (album_id,),
        )
        album = cursor.fetchone()
        if not album:
            return api_response(False, message="Album not found.", status_code=404)

        display_year = album["master_year_override"] or album["big_board_year"] or album["master_year"] or album["release_year"]
        genres = json.loads(album["genres"]) if album["genres"] else []
        styles = json.loads(album["styles"]) if album["styles"] else []

        cursor.execute(
            "SELECT COUNT(*) FROM listens WHERE album_id = ? AND did_listen = 1",
            (album_id,),
        )
        times_played = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM listens WHERE album_id = ? AND skipped = 1",
            (album_id,),
        )
        times_skipped = cursor.fetchone()[0]

        return api_response(data={
            "album_id": album["id"],
            "artist": album["artist"],
            "title": album["title"],
            "release_year": album["release_year"],
            "master_year": album["master_year"],
            "big_board_year": album["big_board_year"],
            "display_year": display_year,
            "cover_image_url": album["cover_image_url"],
            "genres": genres,
            "styles": styles,
            "format": album["format"],
            "big_board_rank": album["big_board_rank"],
            "discogs_url": album["discogs_url"],
            "master_url": album["master_url"],
            "discogs_master_id": album["discogs_master_id"],
            "master_id_override": album["master_id_override"],
            "master_year_override": album["master_year_override"],
            "times_played": times_played,
            "times_skipped": times_skipped,
        })
    finally:
        conn.close()


@app.route("/api/album/<int:album_id>/play-dates")
def album_play_dates(album_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT selected_at FROM listens
               WHERE album_id = ? AND did_listen = 1
               ORDER BY selected_at DESC""",
            (album_id,),
        )
        rows = cursor.fetchall()
        dates = [row["selected_at"] for row in rows]
        return api_response(data={"dates": dates})
    finally:
        conn.close()


@app.route("/api/album/<int:album_id>/master", methods=["POST"])
def set_album_master(album_id):
    from master_year_sync import fetch_master_year

    body = request.get_json(silent=True) or {}
    master_id = body.get("master_id")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM albums WHERE id = ?", (album_id,))
        if not cursor.fetchone():
            return api_response(False, message="Album not found.", status_code=404)

        if master_id is None:
            # Clear override
            cursor.execute(
                """UPDATE albums SET master_id_override = NULL,
                      discogs_master_id = NULL, master_url = NULL, master_year = NULL,
                      updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (album_id,),
            )
        else:
            master_id = int(master_id)
            master_year = None
            cover_image_url = None
            try:
                master_data = _fetch_master_data(master_id)
                master_year = master_data.get("year")
                cover_image_url = master_data.get("cover_image_url")
            except Exception:
                pass  # Fetch failed but we still save the ID

            master_url = f"https://www.discogs.com/master/{master_id}"
            if cover_image_url:
                cursor.execute(
                    """UPDATE albums SET master_id_override = ?, discogs_master_id = ?,
                          master_url = ?, master_year = ?, cover_image_url = ?,
                          updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (master_id, master_id, master_url, master_year, cover_image_url, album_id),
                )
            else:
                cursor.execute(
                    """UPDATE albums SET master_id_override = ?, discogs_master_id = ?,
                          master_url = ?, master_year = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (master_id, master_id, master_url, master_year, album_id),
                )

        conn.commit()
        return api_response(message="Master release updated.")
    except ValueError:
        return api_response(False, message="Invalid master ID.", status_code=400)
    finally:
        conn.close()


@app.route("/api/album/<int:album_id>/year", methods=["POST"])
def set_album_year(album_id):
    body = request.get_json(silent=True) or {}
    year = body.get("year")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM albums WHERE id = ?", (album_id,))
        if not cursor.fetchone():
            return api_response(False, message="Album not found.", status_code=404)

        if year is None:
            cursor.execute(
                "UPDATE albums SET master_year_override = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (album_id,),
            )
        else:
            year = int(year)
            if year < 1900 or year > 2099:
                return api_response(False, message="Year must be between 1900 and 2099.", status_code=400)
            cursor.execute(
                "UPDATE albums SET master_year_override = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (year, album_id),
            )

        conn.commit()
        return api_response(message="Original release year updated.")
    except ValueError:
        return api_response(False, message="Invalid year.", status_code=400)
    finally:
        conn.close()


@app.route("/api/album/<int:album_id>/release", methods=["POST"])
def set_album_release(album_id):
    body = request.get_json(silent=True) or {}
    release_id = body.get("release_id")

    if release_id is None:
        return api_response(False, message="release_id is required.", status_code=400)

    conn = get_db_connection()
    try:
        release_id = int(release_id)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM albums WHERE id = ?", (album_id,))
        if not cursor.fetchone():
            return api_response(False, message="Album not found.", status_code=404)

        # Fetch release data from Discogs
        release_data = _fetch_release_data(release_id)
        discogs_url = f"https://www.discogs.com/release/{release_id}"
        cover_image_url = release_data.get("cover_image_url")

        updates = [
            "discogs_release_id = ?", "discogs_url = ?", "updated_at = CURRENT_TIMESTAMP"
        ]
        params = [release_id, discogs_url]

        if cover_image_url:
            updates.append("cover_image_url = ?")
            params.append(cover_image_url)

        if release_data.get("year"):
            updates.append("release_year = ?")
            params.append(release_data["year"])

        params.append(album_id)
        cursor.execute(
            f"UPDATE albums SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        return api_response(message="Discogs release updated.")
    except ValueError:
        return api_response(False, message="Invalid release ID.", status_code=400)
    except Exception as e:
        return api_response(False, message=str(e), status_code=500)
    finally:
        conn.close()


@app.route("/api/albums/search")
def search_albums():
    """Search owned albums by artist/title for manual Big Board matching."""
    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return api_response(False, message="Search query too short.", status_code=400)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        like = f"%{q}%"
        cursor.execute(
            """SELECT id, artist, title, release_year, master_year, big_board_year,
                      master_year_override, cover_image_url, genres, big_board_rank
               FROM albums
               WHERE is_removed = 0
                 AND (artist LIKE ? OR title LIKE ?)
               ORDER BY artist, title
               LIMIT 20""",
            (like, like),
        )
        rows = cursor.fetchall()

        results = []
        for row in rows:
            display_year = row["master_year_override"] or row["big_board_year"] or row["master_year"] or row["release_year"]
            genres = json.loads(row["genres"]) if row["genres"] else []
            results.append({
                "album_id": row["id"],
                "artist": row["artist"],
                "title": row["title"],
                "display_year": display_year,
                "cover_image_url": row["cover_image_url"],
                "genres": genres,
                "big_board_rank": row["big_board_rank"],
            })

        return api_response(data=results)
    finally:
        conn.close()


@app.route("/api/bigboard/match", methods=["POST"])
def match_bigboard():
    """Manually match an unowned Big Board entry to an album in the collection."""
    body = request.get_json(silent=True) or {}
    album_id = body.get("album_id")
    rank = body.get("rank")
    year = body.get("year")

    if not album_id or not rank:
        return api_response(False, message="album_id and rank are required.", status_code=400)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        album_id = int(album_id)
        rank = int(rank)

        # Check album exists
        cursor.execute("SELECT id FROM albums WHERE id = ?", (album_id,))
        if not cursor.fetchone():
            return api_response(False, message="Album not found.", status_code=404)

        # Check if another album already has this rank
        cursor.execute(
            "SELECT id, artist, title FROM albums WHERE big_board_rank = ? AND id != ?",
            (rank, album_id),
        )
        existing = cursor.fetchone()
        if existing:
            # Clear the rank from the other album
            cursor.execute(
                "UPDATE albums SET big_board_rank = NULL, big_board_year = NULL WHERE id = ?",
                (existing["id"],),
            )

        # Set rank on the target album
        updates = ["big_board_rank = ?", "updated_at = CURRENT_TIMESTAMP"]
        params = [rank]
        if year:
            updates.append("big_board_year = ?")
            params.append(int(year))

        params.append(album_id)
        cursor.execute(
            f"UPDATE albums SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        return api_response(message=f"Album matched to Big Board rank #{rank}.")
    except ValueError:
        return api_response(False, message="Invalid album_id or rank.", status_code=400)
    finally:
        conn.close()


def _fetch_master_data(master_id):
    """Fetch year and cover image from Discogs master release."""
    import requests
    from config import DISCOGS_TOKEN, DISCOGS_USER_AGENT
    headers = {
        "Authorization": f"Discogs token={DISCOGS_TOKEN}",
        "User-Agent": DISCOGS_USER_AGENT,
    }
    url = f"https://api.discogs.com/masters/{master_id}"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    cover = None
    images = data.get("images", [])
    if images:
        cover = images[0].get("uri") or images[0].get("resource_url")
    return {"year": data.get("year"), "cover_image_url": cover}


def _fetch_release_data(release_id):
    """Fetch basic data from a Discogs release."""
    import requests
    from config import DISCOGS_TOKEN, DISCOGS_USER_AGENT
    headers = {
        "Authorization": f"Discogs token={DISCOGS_TOKEN}",
        "User-Agent": DISCOGS_USER_AGENT,
    }
    url = f"https://api.discogs.com/releases/{release_id}"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    cover = None
    images = data.get("images", [])
    if images:
        cover = images[0].get("uri") or images[0].get("resource_url")
    return {"year": data.get("year"), "cover_image_url": cover}


# --- Sync API ---

def run_sync(sync_type):
    """Run a sync operation in a background thread."""
    global sync_status

    def progress_callback(message, current, total):
        sync_status["message"] = message
        sync_status["current"] = current
        sync_status["total"] = total

    try:
        if sync_type == "discogs":
            from discogs_sync import sync_collection
            results = sync_collection(progress_callback=progress_callback)
            sync_status["message"] = (
                f"Done! Added {results['added']}, updated {results['updated']}, "
                f"removed {results['removed']}."
            )
        elif sync_type == "bigboard":
            from bigboard_sync import sync_big_board
            results = sync_big_board(progress_callback=progress_callback)
            sync_status["message"] = (
                f"Done! Matched {results['matched']}/{results['total_entries']} entries. "
                f"{results['unmatched_count']} unmatched."
            )
        elif sync_type == "master_years":
            from master_year_sync import sync_master_years
            results = sync_master_years(progress_callback=progress_callback)
            sync_status["message"] = (
                f"Done! Fetched {results['fetched']} master years. "
                f"{results['errors']} errors, {results['remaining']} remaining."
            )
    except Exception as e:
        sync_status["message"] = f"Error: {e}"
    finally:
        sync_status["in_progress"] = False


@app.route("/api/sync/discogs", methods=["POST"])
def sync_discogs():
    with sync_lock:
        if sync_status["in_progress"]:
            return api_response(
                False,
                message=f"A {sync_status['type']} sync is already in progress.",
                status_code=409,
            )
        sync_status["in_progress"] = True
        sync_status["type"] = "discogs"
        sync_status["message"] = "Starting Discogs sync..."
        sync_status["current"] = 0
        sync_status["total"] = 0

    thread = threading.Thread(target=run_sync, args=("discogs",), daemon=True)
    thread.start()
    return api_response(message="Discogs sync started.")


@app.route("/api/sync/bigboard", methods=["POST"])
def sync_bigboard():
    with sync_lock:
        if sync_status["in_progress"]:
            return api_response(
                False,
                message=f"A {sync_status['type']} sync is already in progress.",
                status_code=409,
            )
        sync_status["in_progress"] = True
        sync_status["type"] = "bigboard"
        sync_status["message"] = "Starting Big Board import..."
        sync_status["current"] = 0
        sync_status["total"] = 0

    thread = threading.Thread(target=run_sync, args=("bigboard",), daemon=True)
    thread.start()
    return api_response(message="Big Board import started.")


@app.route("/api/sync/master_years", methods=["POST"])
def sync_master_years():
    with sync_lock:
        if sync_status["in_progress"]:
            return api_response(
                False,
                message=f"A {sync_status['type']} sync is already in progress.",
                status_code=409,
            )
        sync_status["in_progress"] = True
        sync_status["type"] = "master_years"
        sync_status["message"] = "Starting master year fetch..."
        sync_status["current"] = 0
        sync_status["total"] = 0

    thread = threading.Thread(target=run_sync, args=("master_years",), daemon=True)
    thread.start()
    return api_response(message="Master year fetch started.")


@app.route("/api/sync/status")
def get_sync_status():
    return api_response(data={
        "in_progress": sync_status["in_progress"],
        "type": sync_status["type"],
        "message": sync_status["message"],
        "current": sync_status["current"],
        "total": sync_status["total"],
    })


# --- App startup ---

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=3345)
