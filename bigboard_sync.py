import csv
import re
import unicodedata
from thefuzz import fuzz
from db import get_db_connection
from config import BIG_BOARD_CSV_PATH

# Minimum fuzzy match score to consider a match
MATCH_THRESHOLD = 80


def normalize_for_matching(text):
    """Normalize text for fuzzy matching: lowercase, strip 'the', remove punctuation."""
    if not text:
        return ""
    # Fold accents so "João" matches "Joao"
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    # Remove leading "the "
    text = re.sub(r"^the\s+", "", text)
    # Remove trailing ", the" (Discogs style)
    text = re.sub(r",\s*the$", "", text)
    # Strip parenthetical disambiguation like " (2)"
    text = re.sub(r"\s*\(\d+\)\s*$", "", text)
    # Treat "&" and "and" the same
    text = text.replace("&", " and ")
    # Separators become spaces ("Getz/Gilberto", "12-String"); other
    # punctuation is dropped ("Don't" -> "dont")
    text = re.sub(r"[-/_]", " ", text)
    text = re.sub(r"[^\w\s]", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Discogs credits compilations to "Various"; lists often say "Various Artists"
    if text == "various artists":
        text = "various"
    return text


def read_big_board_csv(csv_path=None):
    """Read the Big Board CSV and return a list of entries with their rank."""
    path = csv_path or BIG_BOARD_CSV_PATH
    entries = []

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            # Skip empty rows
            if not row or not any(cell.strip() for cell in row[:3]):
                continue

            artist = row[0].strip() if len(row) > 0 else ""
            title = row[1].strip() if len(row) > 1 else ""
            year_str = row[2].strip() if len(row) > 2 else ""
            owned = row[3].strip().lower() if len(row) > 3 else ""

            if not artist or not title:
                continue
            # The README and sample file start with an "Artist,Title,..."
            # header; don't import it as the #1 album.
            if not entries and artist.lower() == "artist" and title.lower() == "title":
                continue

            year = None
            if year_str:
                try:
                    year = int(year_str)
                except ValueError:
                    pass

            entries.append({
                "rank": len(entries) + 1,
                "artist": artist,
                "title": title,
                "year": year,
                "owned": owned == "x",
            })

    return entries


# Minimum score each of artist and title must reach on its own. Without this,
# a perfect title could carry a completely different artist (or vice versa)
# over the threshold -- e.g. "Television Personalities / ...Love It" matching
# "Love / Love".
MIN_ARTIST_SCORE = 75
MIN_TITLE_SCORE = 85

# Score given when one name is contained in the other (see _field_score).
SUBSET_SCORE = 90

# Tokens that identify one volume/part of a series ("Led Zeppelin II" vs
# "III", "Pretenders" vs "Pretenders II", "Neu!" vs "Neu! '75").
_ROMAN_NUMERALS = {"ii", "iii", "iv", "vi", "vii", "viii", "ix", "xi", "xii"}


def _series_markers(text):
    return {t for t in text.split() if t.isdigit() or t in _ROMAN_NUMERALS}


def _different_volumes(a, b):
    """True if two titles look like different entries in the same series."""
    ma, mb = _series_markers(a), _series_markers(b)
    if ma == mb:
        return False
    if ma and mb:
        return True
    # Only one side has a number: different records if that's the only
    # difference ("Pretenders" vs "Pretenders II"), but not when the number is
    # just extra detail ("Untitled" vs "Untitled (Led Zeppelin IV)").
    strip = lambda t: [w for w in t.split() if w not in ma | mb]
    return strip(a) == strip(b)


def _is_leading_subset(short, long):
    """True if the shorter string's words are the first words of the longer."""
    short_t, long_t = short.split(), long.split()
    if len(short_t) > len(long_t):
        short_t, long_t = long_t, short_t
    return bool(short_t) and long_t[: len(short_t)] == short_t


def _is_word_subset(a, b):
    """True if every word of the shorter string appears as a word in the longer."""
    ta, tb = a.split(), b.split()
    short_t, long_t = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return bool(short_t) and set(short_t) <= set(long_t)


def _is_phrase_subset(a, b):
    """True if the shorter string appears, word for word and in order, in the longer."""
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return bool(short) and f" {short} " in f" {long} "


def _field_score(a, b, contained):
    """Similarity of two normalized strings, 0-100.

    Containment counts as a strong match ("Eno" vs "Brian Eno", "At Fillmore
    East" vs "The Allman Brothers Band At Fillmore East"), but only on whole
    words, so a short word that merely appears inside a longer name ("Love"
    inside "...Just Love It") or a prefix of another word ("Gil" inside
    "Gilberto") doesn't count.
    """
    if not a or not b:
        return 0
    score = max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b))
    if contained(a, b):
        score = max(score, SUBSET_SCORE)
    return score


