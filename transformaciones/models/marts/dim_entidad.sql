{{ config(materialized = 'table') }}

-- Grano: la unidad que contrata, no la entidad juridica.
--
-- Un mismo NIT agrupa varias unidades. El NIT 899999034 es el SENA y trae 81
-- nombres distintos (SENA Regional Atlantico, Regional Caldas...). El informe
-- pregunta *quien contrata*, y esas regionales contratan por separado, asi
-- que el grano es (nit, nombre): 3.057 unidades sobre 2.692 NIT.
--
-- Se conserva nit_entidad como atributo para poder agregar a entidad juridica
-- cuando haga falta.

with conteos as (

    select
        nit_entidad,
        nombre_entidad,

        -- departamento y ciudad varian dentro de la unidad en 6 y 5 casos de
        -- 3.057. Se resuelve con el valor mas frecuente: una dimension no
        -- puede tener dos filas para la misma unidad solo porque un contrato
        -- trae la ciudad mal diligenciada.
        {{ histograma('departamento') }} as h_departamento,
        {{ histograma('ciudad') }}       as h_ciudad,
        {{ histograma('orden') }}        as h_orden,

        count(*)::BIGINT as contratos

    from {{ ref('int_contratos_calidad') }}
    group by nit_entidad, nombre_entidad

)

select
    {{ clave_subrogada(['nit_entidad', 'nombre_entidad']) }} as entidad_key,
    nit_entidad,
    nombre_entidad,
    {{ moda_de('h_departamento') }} as departamento,
    {{ moda_de('h_ciudad') }}       as ciudad,
    {{ moda_de('h_orden') }}        as orden,
    contratos
from conteos
