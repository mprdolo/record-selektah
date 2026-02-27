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
            """SELECT a.id, a.artist, a.title, a.release_year, a.master_year,
                      a.master_year_override, a.cover_image_url, a.genres, a.styles,
                      a.format, a.discogs_url, a.master_url,
                      bb.rank AS big_board_rank, bb.year AS big_board_year
               FROM albums a
               LEFT JOIN big_board_entries bb ON bb.album_id = a.id
               WHERE a.id = ?""",
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
                      a.master_year_override, a.cover_image_url,
                      a.genres, bb.rank AS big_board_rank, bb.year AS big_board_year
               FROM listens l
               JOIN albums a ON l.album_id = a.id
               LEFT JOIN big_board_entries bb ON bb.album_id = a.id
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

        cursor.execute("SELECT COUNT(*) FROM big_board_entries WHERE album_id IS NOT NULL")
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

        # Single query: all Big Board entries LEFT JOIN direct album + via album
        cursor.execute(
            """SELECT bb.rank, bb.artist, bb.title, bb.year,
                      bb.album_id, bb.via_album_id,
                      a.id AS joined_album_id,
                      a.cover_image_url, a.genres,
                      va.id AS via_joined_id,
                      va.cover_image_url AS via_cover_image_url,
                      va.genres AS via_genres,
                      va.artist AS via_album_artist,
                      va.title AS via_album_title
               FROM big_board_entries bb
               LEFT JOIN albums a ON a.id = bb.album_id AND a.is_removed = 0
               LEFT JOIN albums va ON va.id = bb.via_album_id AND va.is_removed = 0
               ORDER BY bb.rank"""
        )
        rows = cursor.fetchall()

        entries = []
        for row in rows:
            direct = row["joined_album_id"] is not None
            via = row["via_joined_id"] is not None
            owned = direct or via
            # Prefer direct match, fall back to via
            cover = row["cover_image_url"] if direct else (row["via_cover_image_url"] if via else None)
            raw_genres = row["genres"] if direct else (row["via_genres"] if via else None)
            genres = json.loads(raw_genres) if raw_genres else []
            entry = {
                "rank": row["rank"],
                "artist": row["artist"],
                "title": row["title"],
                "year": row["year"],
                "cover_image_url": cover if owned else None,
                "genres": genres if owned else [],
                "owned": owned,
                "album_id": row["album_id"] if direct else None,
                "via_album_id": row["via_album_id"] if via else None,
                "via_album_artist": row["via_album_artist"] if via else None,
                "via_album_title": row["via_album_title"] if via else None,
            }
            entries.append(entry)

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
            """SELECT a.id, a.artist, a.title, a.release_year, a.master_year,
                      a.master_year_override, a.cover_image_url, a.genres, a.format,
                      bb.rank AS big_board_rank, bb.year AS big_board_year
               FROM albums a
               LEFT JOIN big_board_entries bb ON bb.album_id = a.id
               WHERE a.is_removed = 0
               ORDER BY a.artist, a.title"""
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
                key=lambda a: (a["display_year"] or 0, a["artist"].lower()),
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
                      a.master_year_override, a.cover_image_url,
                      a.genres, bb.rank AS big_board_rank, bb.year AS big_board_year,
                      COUNT(l.id) as listen_count,
                      MIN(l.selected_at) as first_listened,
                      MAX(l.selected_at) as last_listened
               FROM albums a
               JOIN listens l ON l.album_id = a.id AND l.did_listen = 1
               LEFT JOIN big_board_entries bb ON bb.album_id = a.id
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
            """SELECT a.id, a.artist, a.title, a.release_year, a.master_year,
                      a.master_year_override, a.cover_image_url, a.genres, a.format,
                      bb.rank AS big_board_rank, bb.year AS big_board_year
               FROM albums a
               LEFT JOIN big_board_entries bb ON bb.album_id = a.id
               WHERE a.is_excluded = 1 AND a.is_removed = 0
               ORDER BY a.artist, a.title"""
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
            """SELECT a.id, a.artist, a.title, a.release_year, a.master_year,
                      a.master_year_override, a.cover_image_url, a.genres, a.styles,
                      a.format, a.discogs_url, a.master_url, a.discogs_master_id,
                      a.master_id_override,
                      bb.rank AS big_board_rank, bb.year AS big_board_year
               FROM albums a
               LEFT JOIN big_board_entries bb ON bb.album_id = a.id
               WHERE a.id = ?""",
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


