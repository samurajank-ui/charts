"use strict";
const $ = (s) => document.querySelector(s);
const KAT = {
  ALL: { n: "Wszystkie", kol: "#3d9bff" },
  GND: { n: "Lotnisko", kol: "var(--GND)" },
  SID: { n: "SID", kol: "var(--SID)" },
  STAR: { n: "STAR", kol: "var(--STAR)" },
  APP: { n: "APP", kol: "var(--APP)" },
  REF: { n: "Inne", kol: "var(--REF)" },
  PIN: { n: "★ Przypięte", kol: "#ffd166" },
};
const KOLEJ = ["GND", "SID", "STAR", "APP", "REF"];
const LS = {
  get: (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set: (k, v) => localStorage.setItem(k, JSON.stringify(v)),
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let LOTNISKA = null, AIP = {}, apt = null, zakladka = "ALL", pas = null, widoczne = [], aktUrl = null;

// ---------------- dane
async function json(u) { const r = await fetch(u, { cache: "no-cache" }); if (!r.ok) throw new Error(r.status); return r.json(); }
async function ladujLotniska() {
  if (!LOTNISKA) LOTNISKA = await json("data/airports.json").catch(() => []);
  return LOTNISKA;
}

// ---------------- wyszukiwarka
function szukaj(q) {
  q = q.trim().toUpperCase();
  if (!q || !LOTNISKA) return [];
  const wyn = [];
  for (const w of LOTNISKA) {
    const [icao, iata, nazwa, miasto] = w;
    let p = 0;
    if (icao === q) p = 100; else if (iata === q) p = 90;
    else if (icao.startsWith(q)) p = 60;
    else if (q.length >= 3) {
      const N = (nazwa + " " + miasto).toUpperCase();
      if (N.startsWith(q)) p = 40; else if (N.includes(q)) p = 30;
    }
    if (p) wyn.push([p + (w[5] ? 5 : 0), w]);
  }
  return wyn.sort((a, b) => b[0] - a[0] || a[1][0].localeCompare(b[1][0])).slice(0, 30).map((x) => x[1]);
}
let podp = [], podpAkt = 0, czekaFiltr = null;
function pokazPodpowiedzi() {
  const ul = $("#podpowiedzi");
  podp = szukaj($("#q").value); podpAkt = 0;
  if (!podp.length) { ul.hidden = true; return; }
  ul.innerHTML = podp.map((w, i) => `<li data-i="${i}" class="${i ? "" : "akt"}"><span class="kod">${esc(w[0])}</span>
    <span>${esc(w[2])}<span class="szary maly"> ${esc([w[3], w[4]].filter(Boolean).join(", "))}${w[1] ? " · " + esc(w[1]) : ""}</span></span>
    <span class="ile">${w[5] ? w[5] + " kart" : "brak kart"}</span></li>`).join("");
  ul.hidden = false;
}
$("#q").addEventListener("focus", ladujLotniska);
$("#q").addEventListener("input", async () => { await ladujLotniska(); pokazPodpowiedzi(); });
$("#q").addEventListener("keydown", (e) => {
  const ul = $("#podpowiedzi");
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault(); if (!podp.length) return;
    podpAkt = (podpAkt + (e.key === "ArrowDown" ? 1 : -1) + podp.length) % podp.length;
    ul.querySelectorAll("li").forEach((li, i) => li.classList.toggle("akt", i === podpAkt));
    ul.children[podpAkt].scrollIntoView({ block: "nearest" });
  } else if (e.key === "Enter") {
    const v = $("#q").value.trim().toUpperCase();
    const [kod, ...reszta] = v.split(/\s+/);
    if (reszta.length && /^[A-Z0-9]{3,4}$/.test(kod)) {   // np. "EPWA ROPU1W" – lotnisko + filtr
      const w = (LOTNISKA || []).find((x) => x[0] === kod || x[1] === kod);
      czekaFiltr = reszta.join(" "); idz(w ? w[0] : kod); return;
    }
    const w = podp[podpAkt];
    idz(w ? w[0] : v);
  } else if (e.key === "Escape") { ul.hidden = true; $("#q").blur(); }
});
$("#podpowiedzi").addEventListener("mousedown", (e) => {
  const li = e.target.closest("li"); if (li) { e.preventDefault(); idz(podp[+li.dataset.i][0]); }
});
$("#q").addEventListener("blur", () => setTimeout(() => ($("#podpowiedzi").hidden = true), 100));

function idz(icao) {
  if (!icao) return;
  $("#podpowiedzi").hidden = true; $("#q").value = ""; $("#q").blur();
  location.hash = icao.toUpperCase();
}

// ---------------- lotnisko
async function otworzLotnisko(icao, kartaIdx) {
  if (!apt || apt.icao !== icao) {
    zakladka = "ALL"; pas = null; $("#filtr").value = "";
    try { apt = await json(`data/apt/${encodeURIComponent(icao)}.json`); }
    catch { await ladujLotniska(); const w = (LOTNISKA || []).find((x) => x[0] === icao);
      apt = { icao, nazwa: w ? w[2] : "", miasto: w ? w[3] : "", kraj: w ? w[4] : "", iata: w ? w[1] : "", karty: [], brak: true }; }
    apt.karty.forEach((k, i) => (k.i = i));
    zamknijPodglad();
    zapiszOstatnie(icao);
  }
  $("#start").hidden = true; $("#lotnisko").hidden = false;
  $("#apt-icao").textContent = apt.icao;
  $("#apt-iata").textContent = apt.iata || "";
  $("#apt-nazwa").textContent = apt.nazwa || "";
  $("#apt-info").innerHTML = apt.brak ? esc([apt.miasto, apt.kraj].filter(Boolean).join(", ")) :
    `${esc([apt.miasto, apt.kraj].filter(Boolean).join(", "))} · ${esc(apt.zrodlo)} · AIRAC ${esc(apt.cykl)}${apt.od ? " (od " + esc(apt.od) + ")" : ""}`;
  document.title = `${apt.icao} – Charty`;
  odswiezGwiazdke();
  if (czekaFiltr != null) {
    zakladka = "ALL"; pas = null; $("#filtr").value = czekaFiltr; czekaFiltr = null;
    rysujZakladki(); rysujPasy(); rysujListe();
    if (widoczne.length) { pokazKarte(widoczne[0]); return; }
  }
  rysujZakladki(); rysujPasy(); rysujListe();
  if (kartaIdx != null && apt.karty[kartaIdx]) pokazKarte(apt.karty[kartaIdx], false);
  else if (window.innerWidth > 800) {
    const adc = apt.karty.find((k) => k.c === "GND");
    if (adc && aktUrl == null) pokazKarte(adc, false);
  }
}

function pinezki() { return LS.get("pin", {})[apt.icao] || []; }
function liczba(kat) {
  if (kat === "ALL") return apt.karty.length;
  if (kat === "PIN") return pinezki().length;
  return apt.karty.filter((k) => k.c === kat).length;
}
function rysujZakladki() {
  const kats = ["ALL", ...KOLEJ, ...(pinezki().length ? ["PIN"] : [])];
  $("#zakladki").innerHTML = kats.filter((k) => k === "ALL" || liczba(k)).map((k) =>
    `<button data-k="${k}" class="${k === zakladka ? "akt" : ""}" style="--kol:${KAT[k].kol}">${KAT[k].n}<span class="n">${liczba(k)}</span></button>`).join("");
}
$("#zakladki").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  zakladka = b.dataset.k; pas = null; rysujZakladki(); rysujPasy(); rysujListe();
});

