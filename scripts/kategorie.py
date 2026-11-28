"""Klasyfikacja kart w stylu Navigraph: GND (lotnisko/kołowanie), SID, STAR, APP, REF (pozostałe)."""
import os
import re

KOLEJNOSC = ["GND", "SID", "STAR", "APP", "REF"]

_SID = re.compile(r"\bSID\b|STANDARD (INSTRUMENT )?DEPARTURE|INSTRUMENT DEPARTURE|DEPARTURE CHART|\bODP\b|ODLOT", re.I)
_STAR = re.compile(r"\bSTAR\b|STANDARD (INSTRUMENT )?ARRIVAL|ARRIVAL CHART|INSTRUMENT ARRIVAL|PRZYLOT|DOLOT", re.I)
_APP = re.compile(
    r"INSTRUMENT APPROACH|\bIAC\b|\bILS\b|\bLOC\b|\bLLZ\b|\bRNP\b|\bGLS\b|\bLPV\b|\bTACAN\b|\bSRA\b|\bPAR\b"
    r"|\b(RNAV|VOR|NDB|DME|GNSS|GPS)\b.*\bRWY|APPROACH CHART|PODEJ[SŚ]CI|\bCOPTER\b|CIRCLING|VISUAL APPROACH", re.I)
_GND = re.compile(
    r"AERODROME CHART|AIRPORT DIAGRAM|\bADC\b|PARKING|DOCKING|GROUND MOVEMENT|\bGMC\b|\bAPDC\b|HOT ?SPOT|TAXI"
    r"|\bSTANDS?\b|APRON|LAHSO|LAND AND HOLD|LOTNISKA\s*-\s*ICAO|P[ŁL]YT|KO[ŁL]OWANI|POSTOJ", re.I)

# Kody kart FAA d-TPP
FAA = {"APD": "GND", "HOT": "GND", "LAH": "GND", "DP": "SID", "ODP": "SID", "DAU": "SID",
       "STAR": "STAR", "IAP": "APP", "MIN": "REF"}

_RWY = re.compile(r"\bRWYS?\s*((?:\d{1,2}[LRC]?)(?:\s*(?:/|,|&|AND|-)\s*\d{1,2}[LRC]?)*)", re.I)


def kategoria(nazwa: str) -> str:
    n = nazwa or ""
    if _GND.search(n) and not re.search(r"OBSTACLE|TERRAIN|ALTITUDE", n, re.I):
        return "GND"
    if _SID.search(n):
        return "SID"
    if _STAR.search(n):
        return "STAR"
    if _APP.search(n) and not re.search(r"TERRAIN|OBSTACLE|MINIMUM ALTITUDE", n, re.I):
        return "APP"
    return "REF"


def pasy(nazwa: str) -> list:
    out = []
    for m in _RWY.finditer(nazwa or ""):
        for r in re.split(r"\s*(?:/|,|&|AND|-)\s*", m.group(1), flags=re.I):
            r = r.strip().upper()
            if re.fullmatch(r"\d{1,2}[LRC]?", r):
                r = r.zfill(3) if r[-1] in "LRC" and len(r) == 2 else r.zfill(2) if r.isdigit() else r
                if r not in out:
                    out.append(r)
    return out


_ZBEDNE = [
    r"\bINSTRUMENT APPROACH CHART\b", r"\bSTANDARD (INSTRUMENT )?DEPARTURE CHART\b", r"\bSTANDARD (INSTRUMENT )?ARRIVAL CHART\b",
    r"\bINSTRUMENT DEPARTURE CHART\b", r"\bINSTRUMENT ARRIVAL CHART\b", r"\bDEPARTURE CHART\b", r"\bARRIVAL CHART\b",
    r"\bAPPROACH CHART\b", r"(?<=CHART)\s*-\s*INSTRUMENT\b", r"^\s*-?\s*INSTRUMENT\s*-", r"\(\s*(SID|STAR|IAC)\s*\)",
    r"[-–]?\s*\bICAO\b",
]


