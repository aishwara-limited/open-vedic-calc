"""Ashtakoota tables pinned against the classical rule, not against the code.

Six Ashtakoota inputs are fixed here: the Nadi of each nakshatra, the Gana of
each nakshatra, the Tara (Dina) koota rule, and the Vasya, Yoni and Gana point
tables.  The authority for the first three is
the marriage chapter (Vivaha-prakarana) of Muhurta Chintamani (Daivajna Rama,
1600 CE), which is where the eight-koota scheme and its 36 points come from;
BPHS does not define the koota tables.  The expected values below are written
out BY HAND from that rule -- the nakshatra lists are typed in as the classical
groupings, never derived from ``bphs_core.compat`` -- so a table in the engine
that drifts from the classical one reds here instead of agreeing with itself.

* Nadi.  The 27 nakshatras run through the three nadis in a serpentine order
  (Aadi, Madhya, Antya, Antya, Madhya, Aadi, repeated), not a plain cycle of
  three.  Same nadi scores 0 of 8 (nadi dosha); different nadis score 8.
* Gana.  Nine nakshatras per gana.  Uttara Bhadrapada is manushya (the three
  Purvas and three Uttaras are all manushya), not deva.
* Tara.  Count inclusively from one partner's star to the other's and divide by
  nine; only the remainders 3 (Vipat), 5 (Pratyak) and 7 (Vadha) are
  inauspicious.  The remainder 1 (Janma: the same star, the 10th, the 19th) is
  not.  Each auspicious direction is worth 1.5 points, so 3 is the maximum.

The Vasya, Yoni and Gana POINT tables are the North Indian tables published by
saravali.de, as transcribed in PyJHora 4.8.7
(``jhora/horoscope/match/compatibility.py``: ``VasiyaArray``, ``YoniArray``,
``gana_array``), each with the BRIDE's group on the rows and the GROOM's on the
columns.  They are typed in below cell by cell; a separate test checks the
hand-typed copy against that transcription, so a typing slip here is caught by
something other than the engine.  The vasya group follows the Moon's sign and,
for Sagittarius (0-15 nara, 15-30 chatushpada) and Capricorn (0-15
chatushpada, 15-30 jalachara), the half of the sign it occupies; every one of
the 108 nakshatra padas is pinned to its group by hand.  The yoni animal of
each nakshatra is that table's; the genders, which the table does not carry,
are the common North Indian list of the same family.

Direction: ``/v1/compat`` reads ``person_a`` as the groom and ``person_b`` as
the bride, and so do the scoring functions (first argument groom).

The route tests drive ``/v1/compat`` and ``/v1/profile`` with synthetic births
whose Moon sits near the MIDDLE of the named nakshatra (at least 5 degrees from
either edge under both ephemeris runtimes), so the nakshatra itself is not in
doubt and the test measures only the table.  No personal birth data is used.
"""
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("CALC_SERVICE_TOKEN", "test")
os.environ.setdefault("PUBLIC_SOURCE_URL", "https://example.com")

from app.main import app
from bphs_core import compat, utils
from bphs_core.chart import PlanetData


@pytest.fixture(scope="module")
def client():
    # One context-managed client for the module: every request shares a single
    # event loop and its worker-thread pool instead of starting fresh threads
    # per request.
    with TestClient(app, headers={"X-Calc-Service-Token": "test"}) as c:
        yield c

# ---------------------------------------------------------------------------
# Classical tables, typed by hand from the rule (never derived from the engine)
# ---------------------------------------------------------------------------

CLASSICAL_NADI = {
    "Aadi": ("Ashwini", "Ardra", "Punarvasu", "Uttara Phalguni", "Hasta",
             "Jyeshtha", "Mula", "Shatabhisha", "Purva Bhadrapada"),
    "Madhya": ("Bharani", "Mrigashira", "Pushya", "Purva Phalguni", "Chitra",
               "Anuradha", "Purva Ashadha", "Dhanishta", "Uttara Bhadrapada"),
    "Antya": ("Krittika", "Rohini", "Ashlesha", "Magha", "Swati",
              "Vishakha", "Uttara Ashadha", "Shravana", "Revati"),
}

