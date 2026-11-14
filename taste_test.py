"""
Taste test: pick between two Big Board albums, and nudge the board toward
your answer.

If you pick the album that's already ranked higher, nothing moves. If you
pick the lower-ranked one, it climbs part of the way toward the other one,
never past it, by an amount that grows with the gap but more slowly than
the gap itself (square root), so one answer is a nudge, not a verdict:

    gap   1 ->  no move (it's already right below)
    gap   4 ->  3 places   (stops just below the other album)
    gap  10 ->  5 places
    gap  50 -> 11 places
    gap 200 -> 22 places
    gap 600 -> 37 places

Pairs are random: any two albums on the board.

Picking the same album again next time moves it again, so a preference you
keep expressing adds up, while a one-off whim barely registers.
"""
import math
import random

from bigboard_ranks import move_entry
from bigboard_sync import mark_app_order_edited

PAIRS_PER_ROUND = 10

# boost = ceil(BOOST_FACTOR * sqrt(gap)), capped so it lands just below the
# album it beat. Raise it to make each answer count for more.
BOOST_FACTOR = 1.5

def boost_for_gap(gap):
    """How many places the lower-ranked album climbs when it wins."""
    if gap <= 1:
        return 0
    return min(gap - 1, math.ceil(BOOST_FACTOR * math.sqrt(gap)))


def pick_pairs(cursor, n=PAIRS_PER_ROUND, rng=random):
    """Pick n pairs of Big Board entries; no album appears twice in a round."""
    cursor.execute(
        """SELECT bb.id, bb.rank, bb.artist, bb.title, bb.year,
                  COALESCE(a.cover_image_url, va.cover_image_url) AS cover_image_url,
                  COALESCE(a.genres, va.genres) AS genres,
                  (a.id IS NOT NULL OR va.id IS NOT NULL) AS owned
           FROM big_board_entries bb
           LEFT JOIN albums a ON a.id = bb.album_id AND a.is_removed = 0
           LEFT JOIN albums va ON va.id = bb.via_album_id AND va.is_removed = 0
           ORDER BY bb.rank"""
    )
    entries = [dict(r) for r in cursor.fetchall()]
    # Fully random pairs: any two albums on the board, no album twice per round.
    rng.shuffle(entries)
    pairs = []
    for i in range(0, min(n * 2, len(entries) - len(entries) % 2), 2):
        pairs.append([entries[i], entries[i + 1]])
    return pairs


def record_vote(cursor, winner_id, loser_id):
    """
    Apply one answer. Returns a dict describing what happened, or None if
    either entry no longer exists.
    """
    cursor.execute(
        "SELECT id, rank, artist, title FROM big_board_entries WHERE id IN (?, ?)",
        (winner_id, loser_id),
    )
    rows = {r["id"]: dict(r) for r in cursor.fetchall()}
    if winner_id not in rows or loser_id not in rows or winner_id == loser_id:
        return None
    winner, loser = rows[winner_id], rows[loser_id]

    new_rank = winner["rank"]
    if winner["rank"] > loser["rank"]:
        gap = winner["rank"] - loser["rank"]
        new_rank = winner["rank"] - boost_for_gap(gap)
        if new_rank != winner["rank"]:
            move_entry(cursor, winner["id"], winner["rank"], new_rank)
            mark_app_order_edited(cursor)

    cursor.execute(
        """INSERT INTO taste_test_votes
           (winner_artist, winner_title, loser_artist, loser_title,
            winner_rank_before, loser_rank_before, winner_rank_after)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            winner["artist"], winner["title"], loser["artist"], loser["title"],
            winner["rank"], loser["rank"], new_rank,
        ),
    )
    return {
        "winner_rank_before": winner["rank"],
        "winner_rank_after": new_rank,
        # The winner always stops below the loser, so the loser never moves.
        "loser_rank": loser["rank"],
        "moved": winner["rank"] - new_rank,
    }
