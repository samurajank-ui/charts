#!/usr/bin/env python3
"""Pomocnik: pobiera podane adresy i wypisuje status, tytuł, linki (href | tekst) i początek tekstu.
Użycie: python scripts/diagnoza.py URL [URL ...]   (filtr linków: --grep wzorzec)"""
import re
import sys
import warnings
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")
args = sys.argv[1:]
wzor = None
if "--grep" in args:
    i = args.index("--grep")
    wzor = re.compile(args[i + 1], re.I)
    del args[i:i + 2]
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
for u in args:
    print("=" * 100)
    print("URL:", u)
    try:
        r = S.get(u, timeout=60)
    except Exception as e:  # noqa: BLE001
        print("BŁĄD:", e)
        continue
    print("STATUS:", r.status_code, "| FINAL:", r.url, "| TYPE:", r.headers.get("content-type"), "| BYTES:", len(r.content))
    if r.content.startswith(b"%PDF"):
        sys.path.insert(0, "scripts")
        from tytuly import analiza, tekst_pdf
        t = tekst_pdf(r.content, stron=3, ocr=True)
        print("PDF TEXT:", re.sub(r"\s+", " ", t)[:3000])
        for kat in ("APP", "GND", "REF", "SID"):
            print("  ANALIZA", kat, analiza(t, kat))
        continue
    if u.lower().split("?")[0].endswith((".js", ".json", ".xml")):
        t = r.text
        if wzor:
            for m in wzor.finditer(t):
                print("  ...", t[max(0, m.start() - 300): m.end() + 300].replace("\n", " "))
                if m.start() > 2_000_000:
                    break
        print("RAW:", t[:5000])
        continue
    if "html" not in (r.headers.get("content-type") or "") and not r.text.lstrip().startswith("<"):
        continue
    s = BeautifulSoup(r.content, "lxml")
    print("TITLE:", s.title.get_text(strip=True) if s.title else "")
    n = 0
    for tag, at in (("a", "href"), ("frame", "src"), ("iframe", "src"), ("form", "action"), ("option", "value")):
        for t in s.find_all(tag):
            v = t.get(at)
            if not v:
                continue
            line = f"  <{tag}> {urljoin(r.url, v)} | {t.get_text(' ', strip=True)[:90]}"
            if wzor and not wzor.search(line):
                continue
            n += 1
            if n <= 250:
                print(line)
    print(f"  (linków: {n})")
    for m in re.finditer(r"""(?:location(?:\.href)?\s*=|window\.open\(|location\.replace\()\s*['"]([^'"]+)""", r.text):
        print("  JS ->", m.group(1))
    q = sorted(set(re.findall(r"""["']([^"'<>\s]{3,200}\.(?:html?|pdf|js|json|xml|aspx|php)(?:\?[^"'<>\s]*)?)["']""", r.text)))
    if wzor:
        q = [x for x in q if wzor.search(x)] or q[:40]
    print("  CYTOWANE ADRESY:", q[:120])
    for sc in s.find_all("script", src=True):
        print("  SCRIPT:", urljoin(r.url, sc["src"]))
    print("TEXT:", re.sub(r"\s+", " ", s.get_text(" ", strip=True))[:1200])
