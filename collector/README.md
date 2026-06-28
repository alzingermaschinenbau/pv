# PV-Datensammler (Collector)

Liest beide SmartLogger 3000 per **Modbus TCP** und schreibt die Werte nach
Supabase. Läuft als Dauerprozess auf einem Rechner mit Zugang zum Logger-Netz.

> **Auf einem NAS (Synology/QNAP)?** Empfohlener Weg – siehe **[SYNOLOGY.md](SYNOLOGY.md)**
> (läuft als Docker-Container, startet automatisch wieder). Windows: Doppelklick
> auf `start_windows.bat`.

## Einrichtung

```bash
cd collector
python -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt
cp .env.example .env        # dann .env ausfüllen (SUPABASE_SERVICE_KEY = geheim!)
python collector.py
```

## Was geschrieben wird

| Ziel         | Modus  | Inhalt                                   |
|--------------|--------|------------------------------------------|
| `pv_live`    | Upsert | aktueller Stand je Anlage (`plant` = PK) |
| `pv_samples` | Insert | Zeitreihe (jeder Tick ein Datensatz)     |

Die App liest daraus `pv_live` + Views `pv_today/pv_daily/pv_monthly`.

## Anlagen / Modbus

| Anlage | Logger          | Wechselrichter (Slave-IDs)   | Zähler        |
|--------|-----------------|------------------------------|---------------|
| voll   | 192.168.100.22  | 12–21 (10 WR)                | –             |
| eigen  | 192.168.100.12  | 12,13,14,15,16,20 (6 WR)     | 11 (NAP)      |

Register (Kommunikationsadresse, FC 03):

| Register | Bedeutung               | Typ | Faktor          |
|----------|-------------------------|-----|-----------------|
| 32080    | Wirkleistung WR         | i32 | /1000 → kW      |
| 32114    | Gesamtertrag WR         | u32 | /100  → kWh     |
| 32278    | Wirkleistung Zähler     | i32 | /1000 → kW (W)  |

Zähler-Vorzeichen: **>0 Netzbezug**, **<0 Einspeisung**. Daraus:
`load = p + grid_signed`, `feed = max(0,−grid_signed)`, `grid = max(0,grid_signed)`.

> Der Collector nutzt nur Modbus/502 und stört die Direktvermarktungs-Box
> (nur Web 80/443) am selben Logger nicht.

## Als Dienst betreiben (systemd, Beispiel)

```ini
# /etc/systemd/system/pv-collector.service
[Unit]
Description=Alzinger PV Collector
After=network-online.target

[Service]
WorkingDirectory=/opt/pv/collector
ExecStart=/opt/pv/collector/.venv/bin/python collector.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now pv-collector
journalctl -u pv-collector -f
```
