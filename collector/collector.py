#!/usr/bin/env python3
# ============================================================
#  Alzinger PV-Monitoring · Datensammler (Modbus TCP -> Supabase)
# ============================================================
#  Liest beide SmartLogger 3000 per Modbus TCP (Port 502,
#  Adressmodus "Kommunikationsadresse"), aggregiert je Anlage und
#  schreibt mit dem service_role-Key nach Supabase:
#    - pv_live     (Upsert auf plant = aktueller Stand)
#    - pv_samples  (Insert = Zeitreihe)
#
#  Läuft als Dauerprozess auf einem Rechner mit Zugang zum Logger-Netz.
#  Eine Direktvermarktungs-Box liest dieselben Logger parallel (nur Web) –
#  diese hier nutzt nur Modbus/502 und stört den DVM-Zugriff nicht.
#
#  Konfiguration über Umgebungsvariablen (siehe .env.example):
#    SUPABASE_URL          z.B. https://xxxx.supabase.co
#    SUPABASE_SERVICE_KEY  service_role ODER sb_secret_... (GEHEIM!)
#    POLL_SECONDS          Abtastintervall (Default 60)
#  Optional pro Anlage überschreibbar:
#    LOGGER_VOLL_HOST / LOGGER_EIGEN_HOST
# ============================================================

import os
import sys
import time
import struct
import datetime as dt

import requests

# .env automatisch laden, falls python-dotenv installiert ist
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

try:
    from pymodbus.client import ModbusTcpClient
except ImportError:
    sys.exit("pymodbus fehlt – bitte 'pip install -r requirements.txt' ausführen.")


# ---------- Anlagen-Konfiguration ----------
# Wechselrichter-Slave-IDs und Logger-Hosts laut Anlagendoku.
PLANTS = {
    "voll": {
        "host": os.getenv("LOGGER_VOLL_HOST", "192.168.100.22"),
        "inverters": [12, 13, 14, 15, 16, 17, 18, 19, 20, 21],  # 10 WR
        "meter": None,                                          # kein Zähler
    },
    "eigen": {
        "host": os.getenv("LOGGER_EIGEN_HOST", "192.168.100.12"),
        "inverters": [12, 13, 14, 15, 16, 20],                  # 6 WR
        "meter": 11,                                            # Messgeraet_NAP
    },
}

PORT = 502

# Modbus-Register (Kommunikationsadresse), Funktionscode 03 (Holding).
REG_WR_POWER  = 32080   # Wirkleistung Wechselrichter, i32, /1000 -> kW
REG_WR_TOTAL  = 32114   # Gesamtertrag,                u32, /100  -> kWh
REG_METER_PWR = 32278   # Wirkleistung Zähler, i32, W; >0 Netzbezug, <0 Einspeisung

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))
# Wie oft die Zeitreihe (pv_samples) geschrieben wird. pv_live (aktueller Stand)
# wird IMMER bei jedem Tick aktualisiert. So kann man sehr schnell pollen
# (z.B. POLL_SECONDS=10 für eine flotte Live-Anzeige), ohne die Historie/DB
# mit zu vielen Zeilen zu fluten.
SAMPLE_SECONDS = int(os.getenv("SAMPLE_SECONDS", "60"))
# Börsen-Spotpreise (Energy-Charts) server-seitig holen und nach pv_spot schreiben.
# So muss der Browser sie nicht selbst laden (kein CORS-Problem). 0 = aus.
SPOT_SECONDS = int(os.getenv("SPOT_SECONDS", "900"))   # alle 15 Min
SPOT_BZN = os.getenv("SPOT_BZN", "DE-LU")
MODBUS_TIMEOUT = 5

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# ---------- Zähler-Energieregister (kWh-Zählerstände) – optional ----------
# Die kumulierten kWh-Stände des Zählers (bezogene / eingespeiste Energie).
# Adressen je nach Zählermodell unterschiedlich -> per ENV setzen (kein Raten).
# Bleiben sie 0/leer, wird die Funktion einfach übersprungen (kein Datenmüll).
#   METER_IMPORT_REG   Register "bezogene Wirkenergie" (Netzbezug, kWh)
#   METER_EXPORT_REG   Register "eingespeiste Wirkenergie" (Einspeisung, kWh)
#   METER_ENERGY_TYPE  u32 | i32 | u64   (Standard u32)
#   METER_ENERGY_GAIN  Teiler -> kWh     (Standard 100)
def _int_env(name):
    v = os.getenv(name, "").strip()
    try:
        return int(v) if v else None
    except ValueError:
        return None

