import csv
import json
import re
from thefuzz import fuzz
from db import get_db_connection
from config import BIG_BOARD_CSV_PATH

# Minimum fuzzy match score to consider a match
MATCH_THRESHOLD = 80


def normalize_for_matching(text):
    """Normalize text for fuzzy matching: lowercase, strip 'the', remove punctuation."""
    if not text:
        return ""
    text = text.lower().strip()
    # Remove leading "the "
    text = re.sub(r"^the\s+", "", text)
    # Remove trailing ", the" (Discogs style)
    text = re.sub(r",\s*the$", "", text)
    # Strip parenthetical disambiguation like " (2)"
    text = re.sub(r"\s*\(\d+\)\s*$", "", text)
    # Remove punctuation
    text = re.sub(r"[^\w\s]", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def read_big_board_csv(csv_path=None):
    """Read the Big Board CSV and return a list of entries with their rank."""
    path = csv_path or BIG_BOARD_CSV_PATH
    entries = []

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row_num, row in enumerate(reader, start=1):
            # Skip empty rows
            if not row or not any(cell.strip() for cell in row[:3]):
                continue

            artist = row[0].strip() if len(row) > 0 else ""
            title = row[1].strip() if len(row) > 1 else ""
            year_str = row[2].strip() if len(row) > 2 else ""
            owned = row[3].strip().lower() if len(row) > 3 else ""

            if not artist or not title:
                continue

            year = None
            if year_str:
                try:
                    year = int(year_str)
                except ValueError:
                    pass

            entries.append({
                "rank": row_num,
                "artist": artist,
                "title": title,
                "year": year,
                "owned": owned == "x",
            })

    return entries


def find_best_match(entry, albums):
    """
    Find the best matching album for a Big Board entry using fuzzy matching.
    Returns (album_row, score) or (None, 0).
    """
    entry_artist = normalize_for_matching(entry["artist"])
    entry_title = normalize_for_matching(entry["title"])

    best_match = None
    best_score = 0

    for album in albums:
        album_artist = normalize_for_matching(album["artist"])
        album_title = normalize_for_matching(album["title"])

        # Score artist and title separately, then combine
        artist_score = fuzz.ratio(entry_artist, album_artist)
        title_score = fuzz.ratio(entry_title, album_title)

        # Also try token_sort_ratio for reordered words
        artist_sort_score = fuzz.token_sort_ratio(entry_artist, album_artist)
        title_sort_score = fuzz.token_sort_ratio(entry_title, album_title)

        # partial_ratio helps when one artist string contains the other
        # (e.g. "Alice Coltrane" vs "Alice Coltrane, Pharoah Sanders, Joe Henderson")
        artist_partial = fuzz.partial_ratio(entry_artist, album_artist)

        # token_set_ratio handles subset matches well
        # (e.g. "Mercy, Mercy, Mercy" vs "Mercy, Mercy, Mercy! - Live At The Club")
        title_set_score = fuzz.token_set_ratio(entry_title, album_title)

        artist_best = max(artist_score, artist_sort_score, artist_partial)
        title_best = max(title_score, title_sort_score, title_set_score)

        # Combined score: weighted average (title matters more for disambiguation)
        combined = (artist_best * 0.4) + (title_best * 0.6)

        if combined > best_score:
            best_score = combined
            best_match = album

    return best_match, best_score


def sync_big_board(csv_path=None, progress_callback=None):
    """
    Import the Big Board CSV and match entries to albums in the database.

    Returns dict with sync results.
    """
    entries = read_big_board_csv(csv_path)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Load all non-removed albums for matching
    cursor.execute(
        "SELECT id, artist, title, release_year, master_year FROM albums WHERE is_removed = 0"
    )
    albums = cursor.fetchall()

    # Snapshot existing entries so we can preserve manual edits and matches
    cursor.execute("SELECT rank, artist, title, year, album_id FROM big_board_entries")
    old_entries = {row["rank"]: dict(row) for row in cursor.fetchall()}

    # Clear existing Big Board entries so re-imports are clean
    cursor.execute("DELETE FROM big_board_entries")

    matched = 0
    unmatched = []
    total = len(entries)

    if progress_callback:
        progress_callback(f"Matching {total} Big Board entries...", 0, total)

    for i, entry in enumerate(entries):
        old = old_entries.get(entry["rank"])

        # Preserve manual field edits: if the old entry's field differs from
        # what the CSV originally had (i.e. user edited it), keep the edited
        # value. We detect this by checking if the old value differs from the
        # new CSV value — if it does and an album_id was set or the text
        # changed, the user likely edited it manually.
        final_artist = entry["artist"]
        final_title = entry["title"]
        final_year = entry["year"]

        if old:
            # If the old entry had a different artist/title/year than what
            # the CSV says now, the user edited it — preserve the edit
            if old["artist"] != entry["artist"]:
                final_artist = old["artist"]
            if old["title"] != entry["title"]:
                final_title = old["title"]
            if old["year"] != entry["year"]:
                final_year = old["year"]

        # Determine album_id: preserve existing manual match, otherwise
        # try fuzzy matching
        album_id = None
        if old and old["album_id"] is not None:
            # Preserve the existing association (manual or auto)
            album_id = old["album_id"]
            matched += 1
        else:
            best_match, score = find_best_match(entry, albums)
            if best_match and score >= MATCH_THRESHOLD:
                album_id = best_match["id"]
                matched += 1
            else:
                unmatched.append({
                    "rank": entry["rank"],
                    "artist": entry["artist"],
                    "title": entry["title"],
                    "year": entry["year"],
                    "owned": entry["owned"],
                    "best_match_score": round(score) if best_match else 0,
                    "best_match": (
                        f"{best_match['artist']} — {best_match['title']}"
                        if best_match
                        else None
                    ),
                })

        cursor.execute(
            """INSERT INTO big_board_entries (rank, artist, title, year, album_id)
               VALUES (?, ?, ?, ?, ?)""",
            (entry["rank"], final_artist, final_title, final_year, album_id),
        )

        if progress_callback and (i + 1) % 50 == 0:
            progress_callback(f"Matched {matched}/{i + 1} entries...", i + 1, total)

    # Log the sync (no longer need unmatched JSON since entries live in their own table)
    cursor.execute(
        """INSERT INTO sync_log (sync_type, albums_added, albums_updated, unmatched_entries, notes)
           VALUES ('big_board', 0, ?, NULL, ?)""",
        (matched, f"{len(unmatched)} unmatched entries"),
    )

    conn.commit()
    conn.close()

    results = {
        "total_entries": total,
        "matched": matched,
        "unmatched_count": len(unmatched),
        "unmatched": unmatched,
    }

    if progress_callback:
        progress_callback(
            f"Done! Matched {matched}/{total} entries. {len(unmatched)} unmatched.",
            total,
            total,
        )

    return results


if __name__ == "__main__":
    def print_progress(msg, current, total):
        print(msg)

    print("Starting Big Board import...")
    try:
        results = sync_big_board(progress_callback=print_progress)
        print(f"\nBig Board import complete!")
        print(f"  Total entries: {results['total_entries']}")
        print(f"  Matched:       {results['matched']}")
        print(f"  Unmatched:     {results['unmatched_count']}")

        if results["unmatched"]:
            print(f"\nUnmatched entries:")
            for u in results["unmatched"]:
                owned_tag = " [OWNED]" if u["owned"] else ""
                best = f" (closest: {u['best_match']}, score={u['best_match_score']})" if u["best_match"] else ""
                print(f"  #{u['rank']:3d}: {u['artist']} — {u['title']} ({u['year']}){owned_tag}{best}")
    except Exception as e:
        print(f"\nImport failed: {e}")
