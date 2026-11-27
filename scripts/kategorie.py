"""Klasyfikacja kart w stylu Navigraph: GND (lotnisko/kołowanie), SID, STAR, APP, REF (pozostałe)."""
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
    n = re.sub(r"\s+", " ", nazwa or "").strip()
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
    if len(k) < 3:
        return n
    if kat in ("SID", "STAR") and not re.search(rf"\b{kat}\b", k, re.I):
        k = f"{kat} {k}"
    return k


if __name__ == "__main__":
    for t in ["ILS OR LOC RWY 33", "RNAV (GPS) Z RWY 04L", "AIRPORT DIAGRAM", "Standard Instrument Departure Chart - ICAO RWY 29",
              "ATC Surveillance Minimum Altitude Chart", "Aerodrome Obstacle Chart - ICAO Type A RWY 11/29",
              "ROBUC THREE (RNAV)", "Instrument Approach Chart - ICAO RNP RWY 15", "Parking/Docking Chart - ICAO", "TAKEOFF MINIMUMS", "Standard Arrival Chart - Instrument (STAR) - ICAO RWY 33", "Standard Departure Chart - Instrument (SID) - ICAO RWY 11 RNAV GNSS"]:
        print(f"{kategoria(t):5} {pasy(t)}  {t}  =>  {ladna_nazwa(t, kategoria(t))}")
