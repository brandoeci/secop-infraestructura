{{ config(materialized = 'table') }}

-- Tabla de fechas comun y continua, para marcarla como tabla de fechas en
-- Power BI.
--
-- Tiene que cubrir sin huecos el rango de las tres fechas del hecho, y
-- empezar un 1 de enero y terminar un 31 de diciembre: si no, la inteligencia
-- de tiempo (SAMEPERIODLASTYEAR y compania) da resultados parciales en los
-- anios de los extremos.
--
-- El rango se acota a la ventana plausible porque un contrato trae fecha de
-- fin en el anio 0206 y esa sola fila estiraba la tabla a 675.699 dias, unos
-- 1.850 anios, dejandola inservible. Ver docs/calidad-datos.md seccion 5.

with fechas_del_hecho as (

    select fecha_de_firma               as fecha from {{ ref('int_contratos_calidad') }}
    union all
    select fecha_de_inicio_del_contrato as fecha from {{ ref('int_contratos_calidad') }}
    union all
    select fecha_de_fin_del_contrato    as fecha from {{ ref('int_contratos_calidad') }}

),

rango as (

    select
        {{ fecha_de('min(extract(year from fecha))', 1, 1) }}   as inicio,
        {{ fecha_de('max(extract(year from fecha))', 12, 31) }} as fin
    from fechas_del_hecho
    where fecha is not null
      and extract(year from fecha)
          between {{ var('anio_min') }} and {{ var('anio_max') }}

),

dias as (

    select cast(dia as DATE) as fecha
    from rango,
         unnest({{ serie_de_fechas('inicio', 'fin') }}) as dia

)

select
    cast({{ formato_fecha('fecha', '%Y%m%d') }} as INT64) as fecha_key,
    fecha,
    cast(extract(year    from fecha) as INT64) as anio,
    cast(extract(quarter from fecha) as INT64) as trimestre,
    cast(extract(month   from fecha) as INT64) as mes,
    cast(extract(day     from fecha) as INT64) as dia,
    {{ elemento("['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
                  'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']",
                'extract(month from fecha)') }} as nombre_mes,
    {{ formato_fecha('fecha', '%Y-%m') }} as anio_mes,
    cast(extract(year from fecha) as STRING) || '-T'
        || cast(extract(quarter from fecha) as STRING) as anio_trimestre
from dias
order by fecha
