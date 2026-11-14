"""Fuzzy matching between Big Board entries and collection albums.

Most cases come from real mismatches the old matcher made, which had to be
undone by hand after every re-sync.
"""
import pytest

from bigboard_sync import MATCH_THRESHOLD, find_best_match, normalize_for_matching


def score(entry_artist, entry_title, album_artist, album_title):
    _, s = find_best_match(
        {"artist": entry_artist, "title": entry_title},
        [{"id": 1, "artist": album_artist, "title": album_title}],
    )
    return s


@pytest.mark.parametrize(
    "entry, album",
    [
        (("George Michael", "Faith"), ("The Cure", "Faith")),
        (("Nina Simone", "In Concert"), ("Thelonious Monk", "Big Band And Quartet In Concert")),
        (("Neu!", "Neu!"), ("Neu!", "Neu! '75")),
        (("Gilberto Gil", "Gilberto Gil"), ("Astrud Gilberto", "The Astrud Gilberto Album")),
        (("Led Zeppelin", "Led Zeppelin II"), ("Led Zeppelin", "Led Zeppelin III")),
        (("Black Sabbath", "Black Sabbath"), ("Blue Sabbath Black Fiji, Ajilvsga", "Blue Sabbath, Black Fiji / Ajilvsga")),
        (("Television Personalities", "...And Don't the Kids Just Love It"), ("Love", "Love")),
        (("Various Artists", "Precious Lord: New Recordings of the Great Songs of Thomas A. Dorsey"), ("Various", "Jeff Recordings")),
        (("John Fahey", "The Transfiguration of Blind Joe Death"), ("John Fahey", "Volume 1 / Blind Joe Death")),
        (("Donny Hathaway", "Everything Is Everything"), ("Rasa (9)", "Everything You See Is Me")),
        (("Glenn Branca", "Symphony No. 1 (Tonal Plexus)"), ("Dawn Penn", "No No No")),
        (("U2", "War"), ("Max Romeo, The Upsetters", "War Ina Babylon")),
        (("The Impressions", "The Impressions"), ("The Impressions", "The Best Impressions... Curtis, Sam & Fred")),
        (("Grandmaster Flash & the Furious Five", "The Message"), ("G&D", "The Message Uni Versa")),
        (("Rain Parade", "Emergency Third Rail Power Trip"), ("Portishead", "Third")),
        (("Roberto Roena y Su Apollo Sound", "6"), ("Bud Powell", "Broadcast Performances 1953, Vol. 1 Of 6 Volumes")),
        (("The Pretenders", "Pretenders"), ("The Pretenders", "Pretenders II")),
        (("Dusty Springfield", "Stay Awhile/I Only Want to Be with You"), ("The Magnetic Fields", "i")),
        (("John Coltrane", "Olé Coltrane"), ("John Coltrane", "Coltrane Time")),
    ],
)
def test_wrong_matches_are_rejected(entry, album):
    assert score(*entry, *album) < MATCH_THRESHOLD


@pytest.mark.parametrize(
    "entry, album",
    [
        (("Radiohead", "OK Computer"), ("Radiohead", "OK Computer")),
        (("The Beatles", "Abbey Road"), ("Beatles, The", "Abbey Road")),
        (("Alice Coltrane", "Journey in Satchidananda"), ("Alice Coltrane, Pharoah Sanders, Joe Henderson", "Journey In Satchidananda")),
        (("Cannonball Adderley", "Mercy, Mercy, Mercy"), ("Cannonball Adderley", "Mercy, Mercy, Mercy! - Live At \"The Club\"")),
        (("James Brown", "The James Brown Show (Live at the Apollo)"), ("James Brown", "'Live' At The Apollo")),
        (("Led Zeppelin", "Untitled (Led Zeppelin IV)"), ("Led Zeppelin", "Untitled")),
        (("Yano Akiko", "Tadaima"), ("Akiko Yano, Akiko Yano", "Tadaima. = ただいま。")),
        (("Smokey Robinson & the Miracles", "Going to a Go-Go"), ("The Miracles", "Going To A Go-Go")),
        (("John Lennon / Plastic Ono Band", "Plastic Ono Band"), ("John Lennon, The Plastic Ono Band", "John Lennon / Plastic Ono Band")),
        (("Gerry Mulligan", "Meets Ben Webster"), ("Gerry Mulligan, Ben Webster", "Gerry Mulligan Meets Ben Webster")),
        (("Stan Getz / Joao Gilberto", "Getz/Gilberto"), ("Stan Getz, João Gilberto, Antonio Carlos Jobim", "Getz / Gilberto")),
        (("Eno", "Another Green World"), ("Brian Eno", "Another Green World")),
        (("The Allman Brothers Band", "At Fillmore East"), ("The Allman Brothers Band", "The Allman Brothers Band At Fillmore East")),
        (("Leo Kottke", "6 and 12 String Guitar"), ("Leo Kottke", "6- And 12-String Guitar")),
        (("John Mayall & the Bluesbreakers with Eric Clapton", "Blues Breakers"), ("John Mayall, Eric Clapton", "Blues Breakers")),
        (("Ray Charles", "Modern Sounds in Country Music"), ("Ray Charles", "Modern Sounds In Country And Western Music")),
        (("Astrud Gilberto", "The Astrud Gilberto Album"), ("Astrud Gilberto", "The Astrud Gilberto Album")),
        (("Neu!", "Neu! 75"), ("Neu!", "Neu! '75")),
    ],
)
def test_right_matches_are_accepted(entry, album):
    assert score(*entry, *album) >= MATCH_THRESHOLD


def test_best_match_prefers_closest_album():
    albums = [
        {"id": 1, "artist": "Led Zeppelin", "title": "Led Zeppelin III"},
        {"id": 2, "artist": "Led Zeppelin", "title": "Led Zeppelin II"},
    ]
    match, _ = find_best_match({"artist": "Led Zeppelin", "title": "Led Zeppelin II"}, albums)
    assert match["id"] == 2


def test_no_match_returns_none():
    match, s = find_best_match({"artist": "Nobody", "title": "Nothing"}, [{"id": 1, "artist": "Radiohead", "title": "Kid A"}])
    assert match is None and s == 0


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("The Beatles", "beatles"),
        ("Beatles, The", "beatles"),
        ("Prince (2)", "prince"),
        ("Simon & Garfunkel", "simon and garfunkel"),
        ("João Gilberto", "joao gilberto"),
        ("Getz/Gilberto", "getz gilberto"),
        ("Don't Stop", "dont stop"),
        ("Various Artists", "various"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize(raw, expected):
    assert normalize_for_matching(raw) == expected
