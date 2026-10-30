{#
  Claves subrogadas deterministas.

  El ETL anterior asignaba las claves con range(1, n+1) sobre un conjunto
  ordenado. Eso parece inofensivo y no lo es: si el origen trae una entidad
  nueva que ordena en la mitad, se renumeran todas las que van despues, y el
  entidad_key de ayer apunta a otra entidad hoy. Con claves asi no se puede
  hacer una carga incremental, porque no hay nada estable contra lo que hacer
  MERGE.

  Aqui la clave sale de un hash de la clave natural. Tres propiedades:

  - Determinista y sin estado: se clona el repo, se corre, y salen las mismas
    claves. La alternativa clasica de bodega (un registro persistente que
    asigna 1, 2, 3... y nunca los reutiliza) viviria en data/, que no se
    versiona, y se perderia al clonar. Ese registro si hara falta el dia que
    se implemente SCD2.
  - Estable ante filas nuevas: una entidad nueva no mueve la clave de ninguna
    otra.
  - **Igual en DuckDB y en BigQuery.** Ver abajo.
#}


{#
  La clave: los primeros 15 digitos hexadecimales del MD5 de la clave
  natural, leidos como entero.

  POR QUE MD5 Y NO EL HASH NATIVO
  -------------------------------
  Antes era hash() de DuckDB enmascarado a 63 bits. Funcionaba, pero hash()
  no existe en BigQuery, y su equivalente FARM_FINGERPRINT da otro numero.
  Las claves habrian sido distintas en cada motor y las dos tablas no se
  podrian comparar directamente.

  MD5 esta en los dos y da el mismo digest, asi que la misma entidad obtiene
  la misma clave corra donde corra. Eso permite comparar las tablas gold de
  DuckDB y de BigQuery incluyendo las claves, que es una igualdad mas fuerte
  que comparar solo los atributos.

  POR QUE 15 DIGITOS
  ------------------
  15 hexadecimales son 60 bits: entran de sobra en el int64 que el modelo
  semantico de Power BI declara para las columnas *_key, y siempre salen
  positivos, sin tener que enmascarar el bit de signo. Con 34.031 proveedores
  la probabilidad de colision es de unos 5 en 10.000 millones.

  El separador '|' y el centinela para nulos evitan que ('AB', 'C') y
  ('A', 'BC') produzcan la misma clave.
#}
{% macro clave_subrogada(columnas) -%}
    {%- set partes = [] -%}
    {%- for c in columnas -%}
        {%- do partes.append("coalesce(cast(" ~ c ~ " as STRING), '∅')") -%}
    {%- endfor -%}
    cast(
        '0x' || substr({{ md5_hex(partes | join(" || '|' || ")) }}, 1, 15)
        as INT64
    )
{%- endmacro %}


{#
  El valor mas frecuente del grupo, con el empate resuelto alfabeticamente.

  Antes esto eran dos macros (histograma() y moda_de()) apoyados en el tipo
  MAP de DuckDB y en map_keys/map_values, que BigQuery no tiene. Portarlo
  obligo a reescribirlo con un conteo y un row_number, y el resultado es mas
  claro que el original: se lee lo que hace sin saber que es un histograma.
  Es el caso tipico en que eliminar la diferencia sale mejor que abstraerla.

  No se usa mode() de DuckDB porque no define como rompe los empates, y una
  dimension cuyo contenido cambia entre dos corridas identicas no es
  idempotente: justo lo que esta capa existe para garantizar.

  Devuelve una consulta con las columnas de 'claves' mas la columna 'columna'
  con su valor mas frecuente. Se usa como CTE y se une por las claves.
#}
{% macro moda_por_grupo(relacion, claves, columna) -%}
    {%- set lista_claves = claves | join(', ') -%}
    select {{ lista_claves }}, {{ columna }}
    from (
        select
            {{ lista_claves }},
            {{ columna }},
            -- El alias lleva guion bajo delante para que no choque con la
            -- columna de la que se saca la moda: dim_entidad la usa sobre
            -- una columna que se llama 'orden', y sin el prefijo DuckDB
            -- intentaba castear 'Territorial' al numero de fila.
            row_number() over (
                partition by {{ lista_claves }}
                order by count(*) desc, {{ columna }} asc
            ) as _fila_moda
        from {{ relacion }}
        where {{ columna }} is not null
        group by {{ lista_claves }}, {{ columna }}
    ) ordenados
    where _fila_moda = 1
{%- endmacro %}


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
{% macro clave_fecha(columna) -%}
    case
        when extract(year from {{ columna }})
             between {{ var('anio_min') }} and {{ var('anio_max') }}
        then cast({{ formato_fecha(columna, '%Y%m%d') }} as INT64)
    end
{%- endmacro %}
