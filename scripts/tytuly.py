"""Tytuły kart odczytane z nagłówka PDF – tak jak pokazuje je Navigraph (np. 'ILS Z RWY 33', 'RNP RWY 15')."""
import io
import re
from collections import Counter

from kategorie import pasy
from procedury import z_tekstu

TYP_APP = r"(?:ILS|LOC|LLZ|RNP|RNAV|VOR|NDB|GLS|LPV|TACAN|DME|GNSS|GPS|SRA|PAR|VISUAL|CIRCLING)"
# np. "ILS Z or LOC Z RWY 33", "RNP RWY 15 (AR)", "VOR/DME RWY 29", "NDB OR VOR RWY 11"
_APP = re.compile(
    rf"\b({TYP_APP}(?:\s*(?:/|OR|AND|&|-)?\s*(?:{TYP_APP}|[XYZWABCDE]\b|\(\s*[A-Z ]{{2,10}}\s*\)|CAT\s*I{{1,3}}|CAT\s*[ABCDH]+|DME)){{0,6}}"
    rf"\s*(?:-\s*)?RWY\s*\d{{2}}[LRC]?(?:\s*/\s*\d{{2}}[LRC]?)?(?:\s*\((?:AR|LPV|LNAV|RNP\s*AR|PRM)\))?)",
    re.I)
_GND = [
    (r"CARTE\s+DE\s+STATIONNEMENT", "Parking/Docking Chart"),
    (r"CARTE\s+DES\s+MOUVEMENTS\s+A?U?\s*SOL", "Ground Movement Chart"),
    (r"CARTE\s+D.A[EÉ]RODROME", "Aerodrome Chart"),
    (r"AIRCRAFT\s+PARKING\s*/\s*DOCKING\s+CHART|PARKING\s*/\s*DOCKING\s+CHART|PARKING\s+CHART|DOCKING\s+CHART", "Parking/Docking Chart"),
    (r"AERODROME\s+GROUND\s+MOVEMENT\s+CHART|GROUND\s+MOVEMENT\s+CHART", "Ground Movement Chart"),
    (r"HOT\s*SPOTS?", "Hot Spot Chart"),
    (r"DE-?ICING", "De-icing Chart"),
    (r"TAXI\s*(?:ROUTES?|ING)\s+CHART|STANDARD\s+TAXI", "Taxi Routes Chart"),
    (r"AERODROME\s+CHART|AIRPORT\s+CHART", "Aerodrome Chart"),
]
_ID = r"(?:[A-Z]?\d{1,3}[A-Z]?|[A-Z])"
_QUALIF = re.compile(rf"\b(APRONS?\s+{_ID}(?:\s*,\s*{_ID}){{0,8}}(?:\s*(?:AND|&)\s*{_ID})?|CARGO\s+APRON|MILITARY\s+APRON|(?:NORTH|SOUTH|EAST|WEST)(?:ERN)?\s+(?:PART|AREA|APRON))\b", re.I)


def _norm_app(t):
    t = re.sub(r"\s+", " ", t.upper()).strip(" -")
    t = re.sub(r"\s*/\s*", "/", t)
    t = re.sub(r"\bRWY(\d)", r"RWY \1", t)
    return t


def tekst_pdf(dane: bytes, stron=2) -> str:
    tekst = ""
    try:
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(dane))
        tekst = "\n".join((p.extract_text() or "") for p in r.pages[:stron])
    except Exception:  # noqa: BLE001
        pass
    return tekst


def analiza(tekst: str, kat: str) -> dict:
    """Zwraca {'t': tytuł lub None, 'c': poprawiona kategoria lub None, 'p': [procedury MCDU], 'r': [pasy]}."""
    T = tekst.upper()
    wynik = {"t": None, "c": None, "p": [], "r": []}
    if not T.strip():
        return wynik
    # kategoria z nagłówka karty (gdy spis AIP był ogólnikowy)
    if re.search(r"STANDARD\s+(INSTRUMENT\s+)?DEPARTURE\s+CHART|\bSID\b.{0,20}CHART|CARTE\s+DE\s+D[EÉ]PART", T):
        kk = "SID"
    elif re.search(r"STANDARD\s+(INSTRUMENT\s+)?ARRIVAL\s+CHART|\bSTAR\b.{0,20}CHART|CARTE\s+D.ARRIV[EÉ]E", T):
        kk = "STAR"
    elif re.search(r"INSTRUMENT\s+APPROACH\s+CHART|CARTE\s+D.APPROCHE\s+AUX\s+INSTRUMENTS", T):
        kk = "APP"
    else:
        kk = kat
    if kk != kat and kat in ("REF", "GND") and kk in ("SID", "STAR", "APP"):
        wynik["c"] = kk
    kat = kk

    if kat == "APP":
        kandydaci = [_norm_app(m.group(1)) for m in _APP.finditer(T)]
        kandydaci = [k for k in kandydaci if 6 <= len(k) <= 50 and not k.startswith(("DME ", "GPS "))]
        if kandydaci:
            # tytuł zwykle powtarza się na karcie (nagłówek + profil); weź najczęstszy, przy remisie najdłuższy
            licz = Counter(kandydaci)
            wynik["t"] = max(licz, key=lambda k: (licz[k], len(k)))
    elif kat in ("SID", "STAR"):
        wynik["p"] = z_tekstu(tekst)
        rw = pasy(T)
        rnav = bool(re.search(r"\bRNAV\b|\bRNP\b|\bGNSS\b", T))
        if rw:
            wynik["t"] = f"{kat} RWY {'/'.join(rw[:4])}" + (" (RNAV)" if rnav else "")
    elif kat == "GND":
        naglowek = T[:900]
        trafienia = [(m.start(), nazwa) for wz, nazwa in _GND for m in [re.search(wz, naglowek)] if m]
        if trafienia:
            nazwa = min(trafienia)[1]
            q = _QUALIF.search(naglowek)
            dopisek = re.sub(r"\s+", " ", q.group(1)).title() if q else ""
            wynik["t"] = nazwa + (f" – {dopisek}" if dopisek else "")
    if wynik["t"]:
        wynik["r"] = pasy(wynik["t"])
    return wynik


if __name__ == "__main__":
    probki = [
        ("APP", "INSTRUMENT APPROACH CHART - ICAO\nWARSZAWA/Chopina\nILS Z or LOC Z RWY 33\n...\nILS Z or LOC Z RWY 33\nMISSED APPROACH: climb"),
        ("APP", "INSTRUMENT APPROACH CHART\nRNP RWY 15\nLNAV/VNAV LNAV\nRNP RWY 15"),
        ("APP", "IAC VOR/DME RWY 29 KRAKOW"),
        ("REF", "INSTRUMENT APPROACH CHART - ICAO  NDB RWY 11"),
        ("SID", "STANDARD DEPARTURE CHART - INSTRUMENT (SID) - ICAO RWY 29 RNAV ARDAG 1G BAMSO 1G\nARDAG BAMSO"),
        ("GND", "AIRCRAFT PARKING/DOCKING CHART - ICAO\n1: 5 000\nAPRONS 1, 7A, 7B, 9"),
        ("GND", "AERODROME CHART - ICAO RWY 11/29 RWY 15/33"),
    ]
    for kat, t in probki:
        print(kat, analiza(t, kat))
