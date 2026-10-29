-- Ningun contrato debe explicar una tajada absurda del valor total.
--
-- Esta es la regla que habria atrapado sola el error que se encontro a mano:
-- un contrato de minima cuantia registrado por 6,45 cuatrillones de pesos,
-- que explicaba el 98,6 % del valor del universo entero. Se tardaron horas en
-- verlo; con este test la corrida se habria detenido el primer dia.
--
-- Se mide sobre las filas confiables, es decir excluyendo los errores ya
-- diagnosticados y marcados: lo que se vigila es que aparezca uno NUEVO.
--
-- Umbral 10 %. El contrato mas grande del universo confiable pesa hoy 1,55 %,
-- asi que hay seis veces de holgura: no salta por un contrato grande de
-- verdad, como una concesion vial, y si por un error de digitacion.
{{ config(severity = 'error') }}

with total as (
    select sum(valor_contratado) as valor_total
    from {{ ref('hecho_contratos') }}
    where valor_confiable
)

select
    h.id_contrato,
    h.valor_contratado,
    round(100 * h.valor_contratado / t.valor_total, 2) as porcentaje_del_total
from {{ ref('hecho_contratos') }} h
cross join total t
where h.valor_confiable
  and h.valor_contratado > 0.10 * t.valor_total
