{{
    config(
        materialized         = 'incremental',
        unique_key           = 'id_contrato',
        incremental_strategy = 'merge',
        post_hook            = "{{ borrar_filas_retiradas('int_contratos_calidad', 'id_contrato') }}",
    )
}}

-- Grano: un contrato.
--
-- Carga incremental con MERGE sobre id_contrato. Esto solo es posible porque
-- las claves subrogadas son deterministas: con las claves posicionales de
-- antes, una entidad nueva renumeraba las demas y el MERGE habria actualizado
-- filas antiguas con claves que apuntaban a otra entidad.
--
-- El MERGE inserta y actualiza, pero no sabe que hacer con una fila que ya no
-- esta en el origen. De eso se encarga el post_hook: borra las claves que
-- desaparecieron. Es la decision D8, el hecho refleja el PRESENTE de SECOP.
--
-- El borrado NO puede ir como 'when not matched by source' dentro del MERGE,
-- porque el origen del MERGE es el delta de aqui abajo y no el universo: con
-- un delta de 0 filas, esa clausula borra la tabla completa. Pasó de verdad.
-- El motivo esta escrito en macros/borrar_filas_retiradas.sql.
--
-- La consecuencia es que las cifras se mueven entre corridas, y por eso toda
-- cifra del README va fechada. La alternativa -conservar la fila marcada como
-- retirada- se descarto en D8: obligaba a SCD Type 2 en dim_entidad y a que
-- cada medida del informe filtrara por 'vigente'.
--
-- Las claves foraneas no se resuelven con un JOIN contra cada dimension, sino
-- recalculando el mismo hash sobre la misma clave natural. Como la clave
-- subrogada es una funcion pura de la clave natural, las dos formas dan el
-- mismo resultado, pero esta no puede producir huerfanas por construccion y
-- se ahorra seis uniones. Los tests de relationships lo comprueban igual,
-- porque una propiedad que no se verifica es una suposicion.

with contratos as (

    select * from {{ ref('int_contratos_calidad') }}

),

-- Unica union del modelo, y es contra DATOS DE REFERENCIA (30 filas), no
-- contra una dimension: hace falta para traducir el nombre del departamento
-- al codigo de territorial, que es la clave natural desde la que se calcula
-- el hash. Sin esta traduccion no hay clave natural que hashear.
--
-- Se compara sin tildes y en mayusculas porque los dos origenes escriben los
-- nombres a su manera. El unico caso que difiere de verdad es Guajira contra
-- La Guajira, y esa equivalencia esta declarada como dato en el seed.
territoriales as (

    select
        {{ sin_tildes('departamento_secop') }} as departamento_comparable,
        codigo
    from {{ ref('territoriales_invias') }}
    where departamento_secop is not null

),

final as (

    select
        id_contrato,

        -- claves foraneas
        {{ clave_subrogada(['nit_entidad', 'nombre_entidad']) }} as entidad_key,
        {{ clave_subrogada(['identidad_proveedor']) }}           as proveedor_key,

        -- Nulas cuando el atributo no viene: la dimension no tiene fila para
        -- un valor que no existe, y apuntar a una fila inventada seria peor.
        case when tipo_de_contrato is not null
             then {{ clave_subrogada(['tipo_de_contrato']) }} end          as tipo_contrato_key,
        case when estado_contrato is not null
             then {{ clave_subrogada(['estado_contrato']) }} end           as estado_key,
        case when modalidad_de_contratacion is not null
             then {{ clave_subrogada(['modalidad_de_contratacion']) }} end as modalidad_key,

        -- Dimension de CONTEXTO: es el territorial del departamento donde
        -- esta registrada la entidad, no el de la via del contrato, porque el
        -- origen no dice cual es. Ver dim_territorial_vial.
        --
        -- A diferencia de las demas claves, esta nunca es nula: lo que no
        -- cruza apunta al centinela -1 ('Sin territorial'). Un nulo diria
        -- 'no se'; el centinela dice 'se comprobo y no tiene', que es
        -- distinto y es el 28% de los contratos.
        {{ clave_subrogada(['coalesce(t.codigo, -1)']) }} as territorial_key,
        case when codigo_de_categoria_principal is not null
             then {{ clave_subrogada(['codigo_de_categoria_principal']) }} end as categoria_key,

        -- Claves de fecha en formato yyyymmdd. Nulas fuera de la ventana
        -- plausible: la fila del hecho se conserva y queda marcada, que es
        -- mas honesto que inventar una fecha o que borrar el contrato.
        {{ clave_fecha('fecha_de_firma') }}               as fecha_firma_key,
        {{ clave_fecha('fecha_de_inicio_del_contrato') }} as fecha_inicio_key,
        {{ clave_fecha('fecha_de_fin_del_contrato') }}    as fecha_fin_key,

        -- medidas
        valor_del_contrato      as valor_contratado,
        valor_pagado,
        valor_facturado,
        valor_pendiente_de_pago as valor_pendiente,

        -- Texto largo y casi unico por contrato: atributo degenerado en el
        -- hecho, no una dimension con una fila por hecho.
        objeto_del_contrato,

        -- banderas de calidad
        valor_confiable,
        veces_p99_modalidad,
        pago_exigible,
        pagado_excede,
        fechas_coherentes,
        duracion_dias,

        -- Huella de todo lo que puede cambiar en un contrato entre dos
        -- corridas. Es lo que permite distinguir 'esta fila volvio a llegar
        -- igual' de 'esta fila cambio', y por tanto medir de verdad cuanto se
        -- movio el origen en vez de reescribirlo todo y decir que se
        -- actualizaron 66.875 filas.
        --
        -- No se exporta a data/curated/: es metadato del pipeline, no un
        -- atributo del contrato, y el modelo de Power BI no lo necesita.
        {{ clave_subrogada([
            'nit_entidad', 'nombre_entidad', 'departamento',
            'identidad_proveedor',
            'tipo_de_contrato', 'estado_contrato', 'modalidad_de_contratacion',
            'codigo_de_categoria_principal', 'objeto_del_contrato',
            'fecha_de_firma', 'fecha_de_inicio_del_contrato',
            'fecha_de_fin_del_contrato', 'valor_del_contrato', 'valor_pagado',
            'valor_facturado', 'valor_pendiente_de_pago',
        ]) }} as hash_atributos

    from contratos c
    left join territoriales t
        on t.departamento_comparable = {{ sin_tildes('c.departamento') }}

)

select * from final

{% if is_incremental() %}

-- Solo las filas nuevas o cuyo contenido cambio de verdad.
--
-- Sin este filtro el MERGE tocaria las 66.875 filas en cada corrida y diria
-- que actualizo todo, que es exactamente la falsa sensacion de trabajo que la
-- idempotencia existe para eliminar. Con el filtro, una segunda corrida sobre
-- el mismo bronze procesa 0 filas, y eso se puede probar:
-- python etl/probar_idempotencia.py
where not exists (
    select 1
    from {{ this }} anterior
    where anterior.id_contrato   = final.id_contrato
      and anterior.hash_atributos = final.hash_atributos
)

{% endif %}
