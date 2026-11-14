"""Taste test: pick one of two albums and nudge the Big Board."""
import random

import pytest

from bigboard_sync import sync_big_board
from conftest import write_csv
from taste_test import boost_for_gap, pick_pairs


def order(conn):
    return [r[0] for r in conn.execute("SELECT title FROM big_board_entries ORDER BY rank")]


def entry_id(conn, title):
    return conn.execute("SELECT id FROM big_board_entries WHERE title = ?", (title,)).fetchone()[0]


def rank_of(conn, title):
    return conn.execute("SELECT rank FROM big_board_entries WHERE title = ?", (title,)).fetchone()[0]


@pytest.fixture
def hundred(conn, tmp_path):
    sync_big_board(write_csv(tmp_path / "bb.csv", [(f"Artist {i}", f"T{i}", 1970) for i in range(1, 101)]))


@pytest.mark.parametrize("gap, boost", [(1, 0), (2, 1), (4, 3), (10, 5), (50, 11), (200, 22), (600, 37)])
def test_boost_grows_with_gap_but_gradually(gap, boost):
    assert boost_for_gap(gap) == boost


def test_boost_never_reaches_the_other_album():
    for gap in range(1, 1000):
        assert boost_for_gap(gap) <= max(0, gap - 1)


def test_higher_ranked_winner_changes_nothing(client, conn, hundred):
    before = order(conn)
    resp = client.post("/api/taste-test/vote", json={"winner_id": entry_id(conn, "T5"), "loser_id": entry_id(conn, "T60")})
    assert resp.get_json()["data"]["moved"] == 0
    assert order(conn) == before
    assert conn.execute("SELECT COUNT(*) FROM taste_test_votes").fetchone()[0] == 1


def test_lower_ranked_winner_climbs_partway(client, conn, hundred):
    # T60 beats T10: gap 50 -> climbs 11 places, to #49.
    data = client.post("/api/taste-test/vote", json={"winner_id": entry_id(conn, "T60"), "loser_id": entry_id(conn, "T10")}).get_json()["data"]
    assert data == {"winner_rank_before": 60, "winner_rank_after": 49, "loser_rank": 10, "moved": 11}
    assert rank_of(conn, "T60") == 49
    assert rank_of(conn, "T49") == 50  # everyone in between slides down one
    assert rank_of(conn, "T10") == 10
    assert sorted(r[0] for r in conn.execute("SELECT rank FROM big_board_entries")) == list(range(1, 101))


def test_close_pairs_stop_just_below_the_other_album(client, conn, hundred):
    client.post("/api/taste-test/vote", json={"winner_id": entry_id(conn, "T13"), "loser_id": entry_id(conn, "T10")})
    assert rank_of(conn, "T13") == 11
    client.post("/api/taste-test/vote", json={"winner_id": entry_id(conn, "T13"), "loser_id": entry_id(conn, "T10")})
    assert rank_of(conn, "T13") == 11  # adjacent now: never jumps above


def test_repeated_wins_add_up(client, conn, hundred):
    for _ in range(3):
        client.post("/api/taste-test/vote", json={"winner_id": entry_id(conn, "T100"), "loser_id": entry_id(conn, "T1")})
    assert rank_of(conn, "T100") < 70


def test_vote_marks_app_order_edited(client, conn, hundred, tmp_path):
    client.post("/api/taste-test/vote", json={"winner_id": entry_id(conn, "T60"), "loser_id": entry_id(conn, "T10")})
    # Re-importing the unchanged sheet keeps the taste-test result.
    sync_big_board(write_csv(tmp_path / "bb.csv", [(f"Artist {i}", f"T{i}", 1970) for i in range(1, 101)]))
    assert rank_of(conn, "T60") == 49


def test_vote_validation(client, conn, hundred):
    assert client.post("/api/taste-test/vote", json={}).status_code == 400
    assert client.post("/api/taste-test/vote", json={"winner_id": 99999, "loser_id": entry_id(conn, "T1")}).status_code == 404


def test_pairs_are_ten_distinct_random_pairs(conn, hundred):
    pairs = pick_pairs(conn.cursor(), 10, rng=random.Random(1))
    assert len(pairs) == 10
    ids = [e["id"] for p in pairs for e in p]
    assert len(set(ids)) == 20


def test_pairs_endpoint(client, conn, hundred):
    data = client.get("/api/taste-test/pairs").get_json()["data"]
    assert len(data["pairs"]) == 10
    assert {"id", "rank", "artist", "title", "cover_image_url", "genres", "owned"} <= set(data["pairs"][0][0])


def test_pairs_need_a_board(client):
    assert client.get("/api/taste-test/pairs").status_code == 400
