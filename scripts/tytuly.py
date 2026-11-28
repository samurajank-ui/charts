"""Tytuły kart odczytane z nagłówka PDF – tak jak pokazuje je Navigraph (np. 'ILS Z RWY 33', 'RNP RWY 15')."""
import io
import os
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
# odwrócony zapis tytułu (UK: 'RWY 05R RNP', Hiszpania: 'RWY 36 RNP Z')
_APP_ODWR = re.compile(
    rf"\bRWY\s*(\d{{2}}[LRC]?)\s+({TYP_APP}(?:\s*(?:/|OR|AND|&)?\s*(?:{TYP_APP}|[XYZW]\b|\(\s*[A-Z]{{1,6}}\s*\)|CAT\s*I{{1,3}}|DME)){{0,5}})", re.I)
_GND = [
    (r"CARTE\s+DE\s+STATIONNEMENT", "Parking/Docking Chart"),
    (r"CARTE\s+DES\s+MOUVEMENTS\s+A?U?\s*SOL", "Ground Movement Chart"),
    (r"CARTE\s+D.A[EÉ]RODROME", "Aerodrome Chart"),
    (r"AIRCRAFT\s+PARKING\s*/\s*DOCKING\s+CHART|PARKING\s*/\s*DOCKING\s+CHART|PARKING\s+CHART|DOCKING\s+CHART", "Parking/Docking Chart"),
    (r"AERODROME\s+GROUND\s+MOVEMENT\s+CHART|GROUND\s+MOVEMENT\s+CHART", "Ground Movement Chart"),
    (r"HOT\s*SPOTS?", "Hot Spot Chart"),
    (r"APRON\s+STAND\s+COORDINATES|STAND\s+COORDINATES|AIRCRAFT\s+STANDS?\s+(CHART|COORDINATES)", "Parking/Docking Chart"),
    (r"DE-?ICING", "De-icing Chart"),
    (r"TAXI\s*(?:ROUTES?|ING)\s+CHART|STANDARD\s+TAXI", "Taxi Routes Chart"),
    (r"AERODROME\s+CHART|AIRPORT\s+CHART", "Aerodrome Chart"),
]
_ID = r"(?:[A-Z]?\d{1,3}[A-Z]?|[A-Z])"
_REF = [
    (r"AERODROME\s+OBSTACLE\s+CHART[^\n]{0,20}TYPE\s*A|OBSTACLE\s+CHART\s*-?\s*ICAO\s*TYPE\s*A", "Aerodrome Obstacle Chart Type A"),
    (r"AERODROME\s+OBSTACLE\s+CHART[^\n]{0,20}TYPE\s*B", "Aerodrome Obstacle Chart Type B"),
    (r"AERODROME\s+OBSTACLE\s+CHART|OBSTACLE\s+CHART|CARTE\s+D.OBSTACLES", "Aerodrome Obstacle Chart"),
    (r"(ATC\s+)?SURVEILLANCE\s+MINIMUM\s+ALTITUDE\s+CHART|ATCSMAC|MINIMUM\s+(RADAR\s+)?(VECTORING\s+)?ALTITUDE\s+CHART|CARTE\s+DES\s+ALTITUDES\s+MINIMALES",
     "ATC Surveillance Minimum Altitude Chart"),
    (r"FAS\s+DATA\s+BLOCK|SBAS\s+PROVIDER|REFERENCE\s+PATH\s+(DATA\s+SELECTOR|IDENTIFIER)", "FAS Data Block"),
    (r"PRECISION\s+APPROACH\s+TERRAIN\s+CHART", "Precision Approach Terrain Chart"),
    (r"VISUAL\s+APPROACH\s+CHART|CARTE\s+D.APPROCHE\s+(ET\s+D.ATTERRISSAGE\s+)?A\s+VUE|\bVAC\b", "Visual Approach Chart"),
    (r"VISUAL\s+OPERATION\s+CHART|VFR\s+(ROUTES?|CHART|ARRIVAL|DEPARTURE)|ENTRY\s*/\s*EXIT\s+LANES|LANES\s+AND\s+VRPS", "VFR Chart"),
    (r"ARRIVAL\s+AND\s+DEPARTURE\s+ROUTE\s+CHART", "Arrival and Departure Route Chart"),
    (r"NOISE\s+ABATEMENT|NOISE\s+(PREFERENTIAL|SENSITIVE)", "Noise Abatement Chart"),
    (r"BIRD\s+(CONCENTRATION|STRIKE|HAZARD)", "Bird Concentration Chart"),
    (r"AREA\s+CHART|TERMINAL\s+(AREA|CONTROL\s+AREA)\s+CHART|\bTMA\b[^\n]{0,30}CHART", "Area Chart"),
    (r"HOLDING\s+(PATTERNS?|PROCEDURES?)", "Holding Chart"),
    (r"CONTROL\s*ZONE\s+AND\s+CONTROL\s+AREA|CONTROL\s+ZONE\s+CHART|\bCTR\s+CHART", "Control Zone Chart"),
    (r"RADIO\s+COMMUNICATION\s+FAILURE|\bRCF\s+PROCEDURE", "Radio Communication Failure"),
    (r"RADAR\s+(MINIMUM|VECTORING)", "Radar Minimum Altitude Chart"),
    (r"ENGINE\s+FAILURE|EMERGENCY\s+TURN", "Engine Failure Procedures"),
    (r"TAKE-?OFF\s+MINIMUMS", "Takeoff Minimums"),
]
_QUALIF = re.compile(rf"\b(APRONS?\s+{_ID}(?:\s*,\s*{_ID}){{0,8}}(?:\s*(?:AND|&)\s*{_ID})?|CARGO\s+APRON|MILITARY\s+APRON|(?:NORTH|SOUTH|EAST|WEST)(?:ERN)?\s+(?:PART|AREA|APRON))\b", re.I)


