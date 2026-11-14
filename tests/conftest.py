import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    """A fresh, initialised database for each test (never touches data/)."""
    monkeypatch.setattr(db, "DATABASE_PATH", str(tmp_path / "test.db"))
    db.init_db()
    connection = db.get_db_connection()
    yield connection
    connection.close()


@pytest.fixture
def client(conn):
    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


_next_release_id = [1000]


def add_album(conn, artist, title, release_id=None, **extra):
    """Insert an album and return its id."""
    if release_id is None:
        _next_release_id[0] += 1
        release_id = _next_release_id[0]
    cols = {
        "discogs_release_id": release_id,
        "artist": artist,
        "title": title,
        "genres": json.dumps(extra.pop("genres", [])),
        "styles": json.dumps([]),
        **extra,
    }
    cur = conn.execute(
        f"INSERT INTO albums ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        list(cols.values()),
    )
    conn.commit()
    return cur.lastrowid


def write_csv(path, rows):
    """rows: list of (artist, title, year) tuples, in rank order."""
    lines = ["Artist,Title,Year,Owned"] + [f"{a},{t},{y or ''}," for a, t, y in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def links(conn):
    """{rank: album_id} for every Big Board entry."""
    return dict(conn.execute("SELECT rank, album_id FROM big_board_entries ORDER BY rank"))
