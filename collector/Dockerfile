# Container für den PV-Collector (läuft z.B. dauerhaft auf einem NAS)
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY collector.py .

# -u = ungepufferte Ausgabe, damit Logs im Container Manager sofort sichtbar sind
CMD ["python", "-u", "collector.py"]