CLASSICAL_GANA = {
    "deva": ("Ashwini", "Mrigashira", "Punarvasu", "Pushya", "Hasta",
             "Swati", "Anuradha", "Shravana", "Revati"),
    "manushya": ("Bharani", "Rohini", "Ardra", "Purva Phalguni",
                 "Uttara Phalguni", "Purva Ashadha", "Uttara Ashadha",
                 "Purva Bhadrapada", "Uttara Bhadrapada"),
    "rakshasa": ("Krittika", "Ashlesha", "Magha", "Chitra", "Vishakha",
                 "Jyeshtha", "Mula", "Dhanishta", "Shatabhisha"),
}

TARA_INAUSPICIOUS_REMAINDERS = {3, 5, 7}

# Vasya points, saravali.de table.  BRIDE on the rows, GROOM on the columns.
VASYA_GROUPS = ("chatushpada", "nara", "jalchar", "vanchar", "keeta")
CLASSICAL_VASYA_POINTS = {
    # bride:        groom: chatushpada nara jalchar vanchar keeta
    "chatushpada": (2.0, 0.5, 1.0, 0.0, 2.0),
    "nara":        (0.5, 2.0, 0.0, 0.0, 0.0),
    "jalchar":     (1.0, 0.0, 2.0, 2.0, 2.0),
    "vanchar":     (0.0, 0.0, 2.0, 2.0, 0.0),
    "keeta":       (1.0, 0.0, 1.0, 0.0, 2.0),
}

# Vasya group of each nakshatra pada (padas 1-4).  "nara/chatushpada" marks the
# one pada that straddles Sagittarius 15 deg (Purva Ashadha 1: 13.33-16.67) and
# "chatushpada/jalchar" the one that straddles Capricorn 15 deg (Shravana 2:
# 13.33-16.67): the first name below 15 deg, the second from 15 deg on.
_C, _N, _J, _V, _K = "chatushpada", "nara", "jalchar", "vanchar", "keeta"
CLASSICAL_PADA_VASYA = {
    "Ashwini":           (_C, _C, _C, _C),        # Aries
    "Bharani":           (_C, _C, _C, _C),        # Aries
    "Krittika":          (_C, _C, _C, _C),        # Aries 1 | Taurus 2-4
    "Rohini":            (_C, _C, _C, _C),        # Taurus
    "Mrigashira":        (_C, _C, _N, _N),        # Taurus 1-2 | Gemini 3-4
    "Ardra":             (_N, _N, _N, _N),        # Gemini
    "Punarvasu":         (_N, _N, _N, _J),        # Gemini 1-3 | Cancer 4
    "Pushya":            (_J, _J, _J, _J),        # Cancer
    "Ashlesha":          (_J, _J, _J, _J),        # Cancer
    "Magha":             (_V, _V, _V, _V),        # Leo
    "Purva Phalguni":    (_V, _V, _V, _V),        # Leo
    "Uttara Phalguni":   (_V, _N, _N, _N),        # Leo 1 | Virgo 2-4
    "Hasta":             (_N, _N, _N, _N),        # Virgo
    "Chitra":            (_N, _N, _N, _N),        # Virgo 1-2 | Libra 3-4
    "Swati":             (_N, _N, _N, _N),        # Libra
    "Vishakha":          (_N, _N, _N, _K),        # Libra 1-3 | Scorpio 4
    "Anuradha":          (_K, _K, _K, _K),        # Scorpio
    "Jyeshtha":          (_K, _K, _K, _K),        # Scorpio
    "Mula":              (_N, _N, _N, _N),        # Sagittarius 0-13.33
    "Purva Ashadha":     (_N + "/" + _C, _C, _C, _C),  # Sagittarius 13.33-26.67
    "Uttara Ashadha":    (_C, _C, _C, _C),        # Sagittarius 1 | Capricorn 2-4
    "Shravana":          (_C, _C + "/" + _J, _J, _J),  # Capricorn 10-23.33
    "Dhanishta":         (_J, _J, _N, _N),        # Capricorn 1-2 | Aquarius 3-4
    "Shatabhisha":       (_N, _N, _N, _N),        # Aquarius
    "Purva Bhadrapada":  (_N, _N, _N, _J),        # Aquarius 1-3 | Pisces 4
    "Uttara Bhadrapada": (_J, _J, _J, _J),        # Pisces
    "Revati":            (_J, _J, _J, _J),        # Pisces
}

