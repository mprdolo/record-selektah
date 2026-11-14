"""HTTP API behaviour."""
from conftest import add_album


def test_index_renders(client):
    assert client.get("/").status_code == 200


def test_search_matches_every_word_across_artist_and_title(client, conn):
    add_album(conn, "Bob Dylan", "Blonde On Blonde")
    add_album(conn, "Bob Dylan", "Highway 61 Revisited")
    add_album(conn, "Blondie", "Parallel Lines")
    data = client.get("/api/albums/search?q=dylan blonde").get_json()["data"]
    assert [a["title"] for a in data] == ["Blonde On Blonde"]


def test_search_rejects_short_query(client):
    assert client.get("/api/albums/search?q=a").status_code == 400


def test_next_then_mark_played(client, conn):
    album = add_album(conn, "Radiohead", "Kid A")
    picked = client.get("/api/next").get_json()["data"]
    assert picked["album_id"] == album and picked["times_played"] == 0

    assert client.post(f"/api/listened/{album}").status_code == 200
    detail = client.get(f"/api/album/{album}").get_json()["data"]
    assert detail["times_played"] == 1


def test_skips_and_unmarked_picks_do_not_count_as_plays(client, conn):
    album = add_album(conn, "Radiohead", "Kid A")
    client.get("/api/next")                       # picked, never marked
    client.get("/api/next")
    client.post(f"/api/skipped/{album}")          # picked, skipped
    client.post(f"/api/album/{album}/just-played")
    picked = client.get("/api/next").get_json()["data"]
    assert picked["times_played"] == 1
    assert client.get("/api/previous").get_json()["data"]["times_played"] == 1


def test_mark_listened_targets_latest_pick(client, conn):
    album = add_album(conn, "Radiohead", "Kid A")
    client.get("/api/next")
    client.get("/api/next")
    client.post(f"/api/listened/{album}")
    rows = conn.execute("SELECT did_listen FROM listens ORDER BY id").fetchall()
    assert [r[0] for r in rows] == [0, 1]


def test_excluded_albums_are_never_picked(client, conn):
    album = add_album(conn, "Radiohead", "Kid A")
    client.post(f"/api/exclude/{album}")
    assert client.get("/api/next").status_code == 404
    assert [a["album_id"] for a in client.get("/api/excluded").get_json()["data"]] == [album]
    client.post(f"/api/unexclude/{album}")
    assert client.get("/api/next").status_code == 200


def test_year_override_validation(client, conn):
    album = add_album(conn, "Radiohead", "Kid A", release_year=2016)
    assert client.post(f"/api/album/{album}/year", json={"year": 1800}).status_code == 400
    assert client.post(f"/api/album/{album}/year", json={"year": 2000}).status_code == 200
    assert client.get(f"/api/album/{album}").get_json()["data"]["display_year"] == 2000


def test_settings_round_trip(client):
    client.post("/api/settings", json={"discogs_username": "someone"})
    assert client.get("/api/settings").get_json()["data"]["discogs_username"] == "someone"


def test_match_requires_existing_entry_and_album(client, conn):
    album = add_album(conn, "Radiohead", "Kid A")
    assert client.post("/api/bigboard/match", json={"album_id": album, "rank": 5}).status_code == 404
    assert client.post("/api/bigboard/match", json={"album_id": 999, "rank": 1}).status_code == 404
    assert client.post("/api/bigboard/match", json={}).status_code == 400