def _title_contained(a, b):
    words = len((a if len(a) <= len(b) else b).split())
    return (
        _is_leading_subset(a, b)
        or (words >= 2 and _is_phrase_subset(a, b))
        or (words >= 3 and _is_word_subset(a, b))
    )


def score_match(entry_artist, entry_title, album_artist, album_title):
    """Score how well a normalized Big Board entry matches a normalized album."""
    # Artist credits get listed in any order ("Yano Akiko" vs "Akiko Yano",
    # "John Mayall & the Bluesbreakers with Eric Clapton" vs "John Mayall, Eric
    # Clapton"), so any word-for-word containment counts.
    artist_score = _field_score(entry_artist, album_artist, _is_word_subset)
    # Title containment is stricter: leading words ("Mercy Mercy Mercy" vs
    # "Mercy Mercy Mercy Live At The Club"), a 2+ word phrase ("At Fillmore
    # East"), or 3+ words in any order ("Modern Sounds in Country Music" vs
    # "...Country and Western Music"). A lone word or a pair of common words
    # inside a longer title is usually a coincidence ("War" vs "War Ina
    # Babylon", "Black Sabbath" vs "Blue Sabbath, Black Fiji").
    title_score = _field_score(entry_title, album_title, _title_contained)

    if _different_volumes(entry_title, album_title):
        return 0
    if artist_score < MIN_ARTIST_SCORE or title_score < MIN_TITLE_SCORE:
        return 0

    # Weighted average (title matters more for disambiguation)
    return (artist_score * 0.4) + (title_score * 0.6)


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
        combined = score_match(
            entry_artist,
            entry_title,
            normalize_for_matching(album["artist"]),
            normalize_for_matching(album["title"]),
        )
        if combined > best_score:
            best_score = combined
            best_match = album

    return best_match, best_score


def _key_text(text):
    """Normalization used for entry identity keys.

    Deliberately frozen: remembered rejections are stored under these keys,
    so changing this would silently forget them. Improve
    normalize_for_matching instead.
    """
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"^the\s+", "", text)
    text = re.sub(r",\s*the$", "", text)
    text = re.sub(r"\s*\(\d+\)\s*$", "", text)
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def entry_key(artist, title):
    """Stable identity for a Big Board entry across re-syncs."""
    return (_key_text(artist), _key_text(title))


def load_rejected_matches(cursor):
    """Return {entry_key: {album_id, ...}} of links the user has rejected."""
    cursor.execute(
        "SELECT entry_artist_key, entry_title_key, album_id FROM big_board_rejected_matches"
    )
    rejected = {}
    for row in cursor.fetchall():
        key = (row["entry_artist_key"], row["entry_title_key"])
        rejected.setdefault(key, set()).add(row["album_id"])
    return rejected


def reject_match(cursor, artist, title, album_id):
    """Remember that this entry must never be auto-linked to this album again."""
    artist_key, title_key = entry_key(artist, title)
    cursor.execute(
        """INSERT OR IGNORE INTO big_board_rejected_matches
           (entry_artist_key, entry_title_key, album_id) VALUES (?, ?, ?)""",
        (artist_key, title_key, album_id),
    )


def unreject_match(cursor, artist, title, album_id):
    """Forget a past rejection (the user has now linked this pair by hand)."""
    artist_key, title_key = entry_key(artist, title)
    cursor.execute(
        """DELETE FROM big_board_rejected_matches
           WHERE entry_artist_key = ? AND entry_title_key = ? AND album_id = ?""",
        (artist_key, title_key, album_id),
    )


def _app_order_edited(cursor):
    cursor.execute("SELECT value FROM settings WHERE key = 'bigboard_order_edited'")
    row = cursor.fetchone()
    return bool(row and row["value"])


def mark_app_order_edited(cursor):
    """Record that the Big Board order was changed in the app since the last import."""
    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('bigboard_order_edited', '1')"
    )