# Yoni animal and gender of each nakshatra.
CLASSICAL_YONI = {
    "Ashwini": ("horse", "male"),            "Bharani": ("elephant", "male"),
    "Krittika": ("goat", "female"),          "Rohini": ("serpent", "male"),
    "Mrigashira": ("serpent", "female"),     "Ardra": ("dog", "female"),
    "Punarvasu": ("cat", "female"),          "Pushya": ("goat", "male"),
    "Ashlesha": ("cat", "male"),             "Magha": ("rat", "male"),
    "Purva Phalguni": ("rat", "female"),     "Uttara Phalguni": ("cow", "male"),
    "Hasta": ("buffalo", "female"),          "Chitra": ("tiger", "female"),
    "Swati": ("buffalo", "male"),            "Vishakha": ("tiger", "male"),
    "Anuradha": ("deer", "female"),          "Jyeshtha": ("deer", "male"),
    "Mula": ("dog", "male"),                 "Purva Ashadha": ("monkey", "male"),
    "Uttara Ashadha": ("mongoose", "male"),  "Shravana": ("monkey", "female"),
    "Dhanishta": ("lion", "female"),         "Shatabhisha": ("horse", "female"),
    "Purva Bhadrapada": ("lion", "male"),    "Uttara Bhadrapada": ("cow", "female"),
    "Revati": ("elephant", "female"),
}

# Yoni points, saravali.de table.  BRIDE on the rows, GROOM on the columns.
YONI_ANIMALS = ("horse", "elephant", "goat", "serpent", "dog", "cat", "rat",
                "cow", "buffalo", "tiger", "deer", "monkey", "mongoose", "lion")
CLASSICAL_YONI_POINTS = {
    # bride:     groom: ho el go se do ca ra co bu ti de mo mn li
    "horse":    (4, 2, 2, 3, 2, 2, 2, 1, 0, 1, 1, 3, 2, 1),
    "elephant": (2, 4, 3, 3, 2, 2, 2, 2, 3, 1, 2, 3, 2, 0),
    "goat":     (2, 3, 4, 2, 1, 2, 1, 3, 3, 1, 2, 0, 3, 1),
    "serpent":  (3, 3, 2, 4, 2, 1, 1, 1, 1, 2, 2, 2, 0, 2),
    "dog":      (2, 2, 1, 2, 4, 2, 1, 2, 2, 1, 0, 2, 1, 1),
    "cat":      (2, 2, 2, 1, 2, 4, 0, 2, 2, 1, 3, 3, 2, 1),
    "rat":      (2, 2, 1, 1, 1, 0, 4, 2, 2, 2, 2, 2, 1, 2),
    "cow":      (1, 2, 3, 1, 2, 2, 2, 4, 3, 0, 3, 2, 2, 1),
    "buffalo":  (0, 3, 3, 1, 2, 2, 2, 3, 4, 1, 2, 2, 2, 1),
    "tiger":    (1, 1, 1, 2, 1, 1, 2, 0, 1, 4, 1, 1, 2, 1),
    "deer":     (1, 2, 2, 2, 0, 3, 2, 3, 2, 1, 4, 2, 2, 1),
    "monkey":   (3, 3, 0, 2, 2, 3, 2, 2, 2, 1, 2, 4, 3, 2),
    "mongoose": (2, 2, 3, 0, 1, 2, 1, 2, 2, 2, 2, 3, 4, 2),
    "lion":     (1, 0, 1, 2, 1, 1, 2, 1, 1, 1, 1, 2, 2, 4),
}

# Gana points, saravali.de table.  BRIDE on the rows, GROOM on the columns.
GANAS = ("deva", "manushya", "rakshasa")
CLASSICAL_GANA_POINTS = {
    # bride:     groom: deva manushya rakshasa
    "deva":     (6, 6, 0),
    "manushya": (5, 6, 0),
    "rakshasa": (1, 0, 6),
}


def _invert(groups: dict[str, tuple[str, ...]]) -> dict[str, str]:
    return {nak: label for label, naks in groups.items() for nak in naks}


def _classical_tara(nak_a: str, nak_b: str) -> float:
    """The Tara rule restated from the text: inclusive count each way, mod 9."""
    order = list(utils.NAKSHATRAS)
    i, j = order.index(nak_a), order.index(nak_b)
    count_ab = (j - i) % 27 + 1
    count_ba = (i - j) % 27 + 1
    good = sum(1 for c in (count_ab, count_ba)
               if c % 9 not in TARA_INAUSPICIOUS_REMAINDERS)
    return 1.5 * good