@app.route("/api/album/<int:album_id>/use-release-as-master", methods=["POST"])
def use_release_as_master(album_id):
    """Re-fetch cover from the album's Discogs release and apply it as the primary image."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, discogs_release_id FROM albums WHERE id = ?",
            (album_id,),
        )
        album = cursor.fetchone()
        if not album:
            return api_response(False, message="Album not found.", status_code=404)

        release_id = album["discogs_release_id"]
        if not release_id:
            return api_response(False, message="Album has no Discogs release ID.", status_code=400)

        release_data = _fetch_release_data(release_id)
        cover_image_url = release_data.get("cover_image_url")
        if not cover_image_url:
            return api_response(False, message="No cover image found on release.", status_code=404)

        cursor.execute(
            "UPDATE albums SET cover_image_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (cover_image_url, album_id),
        )
        conn.commit()
        return api_response(message="Cover image refreshed from release.")
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
            """SELECT a.id, a.artist, a.title, a.release_year, a.master_year,
                      a.master_year_override, a.cover_image_url, a.genres,
                      bb.rank AS big_board_rank, bb.year AS big_board_year
               FROM albums a
               LEFT JOIN big_board_entries bb ON bb.album_id = a.id
               WHERE a.is_removed = 0
                 AND (a.artist LIKE ? OR a.title LIKE ?)
               ORDER BY a.artist, a.title
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


@app.route("/api/bigboard/entry/<int:rank>", methods=["PUT"])
def update_bigboard_entry(rank):
    """Update artist, title, or year on a Big Board entry."""
    body = request.get_json(silent=True) or {}
    artist = body.get("artist")
    title = body.get("title")
    year = body.get("year")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM big_board_entries WHERE rank = ?", (rank,))
        if not cursor.fetchone():
            return api_response(False, message="Big Board entry not found.", status_code=404)

        updates = []
        params = []
        if artist is not None:
            updates.append("artist = ?")
            params.append(artist.strip())
        if title is not None:
            updates.append("title = ?")
            params.append(title.strip())
        if year is not None:
            if year == "" or year is False:
                updates.append("year = NULL")
            else:
                yr = int(year)
                if yr < 1900 or yr > 2099:
                    return api_response(False, message="Year must be between 1900 and 2099.", status_code=400)
                updates.append("year = ?")
                params.append(yr)

        if not updates:
            return api_response(False, message="No fields to update.", status_code=400)

        params.append(rank)
        cursor.execute(
            f"UPDATE big_board_entries SET {', '.join(updates)} WHERE rank = ?",
            params,
        )
        conn.commit()
        return api_response(message="Big Board entry updated.")
    except ValueError:
        return api_response(False, message="Invalid year.", status_code=400)
    finally:
        conn.close()


@app.route("/api/bigboard/match", methods=["POST"])
def match_bigboard():
    """Manually match an unowned Big Board entry to an album in the collection."""
    body = request.get_json(silent=True) or {}
    album_id = body.get("album_id")
    rank = body.get("rank")

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

        # Check entry exists
        cursor.execute("SELECT id FROM big_board_entries WHERE rank = ?", (rank,))
        if not cursor.fetchone():
            return api_response(False, message="Big Board entry not found.", status_code=404)

        # Clear any existing match to this album (one rank per album)
        cursor.execute(
            "UPDATE big_board_entries SET album_id = NULL WHERE album_id = ?",
            (album_id,),
        )

        # Set album_id on the entry
        cursor.execute(
            "UPDATE big_board_entries SET album_id = ? WHERE rank = ?",
            (album_id, rank),
        )
        conn.commit()
        return api_response(message=f"Album matched to Big Board rank #{rank}.")
    except ValueError:
        return api_response(False, message="Invalid album_id or rank.", status_code=400)
    finally:
        conn.close()


@app.route("/api/bigboard/unmatch", methods=["POST"])
def unmatch_bigboard():
    body = request.get_json(silent=True) or {}
    album_id = body.get("album_id")
    if not album_id:
        return api_response(False, message="album_id is required.", status_code=400)
    conn = get_db_connection()
    try:
        album_id = int(album_id)
        cursor = conn.cursor()

        # Clear album_id on the entry — entry stays in table as unowned
        cursor.execute(
            "UPDATE big_board_entries SET album_id = NULL WHERE album_id = ?",
            (album_id,),
        )
        if cursor.rowcount == 0:
            return api_response(False, message="Album has no Big Board rank.", status_code=400)

        conn.commit()
        return api_response(message="Big Board rank removed.")
    except ValueError:
        return api_response(False, message="Invalid album_id.", status_code=400)
    finally:
        conn.close()


@app.route("/api/bigboard/entry/<int:rank>/via", methods=["POST"])
def set_bigboard_via(rank):
    """Set or clear via_album_id on a Big Board entry."""
    body = request.get_json(silent=True) or {}
    album_id = body.get("album_id")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Check entry exists
        cursor.execute("SELECT id FROM big_board_entries WHERE rank = ?", (rank,))
        if not cursor.fetchone():
            return api_response(False, message="Big Board entry not found.", status_code=404)

        if album_id is not None:
            album_id = int(album_id)
            # Check album exists
            cursor.execute("SELECT id FROM albums WHERE id = ?", (album_id,))
            if not cursor.fetchone():
                return api_response(False, message="Album not found.", status_code=404)

        cursor.execute(
            "UPDATE big_board_entries SET via_album_id = ? WHERE rank = ?",
            (album_id, rank),
        )
        conn.commit()

        if album_id:
            return api_response(message=f"Via album linked to Big Board rank #{rank}.")
        else:
            return api_response(message=f"Via album removed from Big Board rank #{rank}.")
    except ValueError:
        return api_response(False, message="Invalid album_id.", status_code=400)
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