def ladna_nazwa(nazwa: str, kat: str) -> str:
    """Skraca oficjalny tytuł do formy jak w Navigraph, np. 'Instrument Approach Chart - ICAO ILS RWY 33' -> 'ILS RWY 33'."""
    n = re.sub(r"\s*-?\s*\S*;\S*_SERVER_ID;\d+", "", nazwa or "")          # śmieci z systemów AIP (Avinor)
    n = re.sub(r"\(\s*RNAV\s*\d?\s*(SID|STAR)?\s*BASED\s+ON\s+GNSS\s*\)", "(RNAV)", n, flags=re.I)
    n = re.sub(r"\s+", " ", n).strip()
    n = re.sub(r"^\d{1,2}\.\s+", "", n)                       # "13. Instrument Approach Chart" (Łotwa)
    n = re.sub(r"\s*[—–]\s*", " - ", n)
    n = re.sub(r"\s+-\s+\S*\d\S*_\S*$", "", n)          # "... - ICAO - 1817_EVRA_2_24_14_20260903" (nazwa pliku)
    if kat in ("GND", "REF"):
        from tytuly import analiza                   # nazwa kanoniczna jak w Navigraph: "Parking/Docking Chart"
        w = analiza(n, kat)
        if w["t"]:
            dop = re.search(r"\((?!\s*RWY)([^()]{1,30})\)\s*$", n)
            return w["t"] + (f" ({dop.group(1).strip()})" if dop and "–" not in w["t"] else "")
    if kat == "APP":
        from tytuly import _APP, _norm_app          # tytuł podejścia jak w Navigraph: "ILS Z RWY 11"
        a = re.sub(r"\(\s*CAT\s+[A-E](?:\s*,\s*[A-E])*\s*\)", " ", n, flags=re.I)        # "(CAT A,B,C,D)"
        a = re.sub(r"\bCAT\s*I{1,3}(?:\s*(?:&|AND|/|,)\s*I{1,3})*\b", " ", a, flags=re.I)   # "ILS CAT II & III"
        a = re.sub(r"\(\s*([^()]{2,40}?)\s*\)\s*(?=RWY)", r"\1 ", a)                       # "(RNP) RWY 29" -> "RNP RWY 29"
        t = [_norm_app(m.group(1)) for m in _APP.finditer(a.upper())]
        t = [x for x in t if 6 <= len(x) <= 50]
        if t:
            return max(t, key=len)
    if kat not in ("SID", "STAR", "APP"):
        return re.sub(r"\s*[-–]\s*ICAO\b", "", n).strip(" -–") or n
    k = re.sub(r"CHART\s*-\s*INSTRUMENT\b", "CHART", n, flags=re.I)
    for wz in _ZBEDNE:
        k = re.sub(wz, " ", k, flags=re.I)
    k = re.sub(r"\s+", " ", re.sub(r"(\s*[-–]\s*){2,}", " - ", k)).strip(" -–,")
    # "SID (RNAV RWY 11)" -> "SID RWY 11 (RNAV)"
    m = re.search(r"\(\s*(RNAV|RNP|GNSS)\s+(RWY\s*[0-9LRC/ ]+)\)", k, re.I)
    if m:
        k = (k[:m.start()] + m.group(2).strip() + f" ({m.group(1).upper()})" + k[m.end():]).strip()
    k = re.sub(r"\s*-\s*(?=RWY|\()", " ", k)
    k = re.sub(r"^\s*INSTRUMENT\b\s*", "", k, flags=re.I).strip()
    k = re.sub(r"\s*\((RNAV|RNP)\)\s*(RWY[^()]*)$", r" \2 (\1)", k).strip()   # "SID (RNAV) RWY 06" -> "SID RWY 06 (RNAV)"
    if len(k) < 3:
        return n
    if kat in ("SID", "STAR") and not re.search(rf"\b{kat}\b", k, re.I):
        k = f"{kat} {k}"
    return k


