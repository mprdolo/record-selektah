"""Discogs collection sync, with the Discogs API faked out."""
import pytest

import discogs_sync
from conftest import links, write_csv


def release(rid, artist, title, year=1970, master_id=None):
    return {
        "basic_information": {
            "id": rid,
            "master_id": master_id,
            "artists": [{"name": artist}],
            "title": title,
            "year": year,
            "cover_image": f"https://img/{rid}.jpg",
            "genres": ["Jazz"],
            "styles": [],
            "formats": [{"name": "Vinyl"}],
        }
    }


@pytest.fixture
def discogs(monkeypatch):
    """Set the collection Discogs will return: discogs(release(...), ...)."""
    collection = []

    def fake_fetch(page=1, per_page=100, username=None):
        return {"pagination": {"pages": 1}, "releases": list(collection)}

    monkeypatch.setattr(discogs_sync, "fetch_collection_page", fake_fetch)
    monkeypatch.setattr(discogs_sync, "DISCOGS_TOKEN", "test-token")
    monkeypatch.setattr(discogs_sync.time, "sleep", lambda s: None)

    def set_collection(*releases):
        collection[:] = releases

    return set_collection


def albums(conn):
    return {
        r["discogs_release_id"]: dict(r)
        for r in conn.execute("SELECT * FROM albums")
    }


def test_adds_updates_and_removes(conn, discogs):
    discogs(release(1, "Miles Davis", "Kind of Blue"), release(2, "Radiohead", "Kid A"))
    assert discogs_sync.sync_collection()["added"] == 2

    discogs(release(1, "Miles Davis", "Kind Of Blue"))
    result = discogs_sync.sync_collection()
    assert (result["added"], result["updated"], result["removed"]) == (0, 1, 1)
    rows = albums(conn)
    assert rows[1]["title"] == "Kind Of Blue"
    assert rows[2]["is_removed"] == 1


def test_empty_response_does_not_remove_everything(conn, discogs):
    discogs(release(1, "Miles Davis", "Kind of Blue"))
    discogs_sync.sync_collection()
    discogs()
    discogs_sync.sync_collection()
    assert albums(conn)[1]["is_removed"] == 0


def test_swapped_pressing_keeps_history_and_big_board_link(conn, discogs, tmp_path):
    from bigboard_sync import sync_big_board

    discogs(release(1, "The Red Garland Trio", "Groovy"))
    discogs_sync.sync_collection()
    album_id = conn.execute("SELECT id FROM albums").fetchone()[0]
    conn.execute("INSERT INTO listens (album_id, did_listen) VALUES (?, 1)", (album_id,))
    conn.execute("UPDATE albums SET master_year_override = 1957 WHERE id = ?", (album_id,))
    conn.commit()
    sync_big_board(write_csv(tmp_path / "bb.csv", [("Red Garland", "Groovy", 1957)]))
    assert links(conn) == {1: album_id}

    # You replace your copy in Discogs with a different pressing.
    discogs(release(2, "The Red Garland Trio", "Groovy", year=2018))
    result = discogs_sync.sync_collection()
    assert (result["added"], result["removed"], result["replaced"]) == (0, 0, 1)

    row = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
    assert row["discogs_release_id"] == 2 and row["release_year"] == 2018
    assert row["is_removed"] == 0 and row["master_year_override"] == 1957
    assert conn.execute("SELECT COUNT(*) FROM albums").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM listens WHERE album_id = ?", (album_id,)).fetchone()[0] == 1
    assert links(conn) == {1: album_id}


def test_ambiguous_swaps_are_left_alone(conn, discogs):
    discogs(release(1, "Lee Morgan", "The Sidewinder"), release(2, "Lee Morgan", "The Sidewinder"))
    discogs_sync.sync_collection()
    discogs(release(3, "Lee Morgan", "The Sidewinder"))
    result = discogs_sync.sync_collection()
    assert result["replaced"] == 0 and result["removed"] == 2 and result["added"] == 1


def test_release_override_survives_sync(client, conn, discogs, monkeypatch):
    import app as app_module

    discogs(release(1, "Miles Davis", "Kind of Blue", year=1997))
    discogs_sync.sync_collection()
    album_id = conn.execute("SELECT id FROM albums").fetchone()[0]

    monkeypatch.setattr(
        app_module, "_fetch_release_data",
        lambda rid: {"year": 1959, "cover_image_url": "https://img/original.jpg"},
    )
    assert client.post(f"/api/album/{album_id}/release", json={"release_id": 999}).status_code == 200

    result = discogs_sync.sync_collection()
    assert result["removed"] == 0 and result["added"] == 0
    row = albums(conn)[1]
    assert row["id"] == album_id
    assert row["release_id_override"] == 999
    assert row["discogs_url"].endswith("/release/999")
    assert row["release_year"] == 1959
    assert row["cover_image_url"] == "https://img/original.jpg"


def test_master_override_keeps_cover_and_master(conn, discogs):
    discogs(release(1, "Miles Davis", "Kind of Blue", master_id=10))
    discogs_sync.sync_collection()
    conn.execute(
        "UPDATE albums SET master_id_override = 77, discogs_master_id = 77, cover_image_url = 'mine.jpg'"
    )
    conn.commit()
    discogs_sync.sync_collection()
    row = albums(conn)[1]
    assert (row["discogs_master_id"], row["cover_image_url"]) == (77, "mine.jpg")


def test_missing_token_is_a_clear_error(conn, monkeypatch):
    monkeypatch.setattr(discogs_sync, "DISCOGS_TOKEN", None)
    with pytest.raises(ValueError, match="DISCOGS_TOKEN"):
        discogs_sync.sync_collection()