def _norm_app(t):
    t = re.sub(r"\s+", " ", t.upper()).strip(" -")
    t = re.sub(r"\s*/\s*", "/", t)
    t = re.sub(r"\bRWY(\d)", r"RWY \1", t)
    return t


def tekst_pdf(dane: bytes, stron=2, ocr=False) -> str:
    tekst = ""
    try:
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(dane))
        tekst = "\n".join((p.extract_text() or "") for p in r.pages[:stron])
    except Exception:  # noqa: BLE001
        pass
    tekst = tekst.replace("\x00", "")          # Łotwa: znaki rozdzielone bajtami zerowymi
    # czcionki bez mapy znaków (Francja): glify '/MT53' to kody ASCII -> '5'
    if tekst.count("/MT") > 20:
        tekst = re.sub(r"/MT(\d{2,3})", lambda m: chr(int(m.group(1))) if 32 <= int(m.group(1)) < 256 else " ", tekst)
    # mało tekstu (napisy zapisane jako grafika) -> rozpoznawanie tekstu z obrazu pierwszej strony
    if ocr and len(re.findall(r"[A-Z]{5}", tekst.upper())) < 3:
        tekst += "\n" + _ocr(dane)
    return tekst


STAT = {"ocr": 0}
os.environ.setdefault("OMP_THREAD_LIMIT", "1")   # wiele tesseractów równolegle – bez tego walczą o rdzenie


def _ocr(dane: bytes) -> str:
    import os
    import shutil
    import subprocess
    import tempfile
    if not (shutil.which("pdftoppm") and shutil.which("tesseract")):
        return ""
    with tempfile.TemporaryDirectory() as d:
        pdf = os.path.join(d, "k.pdf")
        with open(pdf, "wb") as f:
            f.write(dane)
        try:
            subprocess.run(["pdftoppm", "-r", "220", "-f", "1", "-l", "1", "-gray", "-png", pdf, os.path.join(d, "s")],
                           check=True, timeout=120, capture_output=True)
            png = sorted(x for x in os.listdir(d) if x.endswith(".png"))
            if not png:
                return ""
            STAT["ocr"] += 1
            wynik = subprocess.run(["tesseract", os.path.join(d, png[0]), "-", "--psm", "11", "-l", "eng"],
                                   timeout=180, capture_output=True, text=True)
            return wynik.stdout
        except Exception:  # noqa: BLE001
            return ""