# ---------------------------------------------------------------------------
# The hand-typed tables are themselves well formed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("table", [CLASSICAL_NADI, CLASSICAL_GANA],
                         ids=["nadi", "gana"])
def test_each_classical_group_holds_nine_and_the_groups_partition_the_27(table):
    assert all(len(naks) == 9 for naks in table.values())
    assert sorted(_invert(table)) == sorted(utils.NAKSHATRAS)


# ---------------------------------------------------------------------------
# Nadi
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nak", utils.NAKSHATRAS)
def test_every_nakshatra_carries_its_classical_nadi(nak):
    assert compat._nakshatra_nadi(nak) == _invert(CLASSICAL_NADI)[nak]


def test_nadi_score_matches_the_classical_table_for_every_pair():
    nadi = _invert(CLASSICAL_NADI)
    wrong = []
    for a in utils.NAKSHATRAS:
        for b in utils.NAKSHATRAS:
            expected = 0.0 if nadi[a] == nadi[b] else 8.0
            score, _ = compat._nadi(a, b)
            if score != expected:
                wrong.append((a, b, score, expected))
    assert wrong == []


def test_nadi_worked_examples():
    # Rohini is Antya (4th star: Aadi, Madhya, Antya, ANTYA); Ashwini is Aadi.
    score, interp = compat._nadi("Rohini", "Ashwini")
    assert score == 8.0
    assert "Antya and Aadi" in interp
    # Ardra is Aadi (6th star: ..., Antya, Madhya, AADI) -- same as Ashwini.
    score, interp = compat._nadi("Ardra", "Ashwini")
    assert score == 0.0
    assert "nadi dosha" in interp


# ---------------------------------------------------------------------------
# Gana
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nak", utils.NAKSHATRAS)
def test_every_nakshatra_carries_its_classical_gana(nak):
    assert compat.NAKSHATRA_GANA[nak] == _invert(CLASSICAL_GANA)[nak]


def test_gana_worked_examples_for_uttara_bhadrapada():
    # deva groom + manushya bride -> 5; manushya + manushya -> 6.
    assert compat._gana("Ashwini", "Uttara Bhadrapada")[0] == 5.0
    assert compat._gana("Bharani", "Uttara Bhadrapada")[0] == 6.0


def test_gana_score_matches_the_directional_table_for_every_pair():
    # All 27 x 27 ordered (groom, bride) pairs: 9 cells of the 3 x 3 table,
    # each reached through the hand-typed gana of both nakshatras.
    gana = _invert(CLASSICAL_GANA)
    wrong = []
    for groom in utils.NAKSHATRAS:
        for bride in utils.NAKSHATRAS:
            expected = float(CLASSICAL_GANA_POINTS[gana[bride]][GANAS.index(gana[groom])])
            score, _ = compat._gana(groom, bride)
            if score != expected:
                wrong.append((groom, bride, score, expected))
    assert wrong == []


def test_gana_worked_examples_are_directional():
    # Ashwini is deva, Krittika rakshasa, Rohini manushya.
    # Deva groom, rakshasa bride: bride row rakshasa, groom column deva -> 1.
    assert compat._gana("Ashwini", "Krittika")[0] == 1.0
    # Rakshasa groom, deva bride: bride row deva, groom column rakshasa -> 0.
    assert compat._gana("Krittika", "Ashwini")[0] == 0.0
    # Manushya groom, deva bride -> 6; deva groom, manushya bride -> 5.
    assert compat._gana("Rohini", "Ashwini")[0] == 6.0
    assert compat._gana("Ashwini", "Rohini")[0] == 5.0
    # Rakshasa groom with a manushya bride and the reverse are both 0.
    assert compat._gana("Krittika", "Rohini")[0] == 0.0
    assert compat._gana("Rohini", "Krittika")[0] == 0.0


# ---------------------------------------------------------------------------
# Vasya
# ---------------------------------------------------------------------------

def test_vasya_score_matches_the_table_in_every_cell():
    wrong = []
    for bride in VASYA_GROUPS:
        for col, groom in enumerate(VASYA_GROUPS):
            expected = CLASSICAL_VASYA_POINTS[bride][col]
            score, _ = compat._vasya(groom, bride)
            if score != expected:
                wrong.append((groom, bride, score, expected))
    assert wrong == []