def _merge_order(csv_entries, old_entries, old_by_key, app_order_edited):
    """
    Decide the Big Board order after an import.

    If you haven't reordered or added anything in the app since the last
    import, the spreadsheet's order is used as-is.

    If you have, your app order wins for every entry that's already on the
    board. Entries that are new in the sheet are slotted in right after the
    entry they follow in the sheet (or at the top if they come first).
    Entries removed from the sheet are dropped, except ones you added in the
    app that haven't made it into the sheet yet.

    Returns (ordered entries, short human-readable note). Each returned entry
    has artist/title/year, source_artist/source_title, key and added_in_app.
    """
    for e in csv_entries:
        e["source_artist"], e["source_title"] = e["artist"], e["title"]
        old = old_by_key.get(entry_key(e["artist"], e["title"]))
        e["key"] = old["key"] if old else entry_key(e["artist"], e["title"])

    if not app_order_edited:
        return csv_entries, "Order taken from the spreadsheet."

    csv_by_key = {e["key"]: e for e in csv_entries}
    ordered = []
    placed = set()
    for old in old_entries:
        if old["key"] in placed:
            continue
        if old["key"] in csv_by_key:
            ordered.append(csv_by_key[old["key"]])
            placed.add(old["key"])
        elif old["added_in_app"]:
            ordered.append({
                "artist": old["artist"], "title": old["title"], "year": old["year"],
                "owned": False, "source_artist": old["key_artist"],
                "source_title": old["key_title"], "key": old["key"], "added_in_app": True,
            })
            placed.add(old["key"])

    new_count = 0
    previous_key = None
    for e in csv_entries:
        if e["key"] not in placed:
            at = 0
            if previous_key is not None:
                at = next(i for i, o in enumerate(ordered) if o["key"] == previous_key) + 1
            ordered.insert(at, e)
            placed.add(e["key"])
            new_count += 1
        previous_key = e["key"]

    note = "Kept the order you set in the app"
    if new_count:
        note += f" and slotted in {new_count} new entr{'y' if new_count == 1 else 'ies'} from the sheet"
    return ordered, note + "."


def _get_active_csv_path():
    """Return CSV path from DB settings if set, otherwise fall back to config."""
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = 'bigboard_csv_path'")
            row = cursor.fetchone()
            if row and row["value"]:
                return row["value"]
        finally:
            conn.close()
    except Exception:
        pass
    return BIG_BOARD_CSV_PATH


