"""Reordering the Big Board in the app, and keeping that order on re-import."""
from bigboard_sync import sync_big_board
from conftest import add_album, write_csv


def order(conn):
    return [r[0] for r in conn.execute("SELECT title FROM big_board_entries ORDER BY rank")]


def board(tmp_path, titles):
    return write_csv(tmp_path / "bb.csv", [(f"Artist {t}", t, 1970) for t in titles])


def test_move_down_and_up(client, conn, tmp_path):
    sync_big_board(board(tmp_path, ["A", "B", "C", "D"]))
    assert client.post("/api/bigboard/move", json={"rank": 1, "to_rank": 3}).status_code == 200
    assert order(conn) == ["B", "C", "A", "D"]
    client.post("/api/bigboard/move", json={"rank": 4, "to_rank": 1})
    assert order(conn) == ["D", "B", "C", "A"]


def test_move_clamps_and_validates(client, conn, tmp_path):
    sync_big_board(board(tmp_path, ["A", "B", "C"]))
    client.post("/api/bigboard/move", json={"rank": 1, "to_rank": 99})
    assert order(conn) == ["B", "C", "A"]
    assert client.post("/api/bigboard/move", json={"rank": 9, "to_rank": 1}).status_code == 404
    assert client.post("/api/bigboard/move", json={"rank": "x"}).status_code == 400


def test_move_keeps_album_links(client, conn, tmp_path):
    album = add_album(conn, "Artist A", "A")
    sync_big_board(board(tmp_path, ["A", "B"]))
    client.post("/api/bigboard/move", json={"rank": 1, "to_rank": 2})
    assert conn.execute("SELECT rank FROM big_board_entries WHERE album_id = ?", (album,)).fetchone()[0] == 2


def test_import_without_app_changes_uses_sheet_order(conn, tmp_path):
    sync_big_board(board(tmp_path, ["A", "B", "C"]))
    sync_big_board(board(tmp_path, ["C", "A", "B"]))
    assert order(conn) == ["C", "A", "B"]


def test_import_keeps_app_order_and_slots_in_new_rows(client, conn, tmp_path):
    sync_big_board(board(tmp_path, ["A", "B", "C", "D"]))
    client.post("/api/bigboard/move", json={"rank": 4, "to_rank": 1})  # D A B C

    # In the sheet (still old order) you add X after B, Y at the top, and delete C.
    result = sync_big_board(board(tmp_path, ["Y", "A", "B", "X", "D"]))
    assert order(conn) == ["Y", "D", "A", "B", "X"]
    assert "Kept the order you set in the app" in result["order_note"]
    assert "2 new entries" in result["order_note"]


def test_after_import_sheet_order_applies_again(client, conn, tmp_path):
    sync_big_board(board(tmp_path, ["A", "B", "C"]))
    client.post("/api/bigboard/move", json={"rank": 3, "to_rank": 1})
    sync_big_board(board(tmp_path, ["A", "B", "C"]))
    assert order(conn) == ["C", "A", "B"]
    # The app order has been imported against; a sheet-only reorder now wins.
    sync_big_board(board(tmp_path, ["B", "C", "A"]))
    assert order(conn) == ["B", "C", "A"]


def test_add_entry_in_app(client, conn, tmp_path):
    sync_big_board(board(tmp_path, ["A", "B"]))
    resp = client.post("/api/bigboard/entries", json={"artist": "Artist N", "title": "N", "year": "1999", "rank": 2})
    assert resp.status_code == 200
    assert order(conn) == ["A", "N", "B"]
    assert client.post("/api/bigboard/entries", json={"artist": "The Artist N", "title": "N!"}).status_code == 409
    assert client.post("/api/bigboard/entries", json={"artist": "", "title": "Z"}).status_code == 400
    client.post("/api/bigboard/entries", json={"artist": "Artist Z", "title": "Z"})
    assert order(conn) == ["A", "N", "B", "Z"]


def test_app_added_entry_survives_import_until_sheet_has_it(client, conn, tmp_path):
    album = add_album(conn, "Someone", "Something Else")
    sync_big_board(board(tmp_path, ["A", "B"]))
    client.post("/api/bigboard/entries", json={"artist": "Artist N", "title": "N", "rank": 1, "album_id": album})

    sync_big_board(board(tmp_path, ["A", "B"]))  # sheet not updated yet
    assert order(conn) == ["N", "A", "B"]
    assert conn.execute("SELECT album_id FROM big_board_entries WHERE title = 'N'").fetchone()[0] == album

    sync_big_board(board(tmp_path, ["N", "A", "B"]))  # pasted into the sheet
    assert conn.execute("SELECT added_in_app FROM big_board_entries WHERE title = 'N'").fetchone()[0] == 0
    sync_big_board(board(tmp_path, ["A", "B"]))  # now deleting it from the sheet removes it
    assert order(conn) == ["A", "B"]


def test_export_matches_board_order_and_ownership(client, conn, tmp_path):
    add_album(conn, "Artist B", "B")
    sync_big_board(board(tmp_path, ["A", "B"]))
    client.post("/api/bigboard/move", json={"rank": 2, "to_rank": 1})

    tsv = client.get("/api/bigboard/export").get_data(as_text=True)
    assert tsv.splitlines() == ["Artist B\tB\t1970\tx", "Artist A\tA\t1970\t"]

    resp = client.get("/api/bigboard/export?format=csv")
    assert "attachment" in resp.headers["Content-Disposition"]
    path = tmp_path / "roundtrip.csv"
    path.write_bytes(resp.data)
    sync_big_board(str(path))
    assert order(conn) == ["B", "A"]


def test_reexport_after_display_edit_keeps_link(client, conn, tmp_path):
    album = add_album(conn, "Artist A", "A")
    sync_big_board(board(tmp_path, ["A"]))
    client.put("/api/bigboard/entry/1", json={"title": "A (Deluxe)"})
    # Sheet updated from the export, so it now has the edited title.
    path = tmp_path / "bb.csv"
    path.write_text("Artist A,A (Deluxe),1970,x\n", encoding="utf-8")
    sync_big_board(str(path))
    assert conn.execute("SELECT album_id FROM big_board_entries").fetchone()[0] == album


def test_rejections_follow_an_entry_renamed_via_export(client, conn, tmp_path):
    wrong = add_album(conn, "Artist A", "A")
    sync_big_board(board(tmp_path, ["A"]))
    client.post("/api/bigboard/unmatch", json={"album_id": wrong})
    client.put("/api/bigboard/entry/1", json={"title": "A (Deluxe)"})
    path = tmp_path / "bb.csv"
    path.write_text("Artist A,A (Deluxe),1970,\n", encoding="utf-8")
    sync_big_board(str(path))
    sync_big_board(str(path))
    assert conn.execute("SELECT album_id FROM big_board_entries").fetchone()[0] is None


def test_added_entry_links_to_owned_copy(client, conn, tmp_path):
    album = add_album(conn, "Radiohead", "OK Computer")
    sync_big_board(board(tmp_path, ["A"]))
    data = client.post("/api/bigboard/entries", json={"artist": "Radiohead", "title": "OK Computer"}).get_json()["data"]
    assert data == {"rank": 2, "album_id": album}
