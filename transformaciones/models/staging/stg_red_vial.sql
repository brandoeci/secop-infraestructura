{{
    config(
        materialized = 'view',
        description  = 'Capa silver: la red vial de INVIAS tipada y decodificada.'
    )
}}

-- Silver, mismas reglas que stg_contratos: se castea, se limpia el texto y se
-- decodifica. No se agrega y no se decide nada de negocio.
--
-- Lo propio de este origen es que varias columnas llegan como NUMERO y no
-- como etiqueta: superficie=1 significa 'Pavimentada'. Los diccionarios estan
-- publicados en los metadatos del dataset:
--   https://www.datos.gov.co/api/views/ie7y-asdn.json -> columns[].description
--
-- Los tres pequenos se traducen aqui con un case, porque son tres o cuatro
-- valores y leerlos en linea es mas claro que un join. El de `territorial`
-- tiene 30 codigos y vive en el seed territoriales_invias, donde ademas se
-- declara con que nombre lo escribe SECOP.

with bronze as (

    select * from {{ source('bronze', 'red_vial') }}

),

tipado as (

    select
        {{ normalizar_texto('codigo_tramo') }}   as codigo_tramo,
        {{ normalizar_texto('ruta') }}           as ruta,
        {{ normalizar_texto('nombre_ruta') }}    as nombre_ruta,
        {{ normalizar_texto('nombre_tramo') }}   as nombre_tramo,

        -- El codigo crudo. Se traduce en dim_territorial_vial con el seed.
        {{ castear_seguro('territorial', 'INT64') }} as territorial_codigo,

        case {{ castear_seguro('categoria', 'INT64') }}
            when 1 then 'Primer Orden'
            when 2 then 'Segundo Orden'
            when 3 then 'Tercer Orden'
            when 4 then 'Por Definir'
        end as categoria,

        case {{ castear_seguro('superficie', 'INT64') }}
            when 1 then 'Pavimentada'
            when 2 then 'Sin Pavimentar'
            when 3 then 'Por Definir'
        end as superficie,

        case {{ castear_seguro('calzada', 'INT64') }}
            when 1 then 'Sencilla'
            when 2 then 'Doble'
            when 3 then 'Por Definir'
        end as calzada,

        case {{ castear_seguro('administrador', 'INT64') }}
            when 1 then 'INVIAS'
            when 2 then 'ANI'
            when 3 then 'Concesion Departamental'
            when 4 then 'FINDETER'
            when 5 then 'Vias Desuso'
            when 6 then 'INVIAS - Convenios'
        end as administrador,

        -- shape__length viene en metros. Se guarda en kilometros porque es la
        -- unidad en la que se habla de una red vial, y porque la medida del
        -- informe es gasto por kilometro.
        coalesce({{ castear_seguro('shape__length', tipo_real()) }}, 0.0) / 1000.0
            as longitud_km,

        _ingestado_en

    from bronze

)

select * from tipado