function wZakladce() {
  if (zakladka === "ALL") return apt.karty;
  if (zakladka === "PIN") { const p = pinezki(); return apt.karty.filter((k) => p.includes(k.u)); }
  return apt.karty.filter((k) => k.c === zakladka);
}
function rysujPasy() {
  const s = new Set(); wZakladce().forEach((k) => (k.r || []).forEach((r) => s.add(r)));
  const lista = [...s].sort((a, b) => parseInt(a) - parseInt(b) || a.localeCompare(b));
  $("#pasy").innerHTML = lista.length > 1 ? lista.map((r) => `<button data-r="${r}" class="${r === pas ? "akt" : ""}">RWY ${r}</button>`).join("") : "";
}
$("#pasy").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  pas = pas === b.dataset.r ? null : b.dataset.r; rysujPasy(); rysujListe();
});
$("#filtr").addEventListener("input", rysujListe);

function rysujListe() {
  const f = $("#filtr").value.trim().toUpperCase().split(/\s+/).filter(Boolean);
  widoczne = wZakladce().filter((k) => (!pas || (k.r || []).includes(pas)) &&
    f.every((t) => (k.n + " " + (k.k || "") + " " + (k.p || []).join(" ") + " " + (k.r || []).map((r) => "RWY" + r + " " + r).join(" ")).toUpperCase().includes(t)));
  const piny = pinezki();
  // grupowanie: w "Wszystkie" wg kategorii, w SID/STAR/APP wg pasa
  const grupy = new Map();
  for (const k of widoczne) {
    let g;
    if (zakladka === "ALL" || zakladka === "PIN") g = KAT[k.c].n;
    else if (["SID", "STAR", "APP"].includes(zakladka)) g = k.r && k.r.length ? "RWY " + k.r.join(" / ") : "Ogólne";
    else g = "";
    if (!grupy.has(g)) grupy.set(g, []);
    grupy.get(g).push(k);
  }
  let klucze = [...grupy.keys()];
  if (["SID", "STAR", "APP"].includes(zakladka))
    klucze.sort((a, b) => (a === "Ogólne") - (b === "Ogólne") || (parseInt(a.slice(4)) || 0) - (parseInt(b.slice(4)) || 0) || a.localeCompare(b));
  widoczne = klucze.flatMap((g) => grupy.get(g));
  $("#lista").innerHTML = klucze.map((g) => (g ? `<li class="grupa">${esc(g)}</li>` : "") + grupy.get(g).map((k) => `
    <li class="k ${k.u === aktUrl ? "akt" : ""}" data-i="${k.i}" style="--kol:${KAT[k.c].kol}">
      <div class="t">${k.p && k.p.length ? `<div class="proc">${procHtml(k.p, f)}</div>` : ""}
        <div class="nazwa ${k.p && k.p.length ? "druga" : ""}" title="${esc(k.o || k.n)}">${esc(k.n)}</div>
        <div class="pod"><span class="znacznik">${KAT[k.c].n.toUpperCase()}</span>${k.k ? `<span>${esc(k.k)}</span>` : ""}
        ${(k.r || []).map((r) => `<span class="rw">${esc(r)}</span>`).join("")}</div></div>
      <button class="pin ${piny.includes(k.u) ? "on" : ""}" data-pin="${k.i}" title="Przypnij">★</button>
    </li>`).join("")).join("");
  const brak = $("#brak");
  if (apt.brak || !apt.karty.length) {
    const pref = Object.keys(AIP).filter((p) => apt.icao.startsWith(p)).sort((a, b) => b.length - a.length)[0];
    brak.innerHTML = `Nie mamy jeszcze kart dla <b>${esc(apt.icao)}</b> w automatycznej bazie.` +
      (pref ? `<a href="${esc(AIP[pref][1])}" target="_blank" rel="noopener">Oficjalny AIP: ${esc(AIP[pref][0])} ↗</a>` : "") +
      `<a href="https://chartfox.org/${esc(apt.icao)}" target="_blank" rel="noopener">Sprawdź w ChartFox ↗</a>`;
    brak.hidden = false;
  } else if (!widoczne.length) { brak.textContent = "Brak kart pasujących do filtra."; brak.hidden = false; }
  else brak.hidden = true;
}
$("#lista").addEventListener("click", (e) => {
  const pin = e.target.closest("[data-pin]");
  if (pin) { e.stopPropagation(); przypnij(apt.karty[+pin.dataset.pin]); return; }
  const li = e.target.closest(".k"); if (li) pokazKarte(apt.karty[+li.dataset.i]);
});

