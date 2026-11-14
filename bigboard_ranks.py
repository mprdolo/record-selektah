"""Moving Big Board entries to a new rank, shared by drag-to-reorder and the
taste test."""


def shift_ranks(cursor, first, last, delta):
    """Shift ranks first..last (inclusive) by delta without tripping the
    unique index on rank: park them at negative ranks first."""
    cursor.execute(
        "UPDATE big_board_entries SET rank = -(rank + ?) WHERE rank BETWEEN ? AND ?",
        (delta, first, last),
    )
    cursor.execute("UPDATE big_board_entries SET rank = -rank WHERE rank < 0")


def move_entry(cursor, entry_id, from_rank, to_rank):
    """Move one entry from from_rank to to_rank, shifting the ones between."""
    if to_rank == from_rank:
        return
    cursor.execute("UPDATE big_board_entries SET rank = 0 WHERE id = ?", (entry_id,))
    if to_rank < from_rank:
        shift_ranks(cursor, to_rank, from_rank - 1, +1)
    else:
        shift_ranks(cursor, from_rank + 1, to_rank, -1)
    cursor.execute("UPDATE big_board_entries SET rank = ? WHERE id = ?", (to_rank, entry_id))
