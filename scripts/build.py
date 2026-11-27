#!/usr/bin/env python3
"""
Buduje bazę kart do folderu site/data:
  data/airports.json      – lista lotnisk do wyszukiwarki
  data/apt/<ICAO>.json    – karty danego lotniska (nazwa, kategoria, pasy, link do PDF)
  data/status.json        – stan źródeł (cykl AIRAC, liczba lotnisk, błędy)

Źródła (tylko darmowe, oficjalne):
  * FAA d-TPP (USA) – plik metadanych XML z listą wszystkich kart
  * eAIP poszczególnych krajów (format Eurocontrol) – crawler z pliku zrodla.json

Uruchomienie:  python scripts/build.py [--tylko FAA,PL] [--limit 5]
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import threading
import time
import traceback
import xml.etree.ElementTree as ET
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
from procedury import z_nazwy_faa, z_pdf  # noqa: E402
from kategorie import FAA, KOLEJNOSC, kategoria, ladna_nazwa, pasy  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "site", "data")
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
S.headers["Accept-Language"] = "en-GB,en;q=0.9"


_watek = threading.local()


def log(*a):
    bufor = getattr(_watek, "bufor", None)
    if bufor is not None:
        bufor.append(" ".join(str(x) for x in a))
    else:
        print(*a, flush=True)


def get(url, tries=3, **kw):
    last = None
    for i in range(tries):
        try:
            r = S.get(url, timeout=kw.pop("timeout", 60), **kw)
            if r.status_code == 404:
                return r
            r.raise_for_status()
            if "charset" not in r.headers.get("content-type", "").lower():
                m = re.search(rb'charset=["\']?([\w-]+)', r.content[:3000])
                r.encoding = m.group(1).decode() if m else "utf-8"
            return r
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


# ---------------------------------------------------------------- AIRAC
REF_AIRAC = dt.date(2025, 1, 23)  # AIRAC 2501


def airac(d: dt.date):
    """Zwraca (data_wejścia, 'RRNN') cyklu obowiązującego w dniu d."""
    n = (d - REF_AIRAC).days // 28
    start = REF_AIRAC + dt.timedelta(days=28 * n)
    idx, first = 1, start
    while (first - dt.timedelta(days=28)).year == start.year:
        first -= dt.timedelta(days=28)
        idx += 1
    return start, f"{start.year % 100:02d}{idx:02d}"


# ---------------------------------------------------------------- FAA d-TPP
def zrodlo_faa(limit=None):
    today = dt.date.today()
    for d in (today, today - dt.timedelta(days=28)):
        start, cyc = airac(d)
        for name in ("d-tpp_Metafile.xml", "d-TPP_Metafile.xml"):
            url = f"https://aeronav.faa.gov/d-tpp/{cyc}/xml_data/{name}"
            try:
                r = get(url, timeout=300)
            except Exception as e:  # noqa: BLE001
                log("  FAA", url, "->", e)
                continue
            log("  FAA", url, "->", r.status_code, len(r.content), "B")
            if r.ok and b"<digital_tpp" in r.content[:5000]:
                return _parsuj_faa(r.content, cyc, start, limit)
    raise RuntimeError("Nie znaleziono pliku metadanych d-TPP")


def _parsuj_faa(xml, cyc, start, limit):
    root = ET.fromstring(xml)
    lotniska = {}
    for state in root.iter("state_code"):
        for city in state.iter("city_name"):
            for apt in city.iter("airport_name"):
                icao = (apt.get("icao_ident") or "").strip() or (apt.get("apt_ident") or "").strip()
                if not icao:
                    continue
                karty = []
                for rec in apt.iter("record"):
                    pdf = (rec.findtext("pdf_name") or "").strip()
                    akcja = (rec.findtext("useraction") or "").strip().upper()
                    if not pdf or akcja == "D" or pdf.upper().startswith("DELETED"):
                        continue
                    nazwa = (rec.findtext("chart_name") or "").strip()
                    kod = (rec.findtext("chart_code") or "").strip().upper()
                    proc = z_nazwy_faa(nazwa) if kod in ("DP", "STAR") else None
                    karty.append({
                        "n": nazwa,
                        "c": FAA.get(kod) or kategoria(nazwa),
                        "r": pasy(nazwa),
                        "k": kod,
                        "u": f"https://aeronav.faa.gov/d-tpp/{cyc}/{pdf}",
                        "s": int(rec.findtext("chartseq") or 0),
                        **({"p": [proc]} if proc else {}),
                    })
                if karty:
                    karty.sort(key=lambda k: (KOLEJNOSC.index(k["c"]), k["s"], k["n"]))
                    lotniska[icao] = {
                        "icao": icao,
                        "nazwa": (apt.get("ID") or "").title(),
                        "miasto": (city.get("ID") or "").title(),
                        "kraj": "US",
                        "karty": karty,
                    }
                if limit and len(lotniska) >= limit:
                    return {"cykl": cyc, "od": start.isoformat(), "lotniska": lotniska}
    return {"cykl": cyc, "od": start.isoformat(), "lotniska": lotniska}


# ---------------------------------------------------------------- eAIP (Eurocontrol)
DATA_W_URL = re.compile(r"(20\d\d)[-_](\d\d)[-_](\d\d)")
KOD_KARTY = re.compile(r"\bAD\s*2[\s.\-_]*[A-Z]{4}[\s.\-_]*\d+(?:[\s.\-_]+\d+)*", re.I)


def _linki(base, html):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for tag, attr in (("a", "href"), ("frame", "src"), ("iframe", "src"), ("area", "href")):
        for t in soup.find_all(tag):
            v = t.get(attr)
            if v and not v.startswith(("javascript:", "mailto:", "#")):
                out.append((urldefrag(urljoin(base, v.strip().replace("\\", "/")))[0], t.get_text(" ", strip=True)))
    # przekierowania <meta refresh> i window.location
    for m in soup.find_all("meta", attrs={"http-equiv": re.compile("refresh", re.I)}):
        c = m.get("content", "")
        if "url=" in c.lower():
            out.append((urljoin(base, c.split("=", 1)[1].strip(" '\"")), ""))
    for m in re.finditer(r"""(?:location(?:\.href)?\s*=|location\.replace\()\s*['"]([^'"]+)['"]""", html):
        out.append((urljoin(base, m.group(1)), ""))
    # adresy zapisane w skryptach (np. menu eAIP generowane przez JavaScript)
    bazy = [base]
    if urlparse(base).path.lower().endswith(".js"):   # eAIP v2: adresy w menu JS są względne do <wydanie>/eAIP/
        katalog = re.sub(r"(v2/)?js/[^/]*$|[^/]*$", "", base, count=1)
        bazy.append(katalog + "eAIP/")
    for m in re.finditer(r"""["']([^"'<>\n]{2,250}?\.(?:html?|js)(?:#[^"'<>\s]*)?)["']""", html):
        for b in bazy:
            out.append((urldefrag(urljoin(b, m.group(1).replace("\\", "/")))[0], ""))
    out = [(u.replace(" ", "%20"), t) for u, t in out]
    return soup, out