def sync_big_board(csv_path=None, progress_callback=None):
    """
    Import the Big Board CSV and match entries to albums in the database.

    Returns dict with sync results.
    """
    entries = read_big_board_csv(csv_path or _get_active_csv_path())

    # Deduplicate entries by normalized artist+title (CSV may have repeated rows)
    seen = set()
    deduped_entries = []
    duplicates_skipped = 0
    for entry in entries:
        key = entry_key(entry["artist"], entry["title"])
        if key in seen:
            duplicates_skipped += 1
            continue
        seen.add(key)
        # Re-assign sequential rank after deduplication
        entry["rank"] = len(deduped_entries) + 1
        deduped_entries.append(entry)
    entries = deduped_entries

    conn = get_db_connection()
    cursor = conn.cursor()

    # Load all non-removed albums for matching
    cursor.execute(
        "SELECT id, artist, title, release_year, master_year FROM albums WHERE is_removed = 0"
    )
    albums = cursor.fetchall()
    live_album_ids = {album["id"] for album in albums}

    # Snapshot existing entries so we can preserve manual matches, via links
    # and the order you set in the app. Key by the entry's CSV text
    # (source_*), not its displayed text, so an entry edited in the app still
    # finds its old match; the displayed text is also indexed so a sheet that
    # was updated from the app's export still lines up.
    cursor.execute(
        """SELECT rank, artist, title, year, album_id, via_album_id, added_in_app,
                  COALESCE(source_artist, artist) AS key_artist,
                  COALESCE(source_title, title) AS key_title
           FROM big_board_entries ORDER BY rank"""
    )
    old_entries = [dict(row) for row in cursor.fetchall()]
    old_by_key = {}
    for old in old_entries:
        old["key"] = entry_key(old["key_artist"], old["key_title"])
        # Keep the first (best-ranked) entry per key
        old_by_key.setdefault(old["key"], old)
    for old in old_entries:
        old_by_key.setdefault(entry_key(old["artist"], old["title"]), old)

    entries, order_note = _merge_order(entries, old_entries, old_by_key, _app_order_edited(cursor))

    # Load matches the user explicitly rejected (unlinked, or relinked to a
    # different album) so re-syncs never reapply the same wrong association.
    rejected_by_key = load_rejected_matches(cursor)

    # Clear existing Big Board entries so re-imports are clean
    cursor.execute("DELETE FROM big_board_entries")

    total = len(entries)
    if progress_callback:
        progress_callback(f"Matching {total} Big Board entries...", 0, total)

    keys = [e["key"] for e in entries]
    album_ids = [None] * total
    # Each album can only be linked to one entry.
    claimed_album_ids = set()

    # Pass 1: keep every existing link (manual or automatic) whose album is
    # still in the collection and hasn't been rejected. Doing this before any
    # fuzzy matching means a link you made by hand can't be taken away by a
    # higher-ranked entry that happens to fuzzy-match the same album.
    for i, key in enumerate(keys):
        old = old_by_key.get(key)
        if (
            old
            and old["album_id"] in live_album_ids
            and old["album_id"] not in claimed_album_ids
            and old["album_id"] not in rejected_by_key.get(key, set())
        ):
            album_ids[i] = old["album_id"]
            claimed_album_ids.add(old["album_id"])

    # Pass 2: fuzzy-match the remaining entries, in rank order, against albums
    # nobody has claimed and this entry hasn't rejected.
    unmatched = []
    for i, entry in enumerate(entries):
        if album_ids[i] is None:
            excluded = claimed_album_ids | rejected_by_key.get(keys[i], set())
            candidates = [a for a in albums if a["id"] not in excluded]
            best_match, score = find_best_match(entry, candidates)
            if best_match and score >= MATCH_THRESHOLD:
                album_ids[i] = best_match["id"]
                claimed_album_ids.add(best_match["id"])
            else:
                unmatched.append({
                    "rank": entry["rank"],
                    "artist": entry["artist"],
                    "title": entry["title"],
                    "year": entry["year"],
                    "owned": entry["owned"],
                    "best_match_score": round(score),
                    "best_match": (
                        f"{best_match['artist']} — {best_match['title']}" if best_match else None
                    ),
                })

        if progress_callback and (i + 1) % 50 == 0:
            progress_callback(f"Matched {i + 1 - len(unmatched)}/{i + 1} entries...", i + 1, total)

    for i, entry in enumerate(entries):
        old = old_by_key.get(keys[i])
        via_album_id = old["via_album_id"] if old else None
        # The CSV is the source of truth for artist/title/year. Entries added
        # in the app that aren't in the sheet yet keep their own values.
        cursor.execute(
            """INSERT INTO big_board_entries
               (rank, artist, title, year, album_id, via_album_id,
                source_artist, source_title, added_in_app)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                i + 1, entry["artist"], entry["title"], entry["year"],
                album_ids[i], via_album_id, entry["source_artist"], entry["source_title"],
                1 if entry.get("added_in_app") else 0,
            ),
        )

    # If an entry is now known by different text (you edited it in the app and
    # pasted the export into the sheet), carry its remembered rejections over
    # to the new text so they keep applying on later imports.
    for i, entry in enumerate(entries):
        new_key = entry_key(entry["source_artist"], entry["source_title"])
        if new_key != keys[i]:
            cursor.execute(
                """UPDATE OR IGNORE big_board_rejected_matches
                   SET entry_artist_key = ?, entry_title_key = ?
                   WHERE entry_artist_key = ? AND entry_title_key = ?""",
                (*new_key, *keys[i]),
            )

    # The app's order is now in sync with this import.
    cursor.execute("DELETE FROM settings WHERE key = 'bigboard_order_edited'")

    matched = total - len(unmatched)

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
        "duplicates_skipped": duplicates_skipped,
        "order_note": order_note,
    }

    dupe_note = f" ({duplicates_skipped} duplicates skipped.)" if duplicates_skipped else ""
    if progress_callback:
        progress_callback(
            f"Done! Matched {matched}/{total} entries. {len(unmatched)} unmatched.{dupe_note}",
            total,
            total,
        )

    return results


if __name__ == "__main__":
    import sys
    import io

    # Ensure stdout can handle Unicode on Windows
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

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
