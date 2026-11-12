"""Ashtakoota tables pinned against the classical rule, not against the code.

Three Ashtakoota inputs are fixed here: the Nadi of each nakshatra, the Gana of
each nakshatra, and the Tara (Dina) koota rule.  The authority for all three is
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
    # deva + manushya -> 5; manushya + manushya -> 6.
    assert compat._gana("Ashwini", "Uttara Bhadrapada")[0] == 5.0
    assert compat._gana("Bharani", "Uttara Bhadrapada")[0] == 6.0


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


def _moon_nakshatra(client, person: dict) -> str:
    r = client.post("/v1/chart", json=person)
    assert r.status_code == 200, r.text
    return next(p for p in r.json()["rasi"] if p["planet"] == "Moon")["nakshatra"]


@pytest.mark.parametrize("person,nak", [
    (ASHWINI_1, "Ashwini"), (ASHWINI_2, "Ashwini"), (ROHINI, "Rohini"),
    (ARDRA, "Ardra"), (MAGHA, "Magha"),
    (UTTARA_BHADRAPADA, "Uttara Bhadrapada"),
])
def test_route_fixtures_land_in_the_intended_nakshatra(client, person, nak):
    assert _moon_nakshatra(client, person) == nak


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


def test_profile_route_serves_classical_nadi_and_gana(client):
    r = client.post("/v1/profile", json=ROHINI)
    assert r.status_code == 200, r.text
    assert r.json()["avkahada"]["nadi"] == "Antya"
    r = client.post("/v1/profile", json=UTTARA_BHADRAPADA)
    assert r.status_code == 200, r.text
    avk = r.json()["avkahada"]
    assert avk["gana"] == "manushya"
    assert avk["nadi"] == "Madhya"