def _wybierz_wydanie(url, html, filtr=None):
    """Jeśli strona startowa listuje wydania z datami, zwraca link do obowiązującego (najnowsze <= dziś)."""
    _, linki = _linki(url, html)
    dzis = dt.date.today()
    kandydaci = []
    for u, _t in linki:
        if filtr and not re.search(filtr, u):
            continue
        m = DATA_W_URL.search(urlparse(u).path)
        if not m:
            continue
        try:
            d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if d <= dzis:
            kandydaci.append((d, u))
    if not kandydaci:
        return None
    d, u = max(kandydaci)
    log(f"    wydanie: {d} -> {u}")
    return d, u


def _jest_ad2(u, prefiksy):
    p = urlparse(u).path.upper()
    m = re.search(r"AD[\s_\-.%20]*2[\s_\-.]*(?:%20)*([A-Z]{4})(?![A-Z])", p)
    if m and m.group(1)[:2] in prefiksy and m.group(1) not in ("TEXT",):
        return m.group(1)
    return None


def _jezyk_ok(u):
    p = u.lower()
    return not re.search(r"-(pl|de|fr|es|it|nl|cs|sk|hu|ro|lt|lv|et|fi|sv|no|da)-[a-z]{2}\.html?$", p)


def zrodlo_eaip(cfg, limit=None):
    prefiksy = set(cfg["prefiksy"])
    start = cfg["start"]
    r = get(start)
    log("  start", start, "->", r.status_code, r.url)
    wydanie = _wybierz_wydanie(r.url, r.text, cfg.get("filtr_wydania"))
    od = None
    if wydanie:
        od, url0 = wydanie
        od = od.isoformat()
        url0 = url0.replace(" ", "%20")
    else:
        url0 = r.url
    # Zakres crawla: katalog wydania (lub host)
    zakres = cfg.get("zakres")
    if not zakres:
        m = DATA_W_URL.search(url0)
        zakres = url0[: url0.find("/", m.end()) + 1] if m and "/" in url0[m.end():] else f"{urlparse(url0).scheme}://{urlparse(url0).netloc}/"
    zakres = zakres.replace(" ", "%20")
    log("    zakres crawla:", zakres)

    kolejka, widziane, ad2 = deque([url0]), {url0}, {}
    stron, t0 = 0, time.time()
    budzet = cfg.get("max_sekund", 300)

    def pobierz(u):
        try:
            rr = get(u, tries=2, timeout=30)
            ct = rr.headers.get("content-type", "html")
            if not rr.ok or ("html" not in ct and not urlparse(u).path.lower().endswith(".js")):
                return u, None
            return u, rr
        except Exception as e:  # noqa: BLE001
            log("    !", u, e)
            return u, None

    with ThreadPoolExecutor(8) as ex:
        while kolejka and stron < cfg.get("max_stron", 600) and time.time() - t0 < budzet:
            if limit and len(ad2) >= limit * 3:
                break
            partia = [kolejka.popleft() for _ in range(min(16, len(kolejka)))]
            for u, rr in ex.map(pobierz, partia):
                stron += 1
                if rr is None:
                    continue
                if stron <= 3:
                    log(f"    [{stron}] {u} -> {len(rr.text)} B")
                _, linki = _linki(rr.url, rr.text)
                for v, _t in linki:
                    if v in widziane or not v.startswith(zakres):
                        continue
                    widziane.add(v)
                    icao = _jest_ad2(v, prefiksy)
                    if icao:
                        if re.search(r"\.html?$", v, re.I) and _jezyk_ok(v):
                            lst = ad2.setdefault(icao, [])
                            if len(lst) < 6:
                                lst.append(v)
                        continue
                    path = urlparse(v).path.lower()
                    if re.search(r"\.(pdf|png|jpe?g|gif|css|zip|xml|docx?|xlsx?)$", path) or re.search(r"(jquery|knockout|split|bootstrap)[^/]*\.js$", path):
                        continue
                    if re.search(r"(gen|enr)[\s_\-.]*\d", path) and not re.search(r"menu|toc|index|frame", path):
                        continue
                    if not _jezyk_ok(v):
                        continue
                    kolejka.append(v)
    if not ad2:
        log("    przykładowe linki:", sorted(widziane)[:25])
    log(f"    przejrzano {stron} stron, znaleziono AD 2 dla {len(ad2)} lotnisk")
    for icao, u in list(sorted(ad2.items()))[:2]:
        log(f"      np. {icao}: {u}")
    if not ad2:
        raise RuntimeError("Nie znaleziono stron AD 2")

    wazne = "EPWA EPKK EPGD EGLL EGKK EGCC EHAM EBBR ELLX EFHK ESSA EETN EVRA LOWW LPPT LZIB".split()
    pozycje = sorted(ad2.items(), key=lambda p: (p[0] not in wazne, p[0]))[: limit or None]
    lotniska = {}
    with ThreadPoolExecutor(6) as ex:
        for icao, wynik in zip([p[0] for p in pozycje], ex.map(lambda p: _karty_wiele(*p), pozycje)):
            if wynik and wynik["karty"]:
                wynik["kraj"] = cfg["kraj"]
                lotniska[icao] = wynik
    return {"cykl": airac(dt.date.fromisoformat(od))[1] if od else airac(dt.date.today())[1], "od": od, "lotniska": lotniska}


