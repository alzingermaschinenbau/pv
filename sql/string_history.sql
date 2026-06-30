-- ============================================================
--  pv_string_samples · Zeitreihe der String-Werte (für die Auswertung)
--  + pv_string_daily · Tagesenergie je String
-- ============================================================
--  Der Collector schreibt im String-Sample-Takt (Standard 5 Min) je
--  Wechselrichter eine Zeile mit den PV-Eingängen (jsonb). Daraus berechnet
--  die View die Tagesenergie je einzelnem String.
--
--  Einmalig im Supabase SQL-Editor ausführen.
-- ============================================================

create table if not exists public.pv_string_samples (
  plant   text        not null,                 -- 'voll' | 'eigen'
  wr      int         not null,                 -- Wechselrichter 1..n
  ts      timestamptz not null default now(),   -- Messzeitpunkt
  strings jsonb                                 -- [{pv,v,a,w}, ...]
);
create index if not exists pv_string_samples_idx
  on public.pv_string_samples (plant, wr, ts);

alter table public.pv_string_samples enable row level security;
drop policy if exists "anon read pv_string_samples" on public.pv_string_samples;
create policy "anon read pv_string_samples" on public.pv_string_samples for select to anon using (true);
grant select on public.pv_string_samples to anon, authenticated;

-- Tagesenergie je String (Wh), zeitgewichtet integriert.
-- Lücken (Neustart/Nacht) werden auf 15 Min gekappt, damit sie die
-- Integration nicht verfälschen. Negative Leistung (rückspeisender String)
-- bleibt erhalten – so wird ein Verlust sichtbar.
create or replace view public.pv_string_daily as
with x as (
  select plant, wr,
         (s->>'pv')::int      as pv,
         ts,
         (s->>'w')::numeric   as w,
         (ts at time zone 'Europe/Berlin')::date as tag,
         lag(ts) over (partition by plant, wr, (s->>'pv')::int order by ts) as prev
  from public.pv_string_samples,
       lateral jsonb_array_elements(strings) s
)
select plant, wr, pv, tag,
       round(sum( w * least(extract(epoch from (ts - prev)), 900) / 3600.0 )) as energy_wh,
       round(avg(w)) as avg_w,
       round(max(w)) as max_w,
       count(*)      as n
from x
where prev is not null
group by plant, wr, pv, tag;

grant select on public.pv_string_daily to anon, authenticated;
notify pgrst, 'reload schema';

-- Hinweis Speicherplatz: bei 5-Min-Takt ~4.600 Zeilen/Tag. Bei Bedarf
-- Rohdaten aelter als 90 Tage loeschen (die Tageswerte koennten dann in eine
-- eigene Tabelle materialisiert werden) – aktuell nicht noetig.