// nazwy procedur (MCDU); pasujące do filtra – wyróżnione i na początku
function procHtml(p, f) {
  const traf = (x) => f.some((t) => x.includes(t));
  const lista = [...p].sort((a, b) => traf(b) - traf(a));
  const max = 8, pokaz = lista.slice(0, max);
  return pokaz.map((x) => `<span class="${traf(x) ? "hit" : ""}">${esc(x)}</span>`).join("") +
    (lista.length > max ? `<span class="wiecej">+${lista.length - max}</span>` : "");
}

function przypnij(k) {
  const all = LS.get("pin", {}); const p = all[apt.icao] || [];
  all[apt.icao] = p.includes(k.u) ? p.filter((u) => u !== k.u) : [...p, k.u];
  LS.set("pin", all);
  if (zakladka === "PIN" && !all[apt.icao].length) zakladka = "ALL";
  rysujZakladki(); rysujListe();
}

// ---------------- podgląd
function zamknijPodglad() {
  aktUrl = null; document.body.classList.remove("karta");
  $("#pasek").hidden = true; $("#pdf").hidden = true; $("#pdf").removeAttribute("src"); $("#pdf").dataset.u = "";
  $("#pusto").hidden = false; $("#powitanie").hidden = !!apt; $("#wybierz").hidden = !apt;
}
function pokazKarte(k, hash = true) {
  aktUrl = k.u;
  $("#pasek").hidden = false; $("#pusto").hidden = true;
  const ifr = $("#pdf"); ifr.hidden = false;
  if (ifr.dataset.u !== k.u) { ifr.src = k.u + "#view=FitH"; ifr.dataset.u = k.u; }
  $("#k-nazwa").textContent = k.p && k.p.length ? `${k.p.join(" · ")} — ${k.n}` : k.n;
  $("#k-kod").textContent = [KAT[k.c].n, k.k].filter(Boolean).join(" · ");
  $("#otworz").href = k.u;
  document.body.classList.add("karta");
  document.querySelectorAll("#lista .k").forEach((li) => li.classList.toggle("akt", +li.dataset.i === k.i));
  const li = document.querySelector(`#lista .k[data-i="${k.i}"]`); if (li) li.scrollIntoView({ block: "nearest" });
  if (hash) history.replaceState(null, "", `#${apt.icao}/${k.i}`);
}
function krok(d) {
  if (!widoczne.length) return;
  const i = widoczne.findIndex((k) => k.u === aktUrl);
  pokazKarte(widoczne[Math.max(0, Math.min(widoczne.length - 1, i < 0 ? 0 : i + d))]);
}
$("#poprz").onclick = () => krok(-1);
$("#nast").onclick = () => krok(1);
$("#wstecz").onclick = () => document.body.classList.remove("karta");
$("#noc").onclick = () => { document.body.classList.toggle("noc"); LS.set("noc", document.body.classList.contains("noc")); };
if (LS.get("noc", false)) document.body.classList.add("noc");

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input")) return;
  if (e.key === "/") { e.preventDefault(); $("#q").focus(); }
  else if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); krok(1); }
  else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); krok(-1); }
  else if (e.key.toLowerCase() === "n") $("#noc").click();
  else if (apt && /^[1-6]$/.test(e.key)) {
    const b = $("#zakladki").children[+e.key - 1]; if (b) b.click();
  }
});