def _karty_wiele(icao, adresy):
    """Łączy karty ze wszystkich znalezionych stron AD 2 lotniska (eAIP v2 dzieli je na kilka plików)."""
    wynik = None
    for u in adresy:
        w = _karty_ad2(icao, u)
        if not w:
            continue
        if wynik is None:
            wynik = w
            continue
        znane = {k["u"] for k in wynik["karty"]}
        wynik["karty"] += [k for k in w["karty"] if k["u"] not in znane]
        wynik["nazwa"] = wynik["nazwa"] or w["nazwa"]
    if wynik:
        wynik["karty"].sort(key=lambda k: (KOLEJNOSC.index(k["c"]), _klucz_kodu(k["k"]), k["n"]))
    return wynik


def _czysc(t):
    t = re.sub(r"\s+", " ", t or "").strip(" -–|:;,")
    return t


def _karty_ad2(icao, url):
    try:
        r = get(url)
    except Exception as e:  # noqa: BLE001
        log("    !", icao, e)
        return None
    if not r.ok:
        return None
    soup = BeautifulSoup(r.text, "lxml")
    nazwa_lot = ""
    for h in soup.find_all(re.compile("^(h[1-4]|title|p|span|div)$"), limit=60):
        t = h.get_text(" ", strip=True)
        m = re.search(rf"{icao}\s*[-–—]\s*([^\n]{{3,80}})", t)
        if m:
            nazwa_lot = _czysc(m.group(1)).title()
            break
    karty, widziane = [], set()
    # linki do PDF: zwykłe href albo ukryte w innych atrybutach (onclick, data-*, javascript:)
    kandydaci = []
    for el in soup.find_all(True):
        for at, val in el.attrs.items():
            if not isinstance(val, str) or ".pdf" not in val.lower():
                continue
            m = re.search(r"""([^"'\s()]+\.pdf)(?:[?#][^"'\s()]*)?""", val, re.I)
            if m:
                kandydaci.append((el, m.group(1)))
    for a, href in kandydaci:
        u = urljoin(r.url, href.strip().replace("\\", "/"))
        if u in widziane:
            continue
        widziane.add(u)
        wiersz = a.find_parent("tr")
        tekst = wiersz.get_text(" | ", strip=True) if wiersz else a.get_text(" ", strip=True)
        tekst = _czysc(tekst)
        kod_m = KOD_KARTY.search(tekst) or KOD_KARTY.search(a.get_text(" ", strip=True))
        kod = _czysc(kod_m.group(0)) if kod_m else ""
        opis = _czysc(KOD_KARTY.sub("", tekst).replace("|", " - "))
        opis = re.sub(r"(\s*-\s*){2,}", " - ", opis).strip(" -")
        if not opis or len(opis) < 3:
            opis = _czysc(a.get_text(" ", strip=True)) or os.path.basename(urlparse(u).path)
        kat = kategoria(opis)
        karty.append({"n": ladna_nazwa(opis, kat), "o": opis, "c": kat, "r": pasy(opis), "k": kod, "u": u})
    if not karty:
        log(f"      {icao}: 0 kart na {r.url} ({len(r.text)} B, title={soup.title.get_text(strip=True)[:60] if soup.title else ''})")
    karty.sort(key=lambda k: (KOLEJNOSC.index(k["c"]), _klucz_kodu(k["k"]), k["n"]))
    return {"icao": icao, "nazwa": nazwa_lot, "miasto": "", "karty": karty, "zrodlo_url": r.url}


