# Collector auf QNAP-NAS einrichten (Container Station)

Der Collector läuft als Container dauerhaft auf dem QNAP und startet nach
Neustart/Stromausfall automatisch wieder. Es muss **nichts gebaut** werden –
das NAS lädt nur ein fertiges Image herunter.

## 0. Voraussetzung prüfen – erreicht das NAS die Logger?
Der Container kann die SmartLogger nur lesen, wenn das **NAS die Logger
(192.168.100.x) erreicht**. **Test:** Vom selben Netz aus im Browser
`http://192.168.100.12` öffnen – kommt die SmartLogger-Anmeldung, passt es.
(Falls nicht: NAS und Logger sind in getrennten Netzen/VLANs – dann melde dich,
das lösen wir separat.)

## 1. Container Station installieren
QNAP → **App Center** → „Container Station" installieren/öffnen.

## 2. Geheimen Key holen
Supabase → **Settings → API → Project API keys** → den **`secret`**-Key
(beginnt mit `sb_secret_…`) kopieren. ⚠️ NICHT den `publishable`-Key.

## 3. Anwendung anlegen (docker-compose einfügen)
1. Container Station → **Anwendungen** (Applications) → **Erstellen** (Create).
2. Es öffnet sich ein Feld für **YAML / docker-compose**. Dort genau das
   einfügen (und beim Key-Wert deinen `sb_secret_…` eintragen):

   ```yaml
   services:
     pv-collector:
       image: ghcr.io/alzingermaschinenbau/pv-collector:latest
       container_name: pv-collector
       restart: unless-stopped
       environment:
         - SUPABASE_URL=https://tppwuvizobwnnfatysdh.supabase.co
         - POLL_SECONDS=60
         - SUPABASE_SERVICE_KEY=sb_secret_HIER_DEIN_GEHEIMER_KEY
   ```

3. **Erstellen/Starten** klicken. Container Station lädt das Image und startet.

## 4. Läuft es? Logs ansehen
Container Station → Container `pv-collector` → **Protokoll/Logs**. Dort sollte
alle ~60 Sek. eine Zeile erscheinen, z.B.:
```
eigen: 0 kW · 940000 kWh · Last 85 · Einsp 0 · Bezug 85
voll: 0 kW · 1850000 kWh
```

## 5. In der App ansehen
App auf dem iPhone neu laden → Netzbezug/Verbrauch erscheinen. (Aktuelle
PV-Erzeugung ist nachts 0 und kommt mit Sonnenaufgang.)

---

## Wenn etwas klemmt
- **Image kann nicht geladen werden / „unauthorized"** → das Image-Paket muss
  einmalig öffentlich geschaltet werden (siehe Hinweis im Haupt-README), dann
  geht der Download ohne Anmeldung.
- **„Verbindung zu … fehlgeschlagen"** in den Logs → NAS erreicht die Logger
  nicht (Netz/VLAN). Schritt 0 prüfen.
- **`pv_live 401/403`** → falscher Key (muss der `sb_secret_…` sein).
- Nach Änderung des Keys: Anwendung **neu starten**.
