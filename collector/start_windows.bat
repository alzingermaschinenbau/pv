@echo off
REM ============================================================
REM  Alzinger PV-Collector - Start fuer Windows
REM  Doppelklick startet den Datensammler.
REM  Voraussetzung: Python ist installiert (python.org, Haken
REM  "Add Python to PATH" beim Installieren setzen) und im
REM  Ordner liegt eine ausgefuellte .env (siehe .env.example).
REM ============================================================
cd /d "%~dp0"

if not exist ".env" (
  echo.
  echo [FEHLER] Es fehlt die Datei .env in diesem Ordner.
  echo Kopiere .env.example zu .env und trage den geheimen
  echo Supabase-Key sowie ggf. die Logger-IPs ein.
  echo.
  pause
  exit /b 1
)

echo Installiere benoetigte Pakete ...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
echo Starte Collector (Fenster offen lassen!) ...
echo Beenden mit Strg+C oder Fenster schliessen.
echo.
python collector.py

pause
