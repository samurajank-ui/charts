# Charty – darmowe karty lotniskowe (SID, STAR, APP, lotnisko)

Wpisujesz kod lotniska (ICAO/IATA/nazwa) i dostajesz wszystkie dostępne karty, ułożone i podpisane jak w Navigraph:
**Lotnisko** (aerodrome/parking/ground), **SID**, **STAR**, **APP** (ILS, RNP, VOR…), **Inne** – z filtrem po pasie startowym,
wyszukiwarką, przypinaniem kart, ulubionymi lotniskami i trybem nocnym.

> ⚠️ Tylko do symulacji lotu. Nie do prawdziwej nawigacji.

## Skąd są karty
Wyłącznie z darmowych, oficjalnych źródeł (żadnych kart Jeppesen/Lido):
- **USA** – FAA d-TPP (domena publiczna),
- **Europa** – eAIP poszczególnych krajów (lista w `scripts/zrodla.json`),
- dla pozostałych lotnisk strona podaje link do oficjalnego AIP danego kraju i do ChartFox.

Lista lotnisk do wyszukiwarki: OurAirports (domena publiczna).

## Jak to działa
- `scripts/build.py` pobiera spisy kart, klasyfikuje je (`scripts/kategorie.py`) i zapisuje małe pliki JSON do `site/data/`.
- Same PDF-y nie są kopiowane – strona otwiera je bezpośrednio z serwerów FAA / AIP.
- GitHub Actions (`.github/workflows/aktualizacja.yml`) uruchamia to **codziennie** i publikuje stronę na GitHub Pages,
  więc nowy cykl AIRAC pojawia się automatycznie w dniu wejścia w życie.

## Uruchomienie (jednorazowo)
1. Repozytorium musi być **publiczne** (darmowe GitHub Pages).
2. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. **Actions → Aktualizacja kart → Run workflow**. Po kilku–kilkunastu minutach strona jest pod adresem
   `https://<twoj-login>.github.io/<nazwa-repo>/`.
4. Stan źródeł widać w podsumowaniu każdego uruchomienia (✅/❌) oraz na stronie głównej.

## Lokalnie
```
pip install -r requirements.txt
python scripts/build.py --tylko FAA --limit 20    # szybki test
cd site && python -m http.server 8000             # http://localhost:8000
```

## Dodawanie kraju
Dopisz wpis do `scripts/zrodla.json` (`start` = strona eAIP z listą wydań lub stroną startową wydania,
`prefiksy` = prefiksy ICAO). Crawler sam znajduje aktualne wydanie, strony AD 2 i linki do PDF.