def analiza(tekst: str, kat: str) -> dict:
    """Zwraca {'t': tytuł lub None, 'c': poprawiona kategoria lub None, 'p': [procedury MCDU], 'r': [pasy]}."""
    T = re.sub(r"\bRW\s?Y\s*(?=\d{2})", "RWY ", tekst.upper())
    wynik = {"t": None, "c": None, "p": [], "r": []}
    if not T.strip():
        return wynik
    if re.search(r"SBAS\s+PROVIDER|FAS\s+DB\s+TOOL|FAS\s+DATA\s+BLOCK", T):
        m = re.search(r"\bRUNWAY\s+(\d{2})\s+RUNWAY\s+LETTER\s+\d\s*\(([LRC])", T) or re.search(r"\bRUNWAY\s+(\d{2})()", T)
        wynik["t"] = "FAS Data Block" + (f" RWY {m.group(1)}{m.group(2)}" if m else "")
        wynik["c"] = "REF" if kat != "REF" else None
        return wynik
    # kategoria z nagłówka karty (gdy spis AIP był ogólnikowy)
    if re.search(r"STANDARD\s+(INSTRUMENT\s+)?DEPARTURE\s+CHART|\bSID\b.{0,20}CHART|CARTE\s+DE\s+D[EÉ]PART", T):
        kk = "SID"
    elif re.search(r"STANDARD\s+(INSTRUMENT\s+)?ARRIVAL\s+CHART|\bSTAR\b.{0,20}CHART|CARTE\s+D.ARRIV[EÉ]E", T):
        kk = "STAR"
    elif kat in ("REF", "GND") and re.search(r"STANDARD\s+INSTRUMENT\s+DEPARTURE", T):
        kk = "SID"           # Portugalia: tabele SID bez słowa 'CHART'
    elif kat in ("REF", "GND") and re.search(r"STANDARD\s+(INSTRUMENT\s+)?ARRIVAL|\bSTAR\s+RNAV", T):
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
        else:
            odwr = [_norm_app(f"{m.group(2)} RWY {m.group(1)}") for m in _APP_ODWR.finditer(T)]
            odwr = [k for k in odwr if not k.startswith(("DME ", "GPS "))]
            if odwr:
                licz = Counter(odwr)
                wynik["t"] = max(licz, key=lambda k: (licz[k], len(k)))
    elif kat in ("SID", "STAR"):
        wynik["p"] = z_tekstu(tekst)
        rw = pasy(T)
        rnav = bool(re.search(r"\bRNAV\b|\bRNP\b|\bGNSS\b", T))
        if rw:
            wynik["t"] = f"{kat} RWY {'/'.join(rw[:4])}" + (" (RNAV)" if rnav else "")
    elif kat in ("GND", "REF"):
        naglowek = T[:900] + "\n" + (T[-900:] if len(T) > 900 else "")   # UK: tytuł na końcu tekstu
        # najwcześniejsze, a przy remisie najdłuższe dopasowanie (np. "... TYPE A" zamiast samego "OBSTACLE CHART")
        trafienia = [(m.start(), -m.end(), nazwa, "GND") for wz, nazwa in _GND for m in [re.search(wz, naglowek)] if m]
        trafienia += [(m.start(), -m.end(), nazwa, "REF") for wz, nazwa in _REF for m in [re.search(wz, naglowek)] if m]
        if trafienia:
            _, _, nazwa, kk2 = min(trafienia)
            if kk2 != kat:
                wynik["c"] = kk2
            if kk2 == "REF":
                rw = pasy(naglowek)
                if nazwa == "FAS Data Block":
                    m = re.search(r"\bRUNWAY\s+(\d{2})\s+RUNWAY\s+LETTER\s+\d\s*\(([LRC])", naglowek) or re.search(r"\bRUNWAY\s+(\d{2})()", naglowek)
                    wynik["t"] = nazwa + (f" RWY {m.group(1)}{m.group(2)}" if m else "")
                    return wynik
                wynik["t"] = nazwa + (f" RWY {'/'.join(rw[:3])}" if rw and ("Obstacle" in nazwa or "Terrain" in nazwa) else "")
                return wynik
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
