"""Re-syncing the Big Board must never undo links you fixed by hand."""
from bigboard_sync import read_big_board_csv, sync_big_board
from conftest import add_album, links, write_csv


def test_read_csv_skips_blank_rows_and_parses_fields(tmp_path):
    path = tmp_path / "bb.csv"
    path.write_text(
        "Artist,Title,Year,Owned\nRadiohead,OK Computer,1997,x\n,,,\nMiles Davis,Kind of Blue,1959,\nBad,Row,notayear,\n",
        encoding="utf-8",
    )
    entries = read_big_board_csv(str(path))
    assert [(e["artist"], e["rank"], e["year"], e["owned"]) for e in entries] == [
        ("Radiohead", 1, 1997, True),
        ("Miles Davis", 2, 1959, False),
        ("Bad", 3, None, False),
    ]


def test_first_sync_auto_matches(conn, tmp_path):
    ok = add_album(conn, "Radiohead", "OK Computer")
    csv = write_csv(tmp_path / "bb.csv", [("Radiohead", "OK Computer", 1997), ("Miles Davis", "Kind of Blue", 1959)])
    result = sync_big_board(csv)
    assert links(conn) == {1: ok, 2: None}
    assert result["matched"] == 1 and result["unmatched_count"] == 1


def test_duplicate_csv_rows_are_skipped(conn, tmp_path):
    csv = write_csv(tmp_path / "bb.csv", [("Radiohead", "OK Computer", 1997), ("The Radiohead", "OK Computer!", 1997)])
    result = sync_big_board(csv)
    assert result["duplicates_skipped"] == 1
    assert list(links(conn)) == [1]


def test_unlinked_album_stays_unlinked_after_resync(client, conn, tmp_path):
    wrong = add_album(conn, "Led Zeppelin", "Led Zeppelin II")  # matches entry exactly
    csv = write_csv(tmp_path / "bb.csv", [("Led Zeppelin", "Led Zeppelin II", 1969)])
    sync_big_board(csv)
    assert links(conn) == {1: wrong}

    # "I don't own this album"
    assert client.post("/api/bigboard/unmatch", json={"album_id": wrong}).status_code == 200
    sync_big_board(csv)
    sync_big_board(csv)
    assert links(conn) == {1: None}


def test_relinking_remembers_the_old_album_as_wrong(client, conn, tmp_path):
    wrong = add_album(conn, "Kind of a Drag", "The Buckinghams")  # stand-in for a bad auto-link
    right = add_album(conn, "The Buckinghams", "Kind of a Drag (Sundazed reissue)")
    csv = write_csv(tmp_path / "bb.csv", [("The Buckinghams", "Kind of a Drag", 1967)])
    sync_big_board(csv)
    conn.execute("UPDATE big_board_entries SET album_id = ? WHERE rank = 1", (wrong,))
    conn.commit()

    assert client.post("/api/bigboard/match", json={"album_id": right, "rank": 1}).status_code == 200
    assert links(conn) == {1: right}

    # Even if the right album later disappears, the old wrong one must not
    # come back on its own.
    conn.execute("UPDATE albums SET is_removed = 1 WHERE id = ?", (right,))
    conn.commit()
    sync_big_board(csv)
    assert links(conn) == {1: None}


def test_manual_link_survives_when_csv_rank_changes(client, conn, tmp_path):
    album = add_album(conn, "Max Roach", "Freedom Now Suite")
    csv = write_csv(tmp_path / "bb.csv", [("Max Roach", "We Insist!", 1960)])
    sync_big_board(csv)
    assert links(conn) == {1: None}
    client.post("/api/bigboard/match", json={"album_id": album, "rank": 1})

    csv = write_csv(tmp_path / "bb.csv", [("Someone", "New #1", 2020), ("Max Roach", "We Insist!", 1960)])
    sync_big_board(csv)
    assert links(conn) == {1: None, 2: album}


