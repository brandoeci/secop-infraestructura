{{ config(materialized = 'table') }}

-- Grano: el proveedor. La clave depende de si el documento sirve.
--
-- - Documento valido (93,9 %): la identidad es el documento. 206 proveedores
--   traen el nombre con varias grafias; se toma la mas frecuente como nombre
--   canonico en lugar de partirlos en varias filas.
-- - Documento centinela (6,1 %): el nombre es la unica identidad disponible,
--   asi que la identidad se construye sobre el nombre sin tildes y la fila
--   queda marcada con tiene_documento = false. Son 3.889 proveedores que un
--   centinela colapsaria en una sola fila.

with base as (

    select * from {{ ref('int_contratos_calidad') }}

),

resumen as (

    select
        identidad_proveedor,
        not {{ y_logico('documento_es_centinela') }} as tiene_documento,
        cast(count(*) as INT64)                      as contratos
    from base
    group by identidad_proveedor

),

nombre_frecuente as (
    {{ moda_por_grupo('base', ['identidad_proveedor'], 'proveedor_adjudicado') }}
)

select
    {{ clave_subrogada(['r.identidad_proveedor']) }} as proveedor_key,
    case when r.tiene_documento then r.identidad_proveedor end as documento,
    n.proveedor_adjudicado as proveedor,
    r.tiene_documento,
    r.contratos
from resumen r
left join nombre_frecuente n
       on coalesce(r.identidad_proveedor, '∅') = coalesce(n.identidad_proveedor, '∅')
