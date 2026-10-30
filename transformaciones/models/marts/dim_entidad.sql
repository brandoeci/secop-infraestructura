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

with base as (

    select * from {{ ref('int_contratos_calidad') }}

),

unidades as (

    select
        nit_entidad,
        nombre_entidad,
        cast(count(*) as INT64) as contratos
    from base
    group by nit_entidad, nombre_entidad

),

-- departamento, ciudad y orden varian dentro de la unidad en 6, 5 y algunos
-- casos de 3.057. Se resuelve con el valor mas frecuente: una dimension no
-- puede tener dos filas para la misma unidad solo porque un contrato trae la
-- ciudad mal diligenciada.
departamento_frecuente as (
    {{ moda_por_grupo('base', ['nit_entidad', 'nombre_entidad'], 'departamento') }}
),

ciudad_frecuente as (
    {{ moda_por_grupo('base', ['nit_entidad', 'nombre_entidad'], 'ciudad') }}
),

orden_frecuente as (
    {{ moda_por_grupo('base', ['nit_entidad', 'nombre_entidad'], 'orden') }}
)

select
    {{ clave_subrogada(['u.nit_entidad', 'u.nombre_entidad']) }} as entidad_key,
    u.nit_entidad,
    u.nombre_entidad,
    d.departamento,
    c.ciudad,
    o.orden,
    u.contratos
from unidades u
-- El coalesce en el join no es adorno: hoy no hay nulos en nit ni en nombre,
-- pero un JOIN normal no casa NULL con NULL, y el dia que aparezca uno la
-- unidad perderia sus atributos sin que nada fallara.
left join departamento_frecuente d
       on coalesce(u.nit_entidad, '∅')    = coalesce(d.nit_entidad, '∅')
      and coalesce(u.nombre_entidad, '∅') = coalesce(d.nombre_entidad, '∅')
left join ciudad_frecuente c
       on coalesce(u.nit_entidad, '∅')    = coalesce(c.nit_entidad, '∅')
      and coalesce(u.nombre_entidad, '∅') = coalesce(c.nombre_entidad, '∅')
left join orden_frecuente o
       on coalesce(u.nit_entidad, '∅')    = coalesce(o.nit_entidad, '∅')
      and coalesce(u.nombre_entidad, '∅') = coalesce(o.nombre_entidad, '∅')
