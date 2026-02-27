import sqlite3
import os
from config import DATABASE_PATH


def get_db_connection():
    """Get a database connection with row factory enabled."""
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        -- The main collection table
        CREATE TABLE IF NOT EXISTS albums (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discogs_release_id INTEGER UNIQUE NOT NULL,
            discogs_master_id INTEGER,
            artist TEXT NOT NULL,
            title TEXT NOT NULL,
            release_year INTEGER,
            master_year INTEGER,
            big_board_year INTEGER,
            cover_image_url TEXT,
            genres TEXT,
            styles TEXT,
            format TEXT,
            big_board_rank INTEGER,
            is_excluded INTEGER DEFAULT 0,
            is_removed INTEGER DEFAULT 0,
            discogs_url TEXT,
            master_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Listening history
        CREATE TABLE IF NOT EXISTS listens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            album_id INTEGER NOT NULL,
            selected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            did_listen INTEGER DEFAULT 0,
            skipped INTEGER DEFAULT 0,
            FOREIGN KEY (album_id) REFERENCES albums(id)
        );

        -- Sync log
        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_type TEXT NOT NULL,
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            albums_added INTEGER DEFAULT 0,
            albums_updated INTEGER DEFAULT 0,
            albums_removed INTEGER DEFAULT 0,
            unmatched_entries TEXT,
            notes TEXT
        );

        -- Settings (key-value store for app config)
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        -- Indexes for common queries
        CREATE INDEX IF NOT EXISTS idx_albums_discogs_release_id
            ON albums(discogs_release_id);
        CREATE INDEX IF NOT EXISTS idx_albums_discogs_master_id
            ON albums(discogs_master_id);
        CREATE INDEX IF NOT EXISTS idx_albums_is_excluded
            ON albums(is_excluded);
        CREATE INDEX IF NOT EXISTS idx_albums_is_removed
            ON albums(is_removed);
        CREATE INDEX IF NOT EXISTS idx_listens_album_id
            ON listens(album_id);
        CREATE INDEX IF NOT EXISTS idx_listens_selected_at
            ON listens(selected_at);

        -- Big Board entries (standalone, linked to albums via FK)
        CREATE TABLE IF NOT EXISTS big_board_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rank INTEGER NOT NULL,
            artist TEXT NOT NULL,
            title TEXT NOT NULL,
            year INTEGER,
            album_id INTEGER,
            FOREIGN KEY (album_id) REFERENCES albums(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_big_board_rank
            ON big_board_entries(rank);
        CREATE INDEX IF NOT EXISTS idx_big_board_album_id
            ON big_board_entries(album_id);
    """)

    # Migrations — add columns that may not exist yet
    migrations = [
        ("albums", "master_id_override", "ALTER TABLE albums ADD COLUMN master_id_override INTEGER"),
        ("albums", "master_year_override", "ALTER TABLE albums ADD COLUMN master_year_override INTEGER"),
    ]
    for table, column, sql in migrations:
        try:
            cursor.execute(f"SELECT {column} FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute(sql)

    # Migrate existing Big Board data into big_board_entries table
    cursor.execute("SELECT COUNT(*) FROM big_board_entries")
    bb_count = cursor.fetchone()[0]
    if bb_count == 0:
        migrated = 0

        # 1. Migrate matched albums (big_board_rank IS NOT NULL) into new table
        cursor.execute(
            """SELECT id, big_board_rank, big_board_year, artist, title
               FROM albums WHERE big_board_rank IS NOT NULL"""
        )
        matched_rows = cursor.fetchall()
        for row in matched_rows:
            cursor.execute(
                """INSERT OR IGNORE INTO big_board_entries (rank, artist, title, year, album_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (row["big_board_rank"], row["artist"], row["title"],
                 row["big_board_year"], row["id"]),
            )
            migrated += cursor.rowcount

        # 2. Migrate unmatched entries from latest sync_log JSON
        cursor.execute(
            """SELECT unmatched_entries FROM sync_log
               WHERE sync_type = 'big_board' AND unmatched_entries IS NOT NULL
               ORDER BY id DESC LIMIT 1"""
        )
        log_row = cursor.fetchone()
        if log_row and log_row["unmatched_entries"]:
            import json as _json
            unmatched = _json.loads(log_row["unmatched_entries"])
            for u in unmatched:
                cursor.execute(
                    """INSERT OR IGNORE INTO big_board_entries (rank, artist, title, year, album_id)
                       VALUES (?, ?, ?, ?, NULL)""",
                    (u["rank"], u["artist"], u["title"], u.get("year")),
                )
                migrated += cursor.rowcount

        # 3. Clear old columns on albums (leave columns in schema)
        if migrated > 0:
            cursor.execute(
                "UPDATE albums SET big_board_rank = NULL, big_board_year = NULL"
            )
            print(f"Migrated {migrated} Big Board entries to big_board_entries table")

    conn.commit()
    conn.close()
    print(f"Database initialized at {DATABASE_PATH}")


if __name__ == "__main__":
    init_db()
