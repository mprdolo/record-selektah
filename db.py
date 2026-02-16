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
    """)

    # Migrations — add columns that may not exist yet
    migrations = [
        ("albums", "master_id_override", "ALTER TABLE albums ADD COLUMN master_id_override INTEGER"),
    ]
    for table, column, sql in migrations:
        try:
            cursor.execute(f"SELECT {column} FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute(sql)

    conn.commit()
    conn.close()
    print(f"Database initialized at {DATABASE_PATH}")


if __name__ == "__main__":
    init_db()
