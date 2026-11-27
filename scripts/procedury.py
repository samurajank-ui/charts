"""Nazwy procedur SID/STAR w formie jak w MCDU (ARINC 424, max 6 znaków), np. ROPUV 1W -> ROPU1W, ROBUC THREE -> ROBUC3."""
import io
import re

CYFRY = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5, "SIX": 6, "SEVEN": 7, "EIGHT": 8, "NINE": 9, "ZERO": 0}
FONETYKA = {w: w[0] for w in (
    "ALFA ALPHA BRAVO CHARLIE DELTA ECHO FOXTROT GOLF HOTEL INDIA JULIET JULIETT KILO LIMA MIKE NOVEMBER "
    "OSCAR PAPA QUEBEC ROMEO SIERRA TANGO UNIFORM VICTOR WHISKEY WHISKY XRAY X-RAY YANKEE ZULU").split()}
# słowa, które wyglądają jak punkt, ale nim nie są
STOP = set("""RWY RWYS ICAO AIP AMDT AIRAC FL FT NM KT DME VOR NDB ILS LOC RNAV RNP GNSS GPS SID STAR APP IAF IF FAF MAP MSA TA
TL ATC ACC TWR APRON PAGE CHART AD ENR GEN SUP NIL MAX MIN NOTE SEE AND OR TO FROM VIA THE ALT HGT ELEV FIG TYPE CAT MHZ KHZ
CTR TMA CTA FIR UIR SPEED IAS HDG TRK MAG VAR WEF EFF DATE LAT LONG QNH QFE""".split())

_MCDU_RE = re.compile(r"\b([A-Z]{2,5})\s?([1-9])\s?([A-Z])\b")
_SLOWNIE_RE = re.compile(r"\b([A-Z]{2,5})\s+(" + "|".join(CYFRY) + r")\s+(" + "|".join(FONETYKA).replace("-", r"\-") + r")\b")


def mcdu(punkt: str, cyfra, litera: str = "") -> str:
    punkt = punkt.upper()
    reszta = f"{cyfra}{litera}".upper()
    if len(punkt) + len(reszta) > 6:
        punkt = punkt[: 6 - len(reszta)]
    return punkt + reszta


def z_nazwy_faa(nazwa: str):
    """'ROBUC THREE (RNAV)' -> 'ROBUC3'. Zwraca None, gdy nazwa nie pasuje do schematu."""
    n = re.sub(r"\(.*?\)", " ", nazwa.upper())
    m = re.match(r"\s*([A-Z]{2,5})\s+(" + "|".join(CYFRY) + r")\b", n)
    if m:
        return mcdu(m.group(1), CYFRY[m.group(2)])
    return None


def z_tekstu(tekst: str) -> list:
    """Wyszukuje oznaczenia procedur w tekście karty (z PDF). Wymaga, aby punkt występował też samodzielnie na karcie."""
    t = tekst.upper()
    slowa = set(re.findall(r"\b[A-Z]{2,5}\b", t))
    znalezione = {}
    for m in _SLOWNIE_RE.finditer(t):
        p = m.group(1)
        if p in STOP:
            continue
        znalezione.setdefault(mcdu(p, CYFRY[m.group(2)], FONETYKA[m.group(3)]), 0)
        znalezione[mcdu(p, CYFRY[m.group(2)], FONETYKA[m.group(3)])] += 2
    for m in _MCDU_RE.finditer(t):
        p, c, l = m.groups()
        if p in STOP or (len(p) < 5 and p not in slowa):
            continue
        # 'ROPU1W' (skrócony kod) – zapisany już w formie MCDU
        k = mcdu(p, c, l)
        znalezione[k] = znalezione.get(k, 0) + (2 if p in slowa else 1)
    # odrzuć pojedyncze, niepotwierdzone trafienia gdy są lepsze
    wynik = [k for k, v in znalezione.items() if v >= 2 or len(znalezione) <= 3]
    return sorted(set(wynik))


def z_pdf(dane: bytes) -> list:
    from pypdf import PdfReader
    try:
        r = PdfReader(io.BytesIO(dane))
        tekst = "\n".join((p.extract_text() or "") for p in r.pages[:4])
    except Exception:  # noqa: BLE001
        return []
    return z_tekstu(tekst)


if __name__ == "__main__":
    for n in ["ROBUC THREE (RNAV)", "DEEZZ FIVE (RNAV)", "KENNEDY FIVE", "GREKI SEVEN"]:
        print(n, "->", z_nazwy_faa(n))
    przyklad = """STANDARD ARRIVAL CHART - INSTRUMENT (STAR) - ICAO  RWY 33
    ROPUV 1W  ROPUV ONE WHISKEY ARRIVAL   SORIX 1W   AGAVA 1W  RWY 33  FL 100  AMDT 3/25
    ROPUV  SORIX  AGAVA  WA412  WA413   ICAO 2B   NOTE 1A"""
    print(z_tekstu(przyklad))
