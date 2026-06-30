-- ============================================================
--  pv_inverter · Einzelwerte je Wechselrichter (für die Dach-Draufsicht)
-- ============================================================
--  Der Collector schreibt bei jedem Tick den aktuellen Stand jedes
--  Wechselrichters (Upsert auf plant+wr). Die App liest die Tabelle und
--  färbt jede Dachfläche live nach Auslastung ein.
--
--  Einmalig im Supabase SQL-Editor ausführen.
-- ============================================================

create table if not exists public.pv_inverter (
  plant      text        not null,                 -- 'voll' | 'eigen'
  wr         int         not null,                 -- laufende Nummer 1..n (Reihenfolge wie im Collector)
  power_kw   numeric,                              -- aktuelle Wirkleistung in kW
  total_kwh  numeric,                              -- Gesamtertrag (Zählerstand) in kWh
  ts         timestamptz not null default now(),   -- Zeitpunkt der Messung
  primary key (plant, wr)
);

-- Nur-Lesen für den anonymen Browser-Key (RLS)
alter table public.pv_inverter enable row level security;
drop policy if exists "anon read pv_inverter" on public.pv_inverter;
create policy "anon read pv_inverter" on public.pv_inverter for select to anon using (true);
grant select on public.pv_inverter to anon, authenticated;

-- Für die Live-Draufsicht reicht die Tabelle pv_inverter vollständig aus.
-- (Ein Tagesertrag je WR liesse sich später über eine zusätzliche Zeitreihe
--  pv_samples_inverter ergänzen – aktuell nicht nötig.)
