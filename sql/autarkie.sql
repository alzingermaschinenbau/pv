-- ============================================================
--  pv_autarkie_daily · exakte Tages-Autarkie aus den Live-Samples
-- ============================================================
--  Integriert je Tag zeitgewichtet aus pv_samples (Anlage 'eigen'):
--    self = min(Erzeugung, Verbrauch)   → tatsächlich selbst genutzte PV
--    load = Verbrauch,  gen = Erzeugung
--  Damit wird der Autarkiegrad je Tag exakt (5-Min-genau) statt nur aus
--  Tages-Summen geschätzt. Die App bildet daraus den Jahresschnitt
--  (Summe self / Summe load über das laufende Jahr).
--
--  Lücken (Neustart/Nacht) werden auf 5 Min gekappt, damit Ausfälle die
--  Integration nicht aufblähen – gleiche Logik wie pv_load_daily.
--
--  Einmalig im Supabase SQL-Editor ausführen.
-- ============================================================

create or replace view public.pv_autarkie_daily as
with s as (
  select ts,
         greatest(p_kw, 0)                              as gen,
         greatest(load_kw, 0)                           as load,
         least(greatest(p_kw, 0), greatest(load_kw, 0)) as self,
         lead(ts) over (order by ts)                    as ts_next
  from public.pv_samples
  where plant = 'eigen' and p_kw is not null and load_kw is not null
),
d as (
  select (ts at time zone 'Europe/Berlin')::date as tag, gen, load, self,
         extract(epoch from (least(ts_next, ts + interval '5 minutes') - ts)) / 3600.0 as dt
  from s where ts_next is not null
)
select tag,
       round(sum(self * dt)::numeric, 2) as self_kwh,
       round(sum(load * dt)::numeric, 2) as load_kwh,
       round(sum(gen  * dt)::numeric, 2) as gen_kwh
from d
group by tag
order by tag;

grant select on public.pv_autarkie_daily to anon, authenticated;
notify pgrst, 'reload schema';