METER_IMPORT_REG  = _int_env("METER_IMPORT_REG")
METER_EXPORT_REG  = _int_env("METER_EXPORT_REG")
METER_ENERGY_TYPE = os.getenv("METER_ENERGY_TYPE", "u32").lower()
METER_ENERGY_GAIN = float(os.getenv("METER_ENERGY_GAIN", "100"))
METER_ENERGY_ON   = METER_IMPORT_REG is not None or METER_EXPORT_REG is not None

# Diagnose-Hilfe: Registerbereich dumpen, um die kWh-Register zu finden.
#   METER_SCAN="32278:40"  -> ab Register 32278 die nächsten 40 Register zeigen
METER_SCAN = os.getenv("METER_SCAN", "").strip()


# ---------- Modbus-Decoder ----------
_READ_KW = None   # erkanntes Schlüsselwort für die Slave-/Geräte-ID (pymodbus-Version)


def _read_regs(client, slave, address, count):
    """Liest 'count' Holding-Register. Gibt Liste oder None bei Fehler.
    Robust gegen pymodbus-Versionen: slave= (3.x) / device_id= (neuere) / unit= (2.x)."""
    global _READ_KW
    fn = client.read_holding_registers
    candidates = [_READ_KW] if _READ_KW else ["slave", "device_id", "unit"]
    rr, last_err = None, None
    for kw in candidates:
        try:
            rr = fn(address, count=count, **{kw: slave})
            _READ_KW = kw                       # passendes Schlüsselwort merken
            break
        except TypeError as e:                  # Schlüsselwort passt nicht -> nächstes probieren
            last_err = e
            continue
        except Exception as e:                  # noqa: BLE001  echter Modbus-/Verbindungsfehler
            print(f"  ! Modbus-Fehler slave {slave} @ {address}: {e}")
            return None
    if rr is None:
        print(f"  ! Modbus-Fehler slave {slave} @ {address}: {last_err}")
        return None
    if rr.isError():
        print(f"  ! Modbus-Antwortfehler slave {slave} @ {address}: {rr}")
        return None
    return rr.registers


def _to_i32(regs):
    """Zwei 16-Bit-Register (high word zuerst) als signed int32."""
    if not regs or len(regs) < 2:
        return None
    return struct.unpack(">i", struct.pack(">HH", regs[0], regs[1]))[0]


def _to_u32(regs):
    """Zwei 16-Bit-Register (high word zuerst) als unsigned int32."""
    if not regs or len(regs) < 2:
        return None
    return struct.unpack(">I", struct.pack(">HH", regs[0], regs[1]))[0]


def _to_u64(regs):
    """Vier 16-Bit-Register (high word zuerst) als unsigned int64."""
    if not regs or len(regs) < 4:
        return None
    return struct.unpack(">Q", struct.pack(">HHHH", regs[0], regs[1], regs[2], regs[3]))[0]


def read_meter_energy(client, slave, reg):
    """Zählerstand in kWh aus 'reg' lesen (Typ/Gain laut ENV). None wenn aus/Fehler."""
    if reg is None:
        return None
    count = 4 if METER_ENERGY_TYPE == "u64" else 2
    regs = _read_regs(client, slave, reg, count)
    if METER_ENERGY_TYPE == "u64":
        raw = _to_u64(regs)
    elif METER_ENERGY_TYPE == "i32":
        raw = _to_i32(regs)
    else:
        raw = _to_u32(regs)
    return round(raw / METER_ENERGY_GAIN, 2) if raw is not None else None


def scan_registers(client, slave, spec):
    """Diagnose: Registerbereich 'start:count' roh + als u32/u16 ausgeben."""
    try:
        start, count = (int(x) for x in spec.split(":"))
    except ValueError:
        print(f"  ! METER_SCAN ungültig: '{spec}' (erwartet z.B. 32278:40)")
        return
    regs = _read_regs(client, slave, start, count)
    if not regs:
        print("  ! METER_SCAN: keine Daten")
        return
    print(f"  --- METER_SCAN slave {slave}, ab {start} ---")
    for i in range(0, len(regs) - 1, 2):
        addr = start + i
        u32 = struct.unpack(">I", struct.pack(">HH", regs[i], regs[i + 1]))[0]
        i32 = struct.unpack(">i", struct.pack(">HH", regs[i], regs[i + 1]))[0]
        print(f"    {addr}: u16={regs[i]:>6} {regs[i+1]:>6}  u32={u32:>12}  "
              f"i32={i32:>12}  /100={u32/100:>12.2f}  /1000={u32/1000:>12.3f}")
    print("  --- Ende METER_SCAN ---")