def _klucz_kodu(k):
    return [int(x) for x in re.findall(r"\d+", k)[1:]] or [9999]


# ---------------------------------------------------------------- procedury SID/STAR z PDF
CACHE = os.path.join(ROOT, "cache", "procedury.json")


def dodaj_procedury(lotniska, cache):
    """Dla kart SID/STAR bez nazw procedur czyta PDF i dopisuje oznaczenia w formie MCDU (pole 'p')."""
    zadania = [k for l in lotniska.values() for k in l["karty"] if k["c"] in ("SID", "STAR") and "p" not in k]
    nowe = [k["u"] for k in zadania if k["u"] not in cache]
    log(f"    procedury: {len(zadania)} kart SID/STAR, {len(nowe)} PDF do przeczytania")

    def czytaj(u):
        try:
            r = get(u, timeout=90)
            return u, z_pdf(r.content) if r.ok else []
        except Exception as e:  # noqa: BLE001
            log("    ! PDF", u, e)
            return u, None

    with ThreadPoolExecutor(8) as ex:
        for u, wynik in ex.map(czytaj, sorted(set(nowe))):
            if wynik is not None:
                cache[u] = wynik
    for k in zadania:
        if cache.get(k["u"]):
            k["p"] = cache[k["u"]]


# ---------------------------------------------------------------- lista lotnisk (OurAirports, public domain)
def lista_lotnisk():
    try:
        r = get("https://davidmegginson.github.io/ourairports-data/airports.csv", timeout=120)
        out = {}
        for w in csv.DictReader(io.StringIO(r.text)):
            icao = (w.get("icao_code") or w.get("gps_code") or w.get("ident") or "").strip().upper()
            if not re.fullmatch(r"[A-Z]{4}", icao):
                continue
            if w.get("type") not in ("large_airport", "medium_airport", "small_airport"):
                continue
            out[icao] = {
                "nazwa": w.get("name", ""), "miasto": w.get("municipality", ""),
                "kraj": w.get("iso_country", ""), "iata": (w.get("iata_code") or "").strip(),
                "typ": w.get("type"),
            }
        log(f"  OurAirports: {len(out)} lotnisk")
        return out
    except Exception as e:  # noqa: BLE001
        log("  OurAirports niedostępne:", e)
        return {}


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tylko", help="lista id źródeł, np. FAA,PL")
    ap.add_argument("--limit", type=int, help="maks. lotnisk na źródło (test)")
    ap.add_argument("--bez-pdf", action="store_true", help="nie czytaj PDF (bez nazw procedur)")
    ap.add_argument("--zrodla", default=os.path.join(ROOT, "scripts", "zrodla.json"), help="plik z listą eAIP")
    a = ap.parse_args()

    with open(a.zrodla, encoding="utf-8") as f:
        zrodla = json.load(f)
    tylko = set(a.tylko.split(",")) if a.tylko else None

    os.makedirs(os.path.join(OUT, "apt"), exist_ok=True)
    baza = lista_lotnisk()
    try:
        with open(CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:  # noqa: BLE001
        cache = {}
    status, wszystkie = [], {}

    lista = [{"id": "FAA", "nazwa": "FAA d-TPP (USA)", "typ": "faa"}] + zrodla
    lista = [z for z in lista if not tylko or z["id"] in tylko]

    def przetworz(z):
        _watek.bufor = [f"== {z['id']}: {z['nazwa']}"]
        t0 = time.time()
        try:
            wynik = zrodlo_faa(a.limit) if z.get("typ") == "faa" else zrodlo_eaip(z, a.limit)
            if z.get("typ") != "faa" and not a.bez_pdf:
                dodaj_procedury(wynik["lotniska"], cache)
            n_kart = sum(len(l["karty"]) for l in wynik["lotniska"].values())
            log(f"   OK: {len(wynik['lotniska'])} lotnisk, {n_kart} kart, cykl {wynik['cykl']} ({time.time()-t0:.0f}s)")
            st = {"id": z["id"], "nazwa": z["nazwa"], "ok": True, "cykl": wynik["cykl"], "od": wynik["od"],
                  "lotnisk": len(wynik["lotniska"]), "kart": n_kart}
        except Exception as e:  # noqa: BLE001
            log(traceback.format_exc())
            wynik, st = None, {"id": z["id"], "nazwa": z["nazwa"], "ok": False, "blad": str(e)[:300]}
        bufor, _watek.bufor = _watek.bufor, None
        print("\n".join(bufor), flush=True)
        return z, wynik, st

    with ThreadPoolExecutor(6) as ex:
        for z, wynik, st in ex.map(przetworz, lista):
            status.append(st)
            if wynik:
                for icao, l in wynik["lotniska"].items():
                    l["zrodlo"] = z["nazwa"]
                    l["cykl"] = wynik["cykl"]
                    l["od"] = wynik["od"]
                    wszystkie.setdefault(icao, l)

    # pamięć podręczna procedur: tylko adresy z bieżącej bazy (stare cykle wypadają)
    aktualne = {k["u"] for l in wszystkie.values() for k in l["karty"]}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump({u: v for u, v in cache.items() if u in aktualne}, f, separators=(",", ":"))

    # zapis kart
    for icao, l in wszystkie.items():
        b = baza.get(icao, {})
        l["nazwa"] = b.get("nazwa") or l.get("nazwa") or icao
        l["miasto"] = b.get("miasto") or l.get("miasto", "")
        l["kraj"] = b.get("kraj") or l.get("kraj", "")
        l["iata"] = b.get("iata", "")
        with open(os.path.join(OUT, "apt", f"{icao}.json"), "w", encoding="utf-8") as f:
            json.dump(l, f, ensure_ascii=False, separators=(",", ":"))

    # lista do wyszukiwarki: [icao, iata, nazwa, miasto, kraj, liczba_kart]
    wiersze = []
    for icao in sorted(set(baza) | set(wszystkie)):
        b = baza.get(icao, {})
        l = wszystkie.get(icao)
        if not l and b.get("typ") == "small_airport":
            continue
        wiersze.append([icao, b.get("iata", ""), (l or b).get("nazwa", ""), (l or b).get("miasto", ""),
                        (l or b).get("kraj", ""), len(l["karty"]) if l else 0])
    with open(os.path.join(OUT, "airports.json"), "w", encoding="utf-8") as f:
        json.dump(wiersze, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(OUT, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"zbudowano": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                   "airac": airac(dt.date.today())[1], "zrodla": status}, f, ensure_ascii=False, indent=1)
    log(f"Zapisano {len(wszystkie)} lotnisk z kartami, {len(wiersze)} w wyszukiwarce.")
    if not wszystkie:
        sys.exit(1)


if __name__ == "__main__":
    main()
