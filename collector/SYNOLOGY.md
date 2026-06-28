# Collector auf Synology-NAS einrichten (Container Manager)

Der Collector läuft als Docker-Container dauerhaft auf dem NAS und startet nach
Neustart/Stromausfall automatisch wieder. Einmal einrichten – fertig.

> QNAP: Es funktioniert genauso über **Container Station** statt Container Manager.

## 0. Voraussetzung prüfen – erreicht das NAS die Logger?
Der Container kann die SmartLogger nur lesen, wenn das **NAS im selben Netz**
ist bzw. die Logger (192.168.100.x) erreicht.
**Test:** In DSM eine SSH-/Terminal-Sitzung ist nicht nötig – einfach im
Browser vom NAS-Netz aus `http://192.168.100.12` öffnen. Kommt die
SmartLogger-Anmeldung, passt es. (Falls nicht: NAS und Logger sind in
getrennten Netzen/VLANs – dann sag mir Bescheid, das lösen wir separat.)

## 1. Container Manager installieren
DSM → **Paket-Zentrum** → „Container Manager" suchen → installieren.

## 2. Dateien aufs NAS legen
1. In der **File Station** einen Ordner anlegen, z.B. `docker/pv-collector`.
2. Vom Projekt **`github.com/alzingermaschinenbau/pv`** → grüner Button
   **Code → Download ZIP** herunterladen, entpacken.
3. Aus dem entpackten Ordner **`collector`** diese Dateien in den NAS-Ordner
   `docker/pv-collector` hochladen:
   `collector.py`, `requirements.txt`, `Dockerfile`, `docker-compose.yml`

## 3. Geheimen Key eintragen (.env)
1. In Supabase → **Settings → API → Project API keys** den **`secret`**-Key
   (beginnt mit `sb_secret_…`) kopieren. ⚠️ NICHT den `publishable`-Key.
2. Auf dem PC eine Textdatei mit genau diesem Inhalt anlegen …
   ```
   SUPABASE_SERVICE_KEY=sb_secret_HIER_DEIN_GEHEIMER_KEY
   ```
   … und als **`.env`** (Punkt am Anfang, keine .txt-Endung) in den Ordner
   `docker/pv-collector` hochladen.

## 4. Projekt im Container Manager anlegen
1. Container Manager → links **Projekt** → **Erstellen**.
2. **Projektname:** `pv-collector`
3. **Pfad:** den Ordner `docker/pv-collector` auswählen.
4. Quelle: „docker-compose.yml verwenden" (wird automatisch erkannt) → **Weiter**.
5. **Erstellen/Starten** klicken. Beim ersten Mal wird das Image gebaut – das
   dauert 1–2 Minuten.

## 5. Läuft es? Logs ansehen
Container Manager → **Container** → `pv-collector` → **Protokoll/Logs**.
Dort sollte alle ~60 Sek. eine Zeile erscheinen, z.B.:
```
eigen: 0 kW · 940000 kWh · Last 85 · Einsp 0 · Bezug 85
voll: 0 kW · 1850000 kWh
```

## 6. In der App ansehen
App auf dem iPhone neu laden → Netzbezug/Verbrauch erscheinen. (Aktuelle
PV-Erzeugung ist nachts 0 und kommt mit Sonnenaufgang.)

---

## Wenn etwas klemmt
- **„Verbindung zu … fehlgeschlagen"** in den Logs → NAS erreicht die Logger
  nicht (Netz/VLAN). Schritt 0 prüfen.
- **`pv_live 401/403`** → falscher Key in `.env` (muss der `sb_secret_…` sein).
- **Container stoppt sofort** → meist fehlt die `.env` oder der Key. Logs lesen.
- Nach Änderungen an `.env`: im Container Manager das Projekt **neu starten**.