def read_inverter(client, slave):
    """Liefert (power_kw, total_kwh) eines Wechselrichters oder (None, None)."""
    p = _to_i32(_read_regs(client, slave, REG_WR_POWER, 2))
    t = _to_u32(_read_regs(client, slave, REG_WR_TOTAL, 2))
    power_kw  = p / 1000.0 if p is not None else None
    total_kwh = t / 100.0  if t is not None else None
    return power_kw, total_kwh


def read_meter(client, slave):
    """Zähler-Wirkleistung in kW (signiert: >0 Bezug, <0 Einspeisung)."""
    w = _to_i32(_read_regs(client, slave, REG_METER_PWR, 2))
    return w / 1000.0 if w is not None else None


# ---------- Anlage einlesen und in DB-Felder umrechnen ----------
def poll_plant(key, cfg):
    """Liest eine komplette Anlage und gibt das pv_live/pv_samples-Dict zurück."""
    client = ModbusTcpClient(cfg["host"], port=PORT, timeout=MODBUS_TIMEOUT)
    if not client.connect():
        print(f"  ! Verbindung zu {key} ({cfg['host']}) fehlgeschlagen")
        return None
    try:
        p_sum, t_sum, n_ok = 0.0, 0.0, 0
        for slave in cfg["inverters"]:
            pw, tot = read_inverter(client, slave)
            if pw is not None:
                p_sum += pw
                n_ok += 1
            if tot is not None:
                t_sum += tot
        if n_ok == 0:
            print(f"  ! {key}: kein Wechselrichter erreichbar")
            return None

        row = {
            "plant": key,
            "p_kw": round(p_sum, 3),
            "total_kwh": round(t_sum, 2),
            "load_kw": None,
            "feed_kw": None,
            "grid_kw": None,
        }

        if cfg["meter"] is not None:
            if METER_SCAN:
                scan_registers(client, cfg["meter"], METER_SCAN)
            # Der NAP-Zähler misst den GESAMTEN Netzanschlusspunkt (beide Anlagen).
            # Daher wird load/feed/grid erst in main() mit der Gesamterzeugung verrechnet.
            row["_grid_signed"] = read_meter(client, cfg["meter"])   # >0 Bezug, <0 Einspeisung
            # Zähler-kWh-Stände (nur wenn Register konfiguriert sind)
            if METER_ENERGY_ON:
                row["import_kwh"] = read_meter_energy(client, cfg["meter"], METER_IMPORT_REG)
                row["export_kwh"] = read_meter_energy(client, cfg["meter"], METER_EXPORT_REG)
        else:
            # Volleinspeiser: alles ins Netz, kein Eigenverbrauch
            row["feed_kw"] = round(p_sum, 3)
            row["load_kw"] = 0.0
            row["grid_kw"] = 0.0
        return row
    finally:
        client.close()


# ---------- Supabase-Schreibzugriff ----------
def _headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def write_supabase(rows, ts_iso, with_samples=True):
    """Upsert nach pv_live (immer) und optional Insert in pv_samples (Zeitreihe)."""
    live = [{**r, "ts": ts_iso} for r in rows]

    # pv_live: Upsert auf Primärschlüssel plant
    r1 = requests.post(
        f"{SUPABASE_URL}/rest/v1/pv_live",
        headers={**_headers(), "Prefer": "resolution=merge-duplicates"},
        params={"on_conflict": "plant"},
        json=live, timeout=15,
    )
    if not r1.ok:
        print(f"  ! pv_live {r1.status_code}: {r1.text[:200]}")

    # pv_samples: reiner Insert (Zeitreihe) – nur im Sample-Takt, nicht jeden Tick
    if with_samples:
        r2 = requests.post(
            f"{SUPABASE_URL}/rest/v1/pv_samples",
            headers=_headers(),
            json=live, timeout=15,
        )
        if not r2.ok:
            print(f"  ! pv_samples {r2.status_code}: {r2.text[:200]}")