// ---------------- ulubione / ostatnie
function zapiszOstatnie(icao) { LS.set("ost", [icao, ...LS.get("ost", []).filter((x) => x !== icao)].slice(0, 12)); }
function odswiezGwiazdke() {
  const on = LS.get("fav", []).includes(apt.icao);
  $("#gwiazdka").textContent = on ? "★" : "☆";
  $("#gwiazdka").title = on ? "Usuń z ulubionych" : "Dodaj do ulubionych";
}
$("#gwiazdka").onclick = () => {
  const f = LS.get("fav", []);
  LS.set("fav", f.includes(apt.icao) ? f.filter((x) => x !== apt.icao) : [...f, apt.icao]);
  odswiezGwiazdke();
};
function rysujStart() {
  const chip = (x) => `<a class="chip" href="#${esc(x)}">${esc(x)}</a>`;
  $("#ulubione").innerHTML = LS.get("fav", []).map(chip).join("") || '<span class="szary maly">Gwiazdka ☆ przy lotnisku dodaje je tutaj.</span>';
  $("#ostatnie").innerHTML = LS.get("ost", []).map(chip).join("") || '<span class="szary maly">—</span>';
}

// ---------------- routing
async function trasa() {
  const [icao, idx] = decodeURIComponent(location.hash.slice(1)).toUpperCase().split("/");
  if (!icao) {
    apt = null; zamknijPodglad();
    $("#start").hidden = false; $("#lotnisko").hidden = true; document.title = "Charty – darmowe karty lotniskowe";
    rysujStart(); return;
  }
  if (!apt || apt.icao !== icao) aktUrl = null;
  await otworzLotnisko(icao, idx !== undefined && idx !== "" ? +idx : null);
}
window.addEventListener("hashchange", trasa);

(async () => {
  AIP = await json("aip-linki.json").catch(() => ({}));
  json("data/status.json").then((s) => {
    $("#zrodla").innerHTML = s.zrodla.map((z) => `<li><span class="${z.ok ? "ok" : "zle"}">${z.ok ? "●" : "○"}</span>
      <span>${esc(z.nazwa)}${z.ok ? ` <span class="szary">· ${z.lotnisk} lotnisk · AIRAC ${esc(z.cykl)}</span>` : ' <span class="szary">· chwilowo niedostępne</span>'}</span></li>`).join("") +
      `<li class="szary maly">Aktualizacja: ${esc(s.zbudowano)}</li>`;
  }).catch(() => {});
  trasa();
})();
