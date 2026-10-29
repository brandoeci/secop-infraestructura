{{
    config(
        materialized = 'view',
        description  = 'Capa silver: bronze tipado y limpio, un contrato por fila.'
    )
}}

-- Silver. Aqui pasan tres cosas y ninguna mas: se castea, se limpia el texto
-- y se marca el documento centinela. No se agrega, no se filtra y no se
-- decide nada de negocio: eso vive en intermedio/ y en marts/.
--
-- El casteo es con try_cast a proposito. Un valor que no se puede convertir
-- se vuelve nulo y queda visible en los tests, en vez de reventar la corrida
-- entera por una fila mala entre 66.875.

with bronze as (

    select * from {{ source('bronze', 'contratos') }}

),

tipado as (

    select
        {{ normalizar_texto('id_contrato') }}                   as id_contrato,

        -- dimension entidad
        {{ normalizar_texto('nit_entidad') }}                   as nit_entidad,
        {{ normalizar_texto('nombre_entidad') }}                as nombre_entidad,
        {{ normalizar_texto('departamento') }}                  as departamento,
        {{ normalizar_texto('ciudad') }}                        as ciudad,
        {{ normalizar_texto('orden') }}                         as orden,

        -- dimension proveedor
        {{ normalizar_texto('documento_proveedor') }}           as documento_proveedor,
        {{ normalizar_texto('proveedor_adjudicado') }}          as proveedor_adjudicado,

        -- dimensiones de clasificacion. Estas tres llevan capitalizacion
        -- unificada porque la fuente mezcla 'terminado' con 'Terminado'.
        {{ capitalizar('tipo_de_contrato') }}                   as tipo_de_contrato,
        {{ capitalizar('estado_contrato') }}                    as estado_contrato,
        {{ capitalizar('modalidad_de_contratacion') }}          as modalidad_de_contratacion,
        {{ normalizar_texto('codigo_de_categoria_principal') }} as codigo_de_categoria_principal,

        -- atributo degenerado: texto largo y casi unico por contrato
        {{ normalizar_texto('objeto_del_contrato') }}           as objeto_del_contrato,

        -- fechas, normalizadas a dia
        try_cast(fecha_de_firma               as timestamp)::date as fecha_de_firma,
        try_cast(fecha_de_inicio_del_contrato as timestamp)::date as fecha_de_inicio_del_contrato,
        try_cast(fecha_de_fin_del_contrato    as timestamp)::date as fecha_de_fin_del_contrato,

        -- medidas. El cero no es un valor faltante en este dataset: es la
        -- forma en que la fuente reporta 'todavia no se ha pagado'.
        coalesce(try_cast(valor_del_contrato       as double), 0.0) as valor_del_contrato,
        coalesce(try_cast(valor_pagado             as double), 0.0) as valor_pagado,
        coalesce(try_cast(valor_facturado          as double), 0.0) as valor_facturado,
        coalesce(try_cast(valor_pendiente_de_pago  as double), 0.0) as valor_pendiente_de_pago,

        _ingestado_en

    from bronze

),

identidad_proveedor as (

    select
        *,

        -- El 6,1 % de los contratos trae 'No Definido', '0', '000000000' y
        -- similares en documento_proveedor: casi siempre consorcios y uniones
        -- temporales sin NIT propio. Son 3.889 proveedores distintos, y usar
        -- ese campo como clave los colapsaria todos en una sola fila de la
        -- dimension.
        case
            when documento_proveedor is null then true
            when not regexp_full_match(documento_proveedor, '\d+') then true
            when length(regexp_replace(documento_proveedor, '^0+', '')) < 5 then true
            else false
        end as documento_es_centinela

    from tipado

)

select
    *,

    -- Identidad del proveedor: el documento cuando sirve, y el nombre
    -- normalizado cuando no. Partir por (documento, nombre) habria sido mas
    -- simple pero duplicaria al proveedor escrito de dos maneras, que es
    -- justo lo que una dimension debe evitar.
    case
        when documento_es_centinela
            then 'NOMBRE:' || {{ sin_tildes('proveedor_adjudicado') }}
        else documento_proveedor
    end as identidad_proveedor

from identidad_proveedor