def test_manual_link_is_not_stolen_by_higher_ranked_fuzzy_match(client, conn, tmp_path):
    album = add_album(conn, "Gilberto Gil", "Gilberto Gil (1968)")
    csv = write_csv(tmp_path / "bb.csv", [("Gilberto Gil", "Gilberto Gil", 1968), ("Gilberto Gil", "Tropicália 2", 1993)])
    sync_big_board(csv)
    # Suppose the user decides this album belongs to rank 2.
    client.post("/api/bigboard/match", json={"album_id": album, "rank": 2})
    assert links(conn) == {1: None, 2: album}

    sync_big_board(csv)
    assert links(conn) == {1: None, 2: album}


def test_entry_edited_in_app_keeps_link_and_rejections(client, conn, tmp_path):
    album = add_album(conn, "Nick Lowe", "Pure Pop For Now People")
    wrong = add_album(conn, "Nick Lowe", "Jesus of Cool")
    csv = write_csv(tmp_path / "bb.csv", [("Nick Lowe", "Jesus of Cool", 1978)])
    sync_big_board(csv)
    assert links(conn) == {1: wrong}
    client.post("/api/bigboard/match", json={"album_id": album, "rank": 1})
    client.put("/api/bigboard/entry/1", json={"title": "Jesus of Cool (Pure Pop For Now People)"})

    sync_big_board(csv)
    assert links(conn) == {1: album}


def test_link_to_removed_album_is_rematched(conn, tmp_path):
    old = add_album(conn, "Radiohead", "OK Computer")
    csv = write_csv(tmp_path / "bb.csv", [("Radiohead", "OK Computer", 1997)])
    sync_big_board(csv)
    conn.execute("UPDATE albums SET is_removed = 1 WHERE id = ?", (old,))
    new = add_album(conn, "Radiohead", "OK Computer")
    conn.commit()

    sync_big_board(csv)
    assert links(conn) == {1: new}


def test_rejected_best_match_falls_back_to_next_best(client, conn, tmp_path):
    wrong = add_album(conn, "Astrud Gilberto", "The Astrud Gilberto Album")
    csv = write_csv(tmp_path / "bb.csv", [("Astrud Gilberto", "The Astrud Gilberto Album", 1965)])
    sync_big_board(csv)
    client.post("/api/bigboard/unmatch", json={"album_id": wrong})
    right = add_album(conn, "Astrud Gilberto", "The Astrud Gilberto Album")  # the copy you actually own

    sync_big_board(csv)
    assert links(conn) == {1: right}


def test_via_link_survives_resync(client, conn, tmp_path):
    comp = add_album(conn, "Various", "Nuggets")
    csv = write_csv(tmp_path / "bb.csv", [("The Seeds", "The Seeds", 1966)])
    sync_big_board(csv)
    client.post("/api/bigboard/entry/1/via", json={"album_id": comp})
    sync_big_board(csv)
    assert conn.execute("SELECT via_album_id FROM big_board_entries WHERE rank = 1").fetchone()[0] == comp


def test_relinking_back_clears_the_rejection(client, conn, tmp_path):
    album = add_album(conn, "Radiohead", "OK Computer")
    csv = write_csv(tmp_path / "bb.csv", [("Radiohead", "OK Computer", 1997)])
    sync_big_board(csv)
    client.post("/api/bigboard/unmatch", json={"album_id": album})
    client.post("/api/bigboard/match", json={"album_id": album, "rank": 1})
    assert conn.execute("SELECT COUNT(*) FROM big_board_rejected_matches").fetchone()[0] == 0
    sync_big_board(csv)
    assert links(conn) == {1: album}


def test_rejections_saved_by_older_versions_still_apply(client, conn, tmp_path):
    # Keys for remembered rejections must not change between versions, or
    # every rejection you made before upgrading would quietly stop working.
    wrong = add_album(conn, "Afrika Bambaataa & Soulsonic Force, Planet Patrol", "Planet Rock")
    conn.execute(
        "INSERT INTO big_board_rejected_matches (entry_artist_key, entry_title_key, album_id) VALUES (?, ?, ?)",
        ("afrika bambaataa soulsonic force", "planet rock the album", wrong),
    )
    conn.commit()
    csv = write_csv(tmp_path / "bb.csv", [("Afrika Bambaataa & Soulsonic Force", "Planet Rock: The Album", 1986)])
    sync_big_board(csv)
    assert links(conn) == {1: None}
