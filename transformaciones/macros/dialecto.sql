{#
  Las diferencias de dialecto entre DuckDB y BigQuery, en un solo archivo.

  El proyecto corre en los dos motores con los MISMOS modelos:

      dbt build                   DuckDB local, 3 s, gratis
      dbt build --target cloud    BigQuery

  CRITERIO
  --------
  Primero se busca SQL que funcione igual en los dos y no se ramifica. Solo
  cuando no hay equivalente se escribe aqui un macro con las dos ramas y el
  motivo al lado. Abstraer una diferencia que no existe es peor que no
  abstraer nada.

  Lo que NO necesito envolver, porque los dos motores lo entienden igual:

      cast(x as INT64)   cast(x as STRING)   cast(x as BOOL)
      select * except (col)        extract(YEAR from fecha)
      concat(a, b)  ·  a || b      row_number() over (...)
      coalesce  nullif  trim  upper  substr  length  regexp_replace

  Comprobado contra DuckDB 2.0 el 2026-10-30, ejecutando cada una.
#}


{#
  MD5 en hexadecimal. **Esta es la que casi se cuela mal.**

  Los dos motores tienen md5(), pero devuelven cosas distintas:

      DuckDB     md5(x)  ->  VARCHAR, YA es el hexadecimal
      BigQuery   MD5(x)  ->  BYTES,   hay que pasarlo por TO_HEX

  Si se escribiera to_hex(md5(x)) para los dos, en DuckDB se codificaria dos
  veces: to_hex('6804...') devuelve el hex de ese TEXTO, no el digest. Daria
  244182854840759190 en vez de 468445596631364263, y lo peor es que no falla:
  devuelve un numero perfectamente valido, solo que distinto en cada motor.
  Las claves dejarian de coincidir y nadie se enteraria hasta comparar.
#}
{% macro md5_hex(expr) -%}
    {%- if target.type == 'bigquery' -%}
        to_hex(md5({{ expr }}))
    {%- else -%}
        md5({{ expr }})
    {%- endif -%}
{%- endmacro %}


{# El tipo de punto flotante. DuckDB no conoce FLOAT64 ni BigQuery DOUBLE. #}
{% macro tipo_real() -%}
    {%- if target.type == 'bigquery' -%}FLOAT64{%- else -%}DOUBLE{%- endif -%}
{%- endmacro %}


{#
  Casteo que no revienta: devuelve nulo si el valor no se puede convertir.

  Es deliberado en toda la capa silver. Una fila mala entre 66.875 no debe
  tumbar la corrida entera; se vuelve nula y queda visible en los tests.
#}
{% macro castear_seguro(expr, tipo) -%}
    {%- if target.type == 'bigquery' -%}
        safe_cast({{ expr }} as {{ tipo }})
    {%- else -%}
        try_cast({{ expr }} as {{ tipo }})
    {%- endif -%}
{%- endmacro %}


{# AND de todas las filas del grupo. Solo cambia el nombre. #}
{% macro y_logico(expr) -%}
    {%- if target.type == 'bigquery' -%}
        logical_and({{ expr }})
    {%- else -%}
        bool_and({{ expr }})
    {%- endif -%}
{%- endmacro %}


{# Fecha a texto. Ojo: BigQuery pone el formato PRIMERO y la fecha despues. #}
{% macro formato_fecha(columna, formato) -%}
    {%- if target.type == 'bigquery' -%}
        format_date('{{ formato }}', {{ columna }})
    {%- else -%}
        strftime({{ columna }}, '{{ formato }}')
    {%- endif -%}
{%- endmacro %}


{# Construir una fecha a partir de anio, mes y dia. #}
{% macro fecha_de(anio, mes, dia) -%}
    {%- if target.type == 'bigquery' -%}
        date({{ anio }}, {{ mes }}, {{ dia }})
    {%- else -%}
        make_date({{ anio }}, {{ mes }}, {{ dia }})
    {%- endif -%}
{%- endmacro %}


{#
  Dias entre dos fechas. **La otra trampa del dialecto.**

  Los dos tienen date_diff, pero con los argumentos EN ORDEN DISTINTO:

      DuckDB     date_diff('day', desde, hasta)
      BigQuery   date_diff(hasta, desde, DAY)

  Equivocarse no rompe nada: devuelve el mismo numero con el signo cambiado.
  Un contrato de 90 dias pasaria a durar -90, la bandera de duracion seguiria
  calculandose y ningun test de estructura lo notaria. Por eso este macro
  nombra sus parametros (desde, hasta) en vez de dejar el orden al azar.
#}
{% macro dias_entre(desde, hasta) -%}
    {%- if target.type == 'bigquery' -%}
        date_diff({{ hasta }}, {{ desde }}, DAY)
    {%- else -%}
        date_diff('day', {{ desde }}, {{ hasta }})
    {%- endif -%}
{%- endmacro %}


{#
  Percentil continuo como funcion de ventana.

  DuckDB lo llama quantile_cont y BigQuery percentile_cont. DuckDB tambien
  tiene percentile_cont, pero solo en la forma WITHIN GROUP, que es agregacion
  y no ventana: aqui hace falta la ventana para calcular el p99 de cada
  modalidad sin colapsar las filas.
#}
{% macro percentil(expr, p) -%}
    {%- if target.type == 'bigquery' -%}
        percentile_cont({{ expr }}, {{ p }})
    {%- else -%}
        quantile_cont({{ expr }}, {{ p }})
    {%- endif -%}
{%- endmacro %}


{#
  El patron casa con TODA la cadena. El patron se pasa ya anclado con ^ y $,
  asi que solo cambia el nombre de la funcion.
#}
{% macro coincide_completo(columna, patron) -%}
    {%- if target.type == 'bigquery' -%}
        regexp_contains({{ columna }}, r'^{{ patron }}$')
    {%- else -%}
        regexp_matches({{ columna }}, '^{{ patron }}$')
    {%- endif -%}
{%- endmacro %}


{#
  Texto sin tildes, para agrupar grafias del mismo nombre.

  DuckDB trae strip_accents. BigQuery no, y se arma con NORMALIZE en forma
  NFD, que separa la letra de su tilde en dos caracteres, y luego borrando
  los diacriticos combinantes (la categoria Unicode \pM).
#}
{% macro quitar_tildes(expr) -%}
    {%- if target.type == 'bigquery' -%}
        regexp_replace(normalize({{ expr }}, NFD), r'\pM', '')
    {%- else -%}
        strip_accents({{ expr }})
    {%- endif -%}
{%- endmacro %}


{#
  Una fila por dia entre dos fechas, ambas incluidas.

  Los dos devuelven un arreglo que hay que desplegar con unnest; lo que
  cambia es como se genera.
#}
{% macro serie_de_fechas(inicio, fin) -%}
    {%- if target.type == 'bigquery' -%}
        generate_date_array({{ inicio }}, {{ fin }}, interval 1 day)
    {%- else -%}
        generate_series({{ inicio }}, {{ fin }}, interval 1 day)
    {%- endif -%}
{%- endmacro %}


{#
  Elemento de una lista, contando DESDE 1.

  DuckDB indexa desde 1 y BigQuery desde 0. Se expone la version de DuckDB
  porque es la que se lee natural con un numero de mes, y aqui se resta.
#}
{% macro elemento(lista, posicion) -%}
    {%- if target.type == 'bigquery' -%}
        {{ lista }}[offset({{ posicion }} - 1)]
    {%- else -%}
        {{ lista }}[{{ posicion }}]
    {%- endif -%}
{%- endmacro %}
