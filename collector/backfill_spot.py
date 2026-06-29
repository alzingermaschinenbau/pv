#!/usr/bin/env python3
# Einmalig: historische Boersenpreise (DE-LU) von Energy-Charts laden und nach
# pv_spot schreiben. Danach zeigt der PDF-Bericht die Negativpreis-Stunden auch
# rueckwirkend (2024/2025).
#
# Im collector-Ordner ausfuehren (.env mit SUPABASE_URL + SUPABASE_SERVICE_KEY
# muss daneben liegen). Standard-Start 2024-01-01, optional anderes Datum:
#   python backfill_spot.py
#   python backfill_spot.py 2024-01-01

import os, sys, datetime as dt, requests

START = sys.argv[1] if len(sys.argv) > 1 else "2024-01-01"
BZN   = os.getenv("SPOT_BZN", "DE-LU")

# .env einfach einlesen (ohne Zusatzpaket)
_envp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_envp):
    for _line in open(_envp, encoding="utf-8"):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, v = _line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_SERVICE_KEY")
if not URL or not KEY:
    raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY fehlen (.env pruefen).")
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Content-Type": "application/json"}


def months(start):
    y, m, _ = map(int, start.split("-"))
    cur = dt.date(y, m, 1)
    today = dt.date.today()
    while cur <= today:
        nxt = dt.date(cur.year + 1, 1, 1) if cur.month == 12 else dt.date(cur.year, cur.month + 1, 1)
        end = min(nxt, today + dt.timedelta(days=1))
        yield cur.isoformat(), end.isoformat()
        cur = nxt


total = 0
print(f"Backfill Boersenpreise {BZN} ab {START} ...\n")
for s, e in months(START):
    url = f"https://api.energy-charts.info/price?bzn={BZN}&start={s}&end={e}"
    try:
        r = requests.get(url, timeout=30); r.raise_for_status(); j = r.json()
    except Exception as ex:                                   # noqa: BLE001
        print(f"  ! {s[:7]}: Abruf-Fehler {ex}"); continue
    secs = j.get("unix_seconds") or []
    prices = j.get("price") or []
    rows = [{"slot": dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(),
             "price": round(p / 10.0, 2)}                     # EUR/MWh -> ct/kWh
            for t, p in zip(secs, prices) if p is not None]
    if not rows:
        print(f"  {s[:7]}: keine Daten"); continue
    ok = True
    for i in range(0, len(rows), 2000):                       # in Bloecken hochladen
        chunk = rows[i:i + 2000]
        resp = requests.post(f"{URL}/rest/v1/pv_spot",
                             headers={**H, "Prefer": "resolution=merge-duplicates"},
                             params={"on_conflict": "slot"}, json=chunk, timeout=60)
        if not resp.ok:
            print(f"  ! {s[:7]} Upload {resp.status_code}: {resp.text[:150]}"); ok = False; break
    if ok:
        total += len(rows); print(f"  {s[:7]}: {len(rows)} Preise")

print(f"\nFertig. {total} Spotpreise nach pv_spot geschrieben.")
print("Der PDF-Bericht zeigt die Negativpreis-Stunden jetzt auch rueckwirkend.")
