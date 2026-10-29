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

with conteos as (

    select
        identidad_proveedor,
        {{ histograma('proveedor_adjudicado') }} as h_proveedor,
        not bool_and(documento_es_centinela)     as tiene_documento,
        count(*)::BIGINT                         as contratos

    from {{ ref('int_contratos_calidad') }}
    group by identidad_proveedor

)

select
    {{ clave_subrogada(['identidad_proveedor']) }} as proveedor_key,
    case when tiene_documento then identidad_proveedor end as documento,
    {{ moda_de('h_proveedor') }} as proveedor,
    tiene_documento,
    contratos
from conteos