def fetch_and_store_spot():
    """Börsenpreise (Energy-Charts, DE-LU) holen und nach pv_spot schreiben.
    Läuft server-seitig im Collector -> kein CORS-Problem im Browser."""
    try:
        from zoneinfo import ZoneInfo
        now_local = dt.datetime.now(ZoneInfo("Europe/Berlin"))
    except Exception:                                # noqa: BLE001  (z.B. Windows ohne tzdata)
        now_local = dt.datetime.now()
    d  = now_local.strftime("%Y-%m-%d")
    d2 = (now_local + dt.timedelta(days=1)).strftime("%Y-%m-%d")   # heute + morgen
    url = f"https://api.energy-charts.info/price?bzn={SPOT_BZN}&start={d}&end={d2}"
    try:
        r = requests.get(url, timeout=15)
        if not r.ok:
            print(f"  ! Spotpreise {r.status_code}")
            return
        j = r.json()
    except Exception as e:                           # noqa: BLE001
        print(f"  ! Spotpreise-Fehler: {e}")
        return
    secs = j.get("unix_seconds") or []
    prices = j.get("price") or []
    rows = [{"slot": dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(),
             "price": round(p / 10.0, 2)}                      # EUR/MWh -> ct/kWh
            for t, p in zip(secs, prices) if p is not None]
    if not rows:
        return
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/pv_spot",
            headers={**_headers(), "Prefer": "resolution=merge-duplicates"},
            params={"on_conflict": "slot"}, json=rows, timeout=15,
        )
        if not resp.ok:
            print(f"  ! pv_spot {resp.status_code}: {resp.text[:200]}")
        else:
            print(f"  Spotpreise aktualisiert ({len(rows)} Werte)")
    except Exception as e:                           # noqa: BLE001
        print(f"  ! pv_spot-Schreibfehler: {e}")


# ---------- Hauptschleife ----------
def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        sys.exit("SUPABASE_URL und SUPABASE_SERVICE_KEY müssen gesetzt sein.")

    print(f"Collector gestartet · Poll {POLL_SECONDS}s · Sample {SAMPLE_SECONDS}s · Ziel {SUPABASE_URL}")
    last_sample = 0.0
    last_spot = 0.0
    while True:
        t0 = time.time()

        # Spotpreise periodisch holen (server-seitig, kein CORS)
        if SPOT_SECONDS and (t0 - last_spot) >= SPOT_SECONDS:
            fetch_and_store_spot()
            last_spot = t0
        ts_iso = dt.datetime.now(dt.timezone.utc).isoformat()
        collected = []
        for key, cfg in PLANTS.items():
            row = poll_plant(key, cfg)
            if row:
                collected.append((cfg, row))

        # Gesamterzeugung aller erreichbaren Anlagen (für die NAP-Zähler-Rechnung)
        total_pv = sum(r["p_kw"] for _, r in collected)

        rows = []
        for cfg, row in collected:
            if "_grid_signed" in row:
                g = row.pop("_grid_signed")
                if g is not None:
                    # Der NAP-Zähler misst beide Anlagen am Netzanschlusspunkt:
                    # Werksverbrauch = Gesamterzeugung + (Bezug - Einspeisung)
                    row["load_kw"] = round(total_pv + g, 3)
                    row["feed_kw"] = round(max(0.0, -g), 3)   # Einspeisung netto ins Netz
                    row["grid_kw"] = round(max(0.0, g), 3)    # Netzbezug netto
            rows.append(row)
            msg = f"  {row['plant']}: {row['p_kw']} kW · {row['total_kwh']} kWh"
            if cfg["meter"] is not None:
                msg += f" · Last {row['load_kw']} · Einsp {row['feed_kw']} · Bezug {row['grid_kw']}"
                if METER_ENERGY_ON:
                    msg += f" · Zähler Bezug {row.get('import_kwh')} / Einsp {row.get('export_kwh')} kWh"
            print(msg)

        if rows:
            do_sample = (t0 - last_sample) >= SAMPLE_SECONDS
            try:
                write_supabase(rows, ts_iso, with_samples=do_sample)
                if do_sample:
                    last_sample = t0
            except Exception as e:               # noqa: BLE001
                print(f"  ! Supabase-Schreibfehler: {e}")

        # bis zum nächsten Intervall warten (driftarm)
        time.sleep(max(1.0, POLL_SECONDS - (time.time() - t0)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBeendet.")
