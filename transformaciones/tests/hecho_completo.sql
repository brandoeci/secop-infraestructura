{#
  El hecho tiene que tener exactamente las mismas filas que el silver del que sale.

  POR QUE EXISTE
  --------------
  El 2026-11-06 un borrado mal puesto dejo hecho_contratos en CERO filas, y
  los 74 tests pasaron en verde. Todos. Porque not_null, unique y
  relationships se cumplen por vacuidad: sobre una tabla sin filas no hay
  nada que violar. El gate dejo publicar una tabla vacia.

  Este test cierra ese hueco, y el umbral no es inventado: es la invariante
  real del modelo. int_contratos_calidad tiene una fila por contrato y el
  hecho sale de ahi con una union contra 30 filas de referencia, asi que la
  correspondencia es 1 a 1. Si los conteos difieren, algo se perdio o algo
  se quedo.

  Vigila las dos direcciones, y por eso tambien es el test de la decision D8:
    * en_gold < en_silver  -> se perdieron filas (el caso de la tabla vacia)
    * en_gold > en_silver  -> quedaron filas retiradas que el post_hook
                              tenia que haber borrado, o sea D8 no se cumple
#}

with conteos as (

    select
        (select count(*) from {{ ref('int_contratos_calidad') }}) as en_silver,
        (select count(*) from {{ ref('hecho_contratos') }})       as en_gold

)

select
    en_silver,
    en_gold,
    en_gold - en_silver as diferencia
from conteos
where
{%- if var('origen_completo', false) %}
    {# bronze es el universo completo: la correspondencia es exactamente 1 a 1 #}
    en_silver <> en_gold
{%- else %}
    {# bronze puede ser parcial -descargar.py --desde-, asi que el hecho PUEDE
       tener mas filas que el origen: las de los contratos viejos que esta
       carga no trajo. Lo que no puede es tener MENOS, que es haber perdido
       filas. El caso de la tabla vacia cae aqui igual: 0 < 67.299. #}
    en_gold < en_silver
{%- endif %}
