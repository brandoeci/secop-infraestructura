{#
  Claves subrogadas deterministas.

  El ETL anterior asignaba las claves con range(1, n+1) sobre un conjunto
  ordenado. Eso parece inofensivo y no lo es: si el origen trae una entidad
  nueva que ordena en la mitad, se renumeran todas las que van despues, y el
  entidad_key de ayer apunta a otra entidad hoy. Con claves asi no se puede
  hacer una carga incremental, porque no hay nada estable contra lo que hacer
  MERGE.

  Aqui la clave sale de un hash de la clave natural. Dos propiedades:

  - Determinista y sin estado: se clona el repo, se corre, y salen las mismas
    claves. La alternativa clasica de bodega (un registro persistente que
    asigna 1, 2, 3... y nunca los reutiliza) viviria en data/, que no se
    versiona, y se perderia al clonar. Ese registro si hara falta el dia que
    se implemente SCD2.
  - Estable ante filas nuevas: una entidad nueva no mueve la clave de ninguna
    otra.

  hash() de DuckDB devuelve UBIGINT y desbordaria el int64 que el modelo
  semantico de Power BI declara para las columnas *_key, asi que se enmascara
  a 63 bits.
#}

{% macro clave_subrogada(columnas) %}
    (
        hash(
            {%- for c in columnas %}
            coalesce(cast({{ c }} as varchar), '∅')
            {%- if not loop.last %} || '|' || {% endif %}
            {%- endfor %}
        ) & 9223372036854775807
    )::BIGINT
{% endmacro %}


{#
  El valor mas frecuente del grupo, con el empate resuelto por orden
  alfabetico.

  Va en dos partes porque SQL no deja anidar agregaciones: primero
  histograma() dentro del GROUP BY, que deja un MAP de valor -> veces, y
  despues moda_de() sobre ese mapa.

  No se usa mode() de DuckDB porque no define como rompe los empates, y una
  dimension cuyo contenido cambia entre dos corridas identicas no es
  idempotente: justo lo que esta capa existe para garantizar. pandas resolvia
  el empate tomando el primero de mode(), que viene ordenado, y aqui se
  reproduce ese criterio de forma explicita.
#}
{% macro histograma(columna) %}
    histogram({{ columna }})
{% endmacro %}


{% macro moda_de(mapa) %}
    (
        select e.valor
        from (
            select unnest(map_keys({{ mapa }}))   as valor,
                   unnest(map_values({{ mapa }})) as veces
        ) e
        order by e.veces desc, e.valor asc
        limit 1
    )
{% endmacro %}


{#
  Dimension de un solo atributo: tipo de contrato, estado, modalidad,
  categoria. Cuatro tablas con la misma forma, una sola definicion.
#}
{% macro dimension_simple(columna, nombre) %}

with valores as (

    select distinct {{ columna }} as {{ nombre }}
    from {{ ref('int_contratos_calidad') }}
    where {{ columna }} is not null

)

select
    {{ clave_subrogada([nombre]) }} as {{ nombre }}_key,
    {{ nombre }}
from valores

{% endmacro %}


{#
  Clave de fecha yyyymmdd, nula si la fecha cae fuera de la ventana plausible
  de anios. La fila del hecho se conserva: se pierde la relacion con
  dim_fecha, no el contrato.
#}
{% macro clave_fecha(columna) %}
    case
        when year({{ columna }}) between {{ var('anio_min') }} and {{ var('anio_max') }}
        then (strftime({{ columna }}, '%Y%m%d'))::INTEGER
    end
{% endmacro %}