# Nazwy plików w stylu francuskim: AD_2_LFPG_IAC_RWY26L_ILS_Z -> ('APP', 'ILS Z RWY 26L')
_KOD_PLIKU = {"ADC": ("GND", "Aerodrome Chart"), "APDC": ("GND", "Parking/Docking Chart"), "PDC": ("GND", "Parking/Docking Chart"),
              "GMC": ("GND", "Ground Movement Chart"), "IAC": ("APP", ""), "SID": ("SID", "SID"), "STAR": ("STAR", "STAR"),
              "AOC": ("REF", "Aerodrome Obstacle Chart"), "VAC": ("REF", "Visual Approach Chart"), "ARC": ("REF", "Area Chart"),
              "PATC": ("REF", "Precision Approach Terrain Chart"), "ATCSMAC": ("REF", "ATC Surveillance Minimum Altitude Chart"),
              "MRC": ("REF", "Minimum Radar Altitude Chart"), "INSTR": ("REF", "Instructions")}
_KOD_PLIKU.update({
    "AGMC": ("GND", "Ground Movement Chart"), "AMG": ("GND", "Ground Movement Chart"), "HS": ("GND", "Hot Spot Chart"),
    "HOTSPOT": ("GND", "Hot Spot Chart"), "DEICING": ("GND", "De-icing Chart"), "TAXI": ("GND", "Taxi Routes Chart"),
    "MVA": ("REF", "Minimum Vectoring Altitude Chart"), "ENV": ("REF", "Approach Environment Chart"),
    "NOISE": ("REF", "Noise Abatement Chart"), "VFR": ("REF", "VFR Chart"), "TMA": ("REF", "Area Chart"),
})
_KOD_RE = re.compile(r"(" + "|".join(sorted(_KOD_PLIKU, key=len, reverse=True)) + r")(\d{0,3}[A-Z]?)$")
_NIE_KARTY = {"DATA", "TXT", "TEXT", "FASDB", "CODE"}


def z_nazwy_pliku(opis: str, icao: str):
    """Zwraca (kategoria, nazwa) albo ('POMIN', None) dla plików, które nie są kartami; None gdy to nie ten format."""
    m = re.match(rf"^AD_?2_{icao}_([A-Z0-9_\-]+?)(?:\.pdf)?$", opis.strip(), re.I)
    if not m:
        return None
    t = [x for x in m.group(1).upper().split("_") if x]
    if not t or t[0] in _NIE_KARTY or any(x in _NIE_KARTY for x in t):
        return ("POMIN", None)
    kod, reszta = t[0], t[1:]
    if not re.fullmatch(r"[A-Z]{2,}", kod):
        return None                     # 'AD_2_EPGD_12-1' – sam numer strony, nie kod karty
    kat, nazwa = _KOD_PLIKU.get(kod, ("REF", kod.title()))
    pasy_ = [x[3:] for x in reszta if re.fullmatch(r"RWY\d{2}[LRC]?(?:-\d{2}[LRC]?)?", x)]
    inne = [x for x in reszta if not re.fullmatch(r"RWY\d{2}[LRC]?(?:-\d{2}[LRC]?)?|\d{1,2}", x)]
    nr = [x for x in reszta if re.fullmatch(r"\d{1,2}", x)]
    rwy = f"RWY {'/'.join(p.replace('-', '/') for p in pasy_)}" if pasy_ else ""
    if kat == "APP":
        return kat, " ".join(inne + [rwy]).strip() or "Instrument Approach Chart"
    if kat in ("SID", "STAR"):
        rnav = " (RNAV)" if any(x in ("RNAV", "RNP", "GNSS") for x in inne) else ""
        inne = [x for x in inne if x not in ("RNAV", "RNP", "GNSS")]
        return kat, (" ".join([nazwa, rwy] + inne).strip() + rnav)
    return kat, (nazwa + (f" {int(nr[0])}" if nr and nr[0] not in ("01", "1") else "") + (f" {rwy}" if rwy else "")).strip()