def test_vasya_worked_examples_are_directional():
    # Keeta groom, chatushpada bride: row chatushpada, column keeta -> 2.
    assert compat._vasya("keeta", "chatushpada")[0] == 2.0
    # Chatushpada groom, keeta bride: row keeta, column chatushpada -> 1.
    assert compat._vasya("chatushpada", "keeta")[0] == 1.0
    # Nara groom, chatushpada bride -> 0.5; a vanchar (Leo) groom with a nara
    # bride -> 0.
    assert compat._vasya("nara", "chatushpada")[0] == 0.5
    assert compat._vasya("vanchar", "nara")[0] == 0.0


_PADA = 10.0 / 3.0  # one nakshatra pada, in degrees


@pytest.mark.parametrize("nak", utils.NAKSHATRAS)
def test_every_pada_carries_its_classical_vasya_group(nak):
    # All 108 padas: sample just inside each end and the middle of every pada;
    # the straddling padas are checked on both sides of the 15 degree split.
    wrong = []
    for pada, expected in enumerate(CLASSICAL_PADA_VASYA[nak]):
        start = utils.NAKSHATRAS.index(nak) * 4 * _PADA + pada * _PADA
        below, _, above = expected.partition("/")
        for lon in (start + 1e-6, start + _PADA / 2, start + _PADA - 1e-6):
            sign = utils.SIGNS[int(lon // 30)]
            degree = lon % 30.0
            want = (above or below) if (above and degree >= 15.0) else below
            got = compat.vasya_group(sign, degree)
            if got != want:
                wrong.append((nak, pada + 1, round(lon, 4), got, want))
    assert wrong == []


def test_the_half_sign_split_is_at_exactly_fifteen_degrees():
    assert compat.vasya_group("Sagittarius", 14.999999) == "nara"
    assert compat.vasya_group("Sagittarius", 15.0) == "chatushpada"
    assert compat.vasya_group("Capricorn", 14.999999) == "chatushpada"
    assert compat.vasya_group("Capricorn", 15.0) == "jalchar"
    with pytest.raises(ValueError):
        compat.vasya_group("Capricorn", 30.0)
    with pytest.raises(KeyError):
        compat.vasya_group("Ophiuchus", 1.0)


def test_the_split_reads_the_unrounded_longitude():
    # PlanetData.degrees is rounded to 4 dp: a Moon at Sagittarius 14.99996
    # reads 15.0 there.  The split must use the unrounded longitude.
    moon = PlanetData(planet="Moon", sign="Sagittarius", degrees=15.0,
                      nakshatra="Purva Ashadha", dignity="neutral", house=1,
                      conjunctions=[], aspects=[], is_retrograde=False,
                      longitude_abs=254.99996)
    assert compat.vasya_group(moon.sign, compat._degree_in_sign(moon)) == "nara"


# ---------------------------------------------------------------------------
# Yoni
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nak", utils.NAKSHATRAS)
def test_every_nakshatra_carries_its_classical_yoni(nak):
    assert compat.NAKSHATRA_YONI[nak] == CLASSICAL_YONI[nak]


def test_each_yoni_animal_has_one_male_and_one_female_star_except_the_mongoose():
    by_animal: dict[str, list[str]] = {}
    for animal, gender in CLASSICAL_YONI.values():
        by_animal.setdefault(animal, []).append(gender)
    assert sorted(by_animal) == sorted(YONI_ANIMALS)
    for animal, genders in by_animal.items():
        expected = ["male"] if animal == "mongoose" else ["female", "male"]
        assert sorted(genders) == expected, animal


def test_yoni_score_matches_the_table_for_every_pair():
    # All 27 x 27 ordered (groom, bride) pairs reach every one of the 14 x 14
    # cells that any two nakshatras can reach; the cell test below covers the
    # table itself.
    wrong = []
    for groom in utils.NAKSHATRAS:
        for bride in utils.NAKSHATRAS:
            g_animal, b_animal = CLASSICAL_YONI[groom][0], CLASSICAL_YONI[bride][0]
            expected = float(CLASSICAL_YONI_POINTS[b_animal][YONI_ANIMALS.index(g_animal)])
            score, _ = compat._yoni(groom, bride)
            if score != expected:
                wrong.append((groom, bride, score, expected))
    assert wrong == []


def test_yoni_table_every_cell():
    # Every animal has a nakshatra, so each of the 196 cells is reachable;
    # drive each through one representative star per animal.
    star = {}
    for nak, (animal, _) in CLASSICAL_YONI.items():
        star.setdefault(animal, nak)
    wrong = []
    for b_animal in YONI_ANIMALS:
        for col, g_animal in enumerate(YONI_ANIMALS):
            score, _ = compat._yoni(star[g_animal], star[b_animal])
            if score != CLASSICAL_YONI_POINTS[b_animal][col]:
                wrong.append((g_animal, b_animal, score))
    assert wrong == []


def test_yoni_worked_examples():
    # Ashwini (horse) groom, Rohini (serpent) bride -> friendly, 3.
    assert compat._yoni("Ashwini", "Rohini")[0] == 3.0
    # Ashwini (horse) and Uttara Phalguni (cow) -> unfriendly, 1.
    assert compat._yoni("Ashwini", "Uttara Phalguni")[0] == 1.0
    # Ashwini (horse) and Anuradha (deer) -> 1 in this table (3 in others).
    assert compat._yoni("Anuradha", "Ashwini")[0] == 1.0
    # Swati (buffalo) and Ashwini (horse) -> sworn enemies, 0.
    assert compat._yoni("Swati", "Ashwini")[0] == 0.0
    # Magha (rat) and Ashlesha (cat) -> sworn enemies, 0.
    assert compat._yoni("Magha", "Ashlesha")[0] == 0.0


# ---------------------------------------------------------------------------
# The hand-typed tables agree with the cited transcription
# ---------------------------------------------------------------------------

def test_hand_typed_point_tables_match_the_cited_transcription():
    # A check on the TYPING above, against the published table as PyJHora
    # 4.8.7 transcribes it -- never against the engine under test.
    from jhora.horoscope.match import compatibility as cited

    vasya_names = {"Chathushpadha": "chatushpada", "Manava": "nara",
                   "Jalachara": "jalchar", "Vanachara": "vanchar", "Keeta": "keeta"}
    assert tuple(vasya_names[c] for c in cited.vasiya_categories) == VASYA_GROUPS
    assert [list(CLASSICAL_VASYA_POINTS[g]) for g in VASYA_GROUPS] == cited.VasiyaArray

    yoni_names = {"Sheep": "goat", "Serpant": "serpent"}
    cited_animals = tuple(yoni_names.get(a, a.lower()) for a in cited.yoni_categories)
    assert cited_animals == YONI_ANIMALS
    assert [list(CLASSICAL_YONI_POINTS[a]) for a in YONI_ANIMALS] == cited.YoniArray
    assert [CLASSICAL_YONI[n][0] for n in utils.NAKSHATRAS] == \
        [cited_animals[i] for i in cited.yoni_mappings]

    assert [list(CLASSICAL_GANA_POINTS[g]) for g in GANAS] == cited.gana_array


# ---------------------------------------------------------------------------
# Tara
# ---------------------------------------------------------------------------

def test_tara_score_matches_the_classical_rule_for_every_pair():
    wrong = []
    for a in utils.NAKSHATRAS:
        for b in utils.NAKSHATRAS:
            score, _ = compat._tara(a, b)
            expected = _classical_tara(a, b)
            if score != expected:
                wrong.append((a, b, score, expected))
    assert wrong == []


def test_tara_worked_examples():
    # Same star: count 1 each way, remainder 1 (Janma) -- not 3/5/7 -> 3.
    assert compat._tara("Ashwini", "Ashwini")[0] == 3.0
    # Ashwini -> Magha is the 10th star (remainder 1), Magha -> Ashwini the
    # 19th (remainder 1): both Janma, both auspicious -> 3.
    assert compat._tara("Ashwini", "Magha")[0] == 3.0
    # Ashwini -> Krittika is the 3rd (Vipat, bad); Krittika -> Ashwini the
    # 26th (remainder 8, auspicious) -> 1.5.
    assert compat._tara("Ashwini", "Krittika")[0] == 1.5


def test_tara_never_scores_zero_because_both_directions_cannot_be_inauspicious():
    # For two different stars the inclusive counts sum to 29, so the two
    # remainders sum to 2 (mod 9); no two of {3, 5, 7} do.  The same star gives
    # remainder 1 both ways.  So under the classical rule the minimum is 1.5.
    scores = {compat._tara(a, b)[0]
              for a in utils.NAKSHATRAS for b in utils.NAKSHATRAS}
    assert scores == {1.5, 3.0}


# ---------------------------------------------------------------------------
# Through the real routes
# ---------------------------------------------------------------------------

def _birth(date: str) -> dict:
    return {
        "name": "synthetic",
        "birth_date": date,
        "birth_time": "12:00:00",
        "birth_place": "Synthetic Place",
        "latitude": 7.0,
        "longitude": 80.0,
        "timezone_offset_hours": 5.5,
    }


# Moon near the middle of each named nakshatra (sidereal longitude in brackets).
ASHWINI_1 = _birth("1985-04-20")          # Aries   ~7.0
ASHWINI_2 = _birth("1985-10-28")          # Aries   ~6.1
ROHINI = _birth("1985-01-04")             # Taurus  ~16.0
ARDRA = _birth("1985-06-19")              # Gemini  ~13.3
MAGHA = _birth("1985-01-10")              # Leo     ~7.4
UTTARA_BHADRAPADA = _birth("1985-05-15")  # Pisces  ~10.3
KRITTIKA = _birth("1985-01-03")           # Taurus  ~3.5
HASTA = _birth("1985-02-09")              # Virgo   ~16.3
# Second halves of the two split signs, about 5 degrees past the split.
PURVA_ASHADHA = _birth("1985-03-15")      # Sagittarius ~19.9
SHRAVANA = _birth("1985-08-01")           # Capricorn   ~19.9


def _moon_nakshatra(client, person: dict) -> str:
    r = client.post("/v1/chart", json=person)
    assert r.status_code == 200, r.text
    return next(p for p in r.json()["rasi"] if p["planet"] == "Moon")["nakshatra"]


@pytest.mark.parametrize("person,nak", [
    (ASHWINI_1, "Ashwini"), (ASHWINI_2, "Ashwini"), (ROHINI, "Rohini"),
    (ARDRA, "Ardra"), (MAGHA, "Magha"),
    (UTTARA_BHADRAPADA, "Uttara Bhadrapada"),
    (KRITTIKA, "Krittika"), (HASTA, "Hasta"),
    (PURVA_ASHADHA, "Purva Ashadha"), (SHRAVANA, "Shravana"),
])
def test_route_fixtures_land_in_the_intended_nakshatra(client, person, nak):
    assert _moon_nakshatra(client, person) == nak


@pytest.mark.parametrize("person,sign,lo,hi", [
    (PURVA_ASHADHA, "Sagittarius", 18.0, 22.0),
    (SHRAVANA, "Capricorn", 18.0, 22.0),
])
def test_split_fixtures_sit_well_past_fifteen_degrees(client, person, sign, lo, hi):
    r = client.post("/v1/chart", json=person)
    assert r.status_code == 200, r.text
    moon = next(p for p in r.json()["rasi"] if p["planet"] == "Moon")
    assert moon["sign"] == sign
    assert lo < moon["degrees"] < hi


def _kutas(client, person_a: dict, person_b: dict) -> dict[str, float]:
    r = client.post("/v1/compat", json={"person_a": person_a, "person_b": person_b})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["max_score"] == 36.0
    return {k["name"]: k["score"] for k in body["kutas"]}


def test_compat_route_serves_classical_nadi(client):
    assert _kutas(client, ROHINI, ASHWINI_1)["nadi"] == 8.0   # Antya / Aadi
    assert _kutas(client, ARDRA, ASHWINI_1)["nadi"] == 0.0    # Aadi / Aadi: dosha


def test_compat_route_serves_classical_tara(client):
    assert _kutas(client, ASHWINI_1, ASHWINI_2)["tara"] == 3.0   # same star
    assert _kutas(client, ASHWINI_1, MAGHA)["tara"] == 3.0       # 10th / 19th


def test_compat_route_serves_classical_gana_for_uttara_bhadrapada(client):
    assert _kutas(client, ASHWINI_1, UTTARA_BHADRAPADA)["gana"] == 5.0  # deva/manushya


def test_compat_request_schema_names_the_groom_and_the_bride():
    # The order is part of the wire contract, so it is stated where a caller
    # reads the contract: the request model's field descriptions.
    from app.schemas import CompatRequest

    fields = CompatRequest.model_fields
    assert "GROOM" in (fields["person_a"].description or "")
    assert "BRIDE" in (fields["person_b"].description or "")


def test_compat_route_scores_gana_with_person_a_as_the_groom(client):
    # person_a = groom, person_b = bride.  Deva groom, rakshasa bride -> 1;
    # the same two charts the other way round -> 0.
    assert _kutas(client, ASHWINI_1, KRITTIKA)["gana"] == 1.0
    assert _kutas(client, KRITTIKA, ASHWINI_1)["gana"] == 0.0
    # Manushya groom, deva bride -> 6.
    assert _kutas(client, ROHINI, ASHWINI_1)["gana"] == 6.0


def test_compat_route_serves_the_vasya_half_sign_split(client):
    # Moon in the second half of Sagittarius is chatushpada, not nara, so with
    # an Aries (chatushpada) bride the groom scores the full 2.
    assert _kutas(client, PURVA_ASHADHA, ASHWINI_1)["vasya"] == 2.0
    # Second half of Capricorn is jalchar, not chatushpada: a chatushpada
    # (Aries) groom with that bride is row jalchar, column chatushpada -> 1;
    # that bride as groom with a nara (Ardra, Gemini) bride -> row nara,
    # column jalchar -> 0.
    assert _kutas(client, SHRAVANA, ARDRA)["vasya"] == 0.0
    assert _kutas(client, ASHWINI_1, SHRAVANA)["vasya"] == 1.0


def test_compat_route_serves_the_yoni_table(client):
    # Ashwini (horse) and Rohini (serpent) are friendly -> 3.
    assert _kutas(client, ASHWINI_1, ROHINI)["yoni"] == 3.0


def test_compat_route_worked_total_by_hand(client):
    # Groom Ashwini (Aries), bride Rohini (Taurus), every koota by hand:
    #   varna   Kshatriya groom >= Vaishya bride                 1
    #   vasya   chatushpada / chatushpada                         2
    #   tara    count 4 (rem 4, good) and 25 (rem 7, bad)         1.5
    #   yoni    horse / serpent, friendly                         3
    #   maitri  Mars / Venus, neutral both ways                   3
    #   gana    deva groom, manushya bride                        5
    #   bhakoot 2/12 from each other: dosha                       0
    #   nadi    Aadi / Antya                                      8
    r = client.post("/v1/compat", json={"person_a": ASHWINI_1, "person_b": ROHINI})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {k["name"]: k["score"] for k in body["kutas"]} == {
        "varna": 1.0, "vasya": 2.0, "tara": 1.5, "yoni": 3.0,
        "graha_maitri": 3.0, "gana": 5.0, "bhakoot": 0.0, "nadi": 8.0,
    }
    assert body["total_score"] == 23.5
    assert body["max_score"] == 36.0
    assert {k["name"]: k["max_score"] for k in body["kutas"]} == {
        "varna": 1.0, "vasya": 2.0, "tara": 3.0, "yoni": 4.0,
        "graha_maitri": 5.0, "gana": 6.0, "bhakoot": 7.0, "nadi": 8.0,
    }


def test_profile_route_serves_classical_nadi_and_gana(client):
    r = client.post("/v1/profile", json=ROHINI)
    assert r.status_code == 200, r.text
    assert r.json()["avkahada"]["nadi"] == "Antya"
    r = client.post("/v1/profile", json=UTTARA_BHADRAPADA)
    assert r.status_code == 200, r.text
    avk = r.json()["avkahada"]
    assert avk["gana"] == "manushya"
    assert avk["nadi"] == "Madhya"


def test_profile_vasya_reads_the_degree_and_keeps_its_unknown_label():
    # The avkahada helper keeps its existing "Unknown" label for a sign or a
    # degree it cannot place, and otherwise serves the split group.
    from bphs_core import profile

    assert profile._vasya("Capricorn", 14.5) == "chatushpada"
    assert profile._vasya("Capricorn", 15.0) == "jalchar"
    assert profile._vasya("Ophiuchus", 1.0) == "Unknown"
    assert profile._vasya("Capricorn", 30.0) == "Unknown"


def test_profile_route_serves_the_vasya_split_and_yoni_gender(client):
    r = client.post("/v1/profile", json=SHRAVANA)
    assert r.status_code == 200, r.text
    avk = r.json()["avkahada"]
    assert avk["vasya"] == "jalchar"          # Capricorn second half
    assert avk["yoni"] == "monkey (female)"
    r = client.post("/v1/profile", json=PURVA_ASHADHA)
    assert r.status_code == 200, r.text
    assert r.json()["avkahada"]["vasya"] == "chatushpada"  # Sagittarius second half
    r = client.post("/v1/profile", json=HASTA)
    assert r.status_code == 200, r.text
    assert r.json()["avkahada"]["yoni"] == "buffalo (female)"
