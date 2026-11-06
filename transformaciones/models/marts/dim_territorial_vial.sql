{{
    config(
        materialized = 'table',
        description  = 'Dimension de contexto: la red vial nacional de INVIAS por territorial.'
    )
}}

-- GRANO: un territorial de INVIAS. 30 del diccionario mas un centinela.
--
-- QUE ES Y QUE NO ES
-- ------------------
-- Es una dimension de CONTEXTO, no de hecho. El dataset de INVIAS no dice en
-- que via se gasto cada contrato: no hay forma de saberlo. Lo unico que se
-- puede relacionar es el departamento donde esta registrada la entidad
-- contratante con el territorial de INVIAS del mismo nombre.
--
-- Eso NO es "la via de este contrato", y hay que decirlo asi. Una entidad
-- nacional con sede en Bogota contrata obra en todo el pais. Medido el
-- 2026-11-05: el 71,9% de los contratos cae en departamentos con territorial,
-- pero solo el 54,3% del dinero, porque el resto se concentra en Bogota.
--
-- Para lo que SI sirve: normalizar. "Quien gasta mas" siempre responde los
-- grandes; "quien gasta mas por kilometro de red que administra" es otra
-- pregunta, y es la que esta dimension habilita.
--
-- POR QUE NO HAY pct_pavimentado
-- ------------------------------
-- Porque el origen no lo soporta. De 715 segmentos, 515 traen superficie
-- 'Por Definir' y solo 3 'Sin Pavimentar'. Un porcentaje de pavimento
-- calculado sobre eso diria que Boyaca tiene el 1,3% de su red pavimentada,
-- lo cual es falso: lo que pasa es que no se sabe. Se exponen los kilometros
-- de cada estado por separado para que el hueco se vea.

with diccionario as (

    select
        codigo,
        nombre,
        departamento_secop,
        -- Los codigos 1 a 25 son departamentos. El 26 es Ocana, una ciudad; el
        -- 27 la sede de INVIAS; el 28 la ANI; el 29 y el 0, sin asignar.
        codigo between 1 and 25 as es_departamento
    from {{ ref('territoriales_invias') }}

    union all

    -- Dos centinelas, porque son dos cosas distintas y mezclarlas rompe la
    -- medida. El -1 es a donde apuntan los contratos de departamentos sin red
    -- vial nacional, y tiene CERO kilometros a proposito: si tuviera, el
    -- gasto por kilometro de ese miembro seria un numero inventado. El -2
    -- recoge los 9 segmentos de via cuyo territorial llego nulo en el origen
    -- (243 km), que no tienen contratos pero tampoco pueden desaparecer de
    -- los totales de red. Marcar y no borrar.
    select -1, 'Sin territorial', cast(null as STRING), false
    union all
    select -2, 'Territorial no informado', cast(null as STRING), false

),

red as (

    select
        coalesce(territorial_codigo, -2) as codigo,
        count(*)                                                   as segmentos,
        count(distinct ruta)                                       as rutas,
        sum(longitud_km)                                           as km_red,
        sum(case when superficie = 'Pavimentada'
                 then longitud_km else 0 end)                      as km_pavimentados,
        sum(case when superficie = 'Sin Pavimentar'
                 then longitud_km else 0 end)                      as km_sin_pavimentar,
        sum(case when superficie is null or superficie = 'Por Definir'
                 then longitud_km else 0 end)                      as km_superficie_sin_definir,
        sum(case when categoria = 'Primer Orden'
                 then longitud_km else 0 end)                      as km_primer_orden
    from {{ ref('stg_red_vial') }}
    group by 1

)

select
    {{ clave_subrogada(['d.codigo']) }}          as territorial_key,
    d.codigo                                     as territorial_codigo,
    d.nombre                                     as territorial,
    d.departamento_secop                         as departamento,
    d.es_departamento,
    coalesce(r.segmentos, 0)                     as segmentos,
    coalesce(r.rutas, 0)                         as rutas,
    coalesce(r.km_red, 0.0)                      as km_red,
    coalesce(r.km_pavimentados, 0.0)             as km_pavimentados,
    coalesce(r.km_sin_pavimentar, 0.0)           as km_sin_pavimentar,
    coalesce(r.km_superficie_sin_definir, 0.0)   as km_superficie_sin_definir,
    coalesce(r.km_primer_orden, 0.0)             as km_primer_orden

from diccionario d
left join red r on r.codigo = d.codigo