def z_kodu(tekst: str, icao: str = ""):
    """Rozpoznaje rodzaj karty po kodzie w nazwie pliku lub krótkim opisie, np. 'EBBR_ADC01_v66.pdf' -> ('GND','Aerodrome Chart'),
    'LP_AD_2_LPPT_IAC_RWY03_ILS_en.pdf' -> ('APP','ILS RWY 03'), 'VAC - ICAO' -> ('REF','Visual Approach Chart')."""
    t = [x for x in re.split(r"[_\-.\s/]+", os.path.basename(tekst or "").upper()) if x and x not in ("PDF", "EN", "ICAO", icao)]
    for i, x in enumerate(t):
        m = _KOD_RE.fullmatch(x)
        if not m:
            continue
        kod = m.group(1)
        kat, nazwa = _KOD_PLIKU[kod]
        reszta = t[i + 1:]
        rw = []
        for j, y in enumerate(reszta):
            if re.fullmatch(r"RWY\d{2}[LRC]?", y):
                rw.append(y[3:])
            elif y == "RWY" and j + 1 < len(reszta) and re.fullmatch(r"\d{2}[LRC]?", reszta[j + 1]):
                rw.append(reszta[j + 1])
        if "ENV" in reszta:
            return "REF", "Approach Environment Chart" + (f" RWY {'/'.join(rw)}" if rw else "")
        rwy = f" RWY {'/'.join(rw)}" if rw else ""
        if kat == "APP":
            typ = [y for y in reszta if re.fullmatch(r"ILS|LOC|RNP|RNAV|VOR|NDB|DME|GLS|LPV|[XYZ]", y)]
            return kat, (" ".join(typ) + rwy).strip() or "Instrument Approach Chart"
        if kat in ("SID", "STAR"):
            rnav = " (RNAV)" if any(y in ("RNAV", "RNP", "GNSS") for y in reszta) else ""
            return kat, f"{nazwa}{rwy}{rnav}"
        nr = m.group(2).lstrip("0")
        return kat, nazwa + (f" {nr}" if nr and nr not in ("1",) and kat == "GND" else "") + rwy
    return None


if __name__ == "__main__":
    for t in ["AD_2_LFPG_IAC_RWY26L_ILS_Z", "AD_2_LFAC_ADC_01", "AD_2_LFAC_DATA_RWY24_RNP_CODE", "AD_2_LFPG_SID_RWY27L_RNAV", "AD_2_LFPG_PDC_03"]:
        print(t, "->", z_nazwy_pliku(t, t.split("_")[2]))
    print(ladna_nazwa("Standard Departure Chart - Instrument (RNAV 1 SID BASED ON GNSS) RWY 06 - TACLO;ACLO_SERVER_ID;58", "SID"))
    for t in ["ILS OR LOC RWY 33", "RNAV (GPS) Z RWY 04L", "AIRPORT DIAGRAM", "Standard Instrument Departure Chart - ICAO RWY 29",
              "ATC Surveillance Minimum Altitude Chart", "Aerodrome Obstacle Chart - ICAO Type A RWY 11/29",
              "ROBUC THREE (RNAV)", "Instrument Approach Chart - ICAO RNP RWY 15", "Parking/Docking Chart - ICAO", "TAKEOFF MINIMUMS", "Standard Arrival Chart - Instrument (STAR) - ICAO RWY 33", "Standard Departure Chart - Instrument (SID) - ICAO RWY 11 RNAV GNSS"]:
        print(f"{kategoria(t):5} {pasy(t)}  {t}  =>  {ladna_nazwa(t, kategoria(t))}")
