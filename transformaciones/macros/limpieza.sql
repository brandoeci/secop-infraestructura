{# Equivalentes SQL de las funciones de limpieza de etl/transformar.py. #}

{# Quita espacios sobrantes y saltos de linea dentro del propio campo. #}
{% macro normalizar_texto(c) %}
    nullif(trim({{ regex_reemplazar_global('cast(' ~ c ~ ' as STRING)', '\\s+', ' ') }}), '')
{% endmacro %}


{#
  Unifica la capitalizacion inconsistente de la fuente: SECOP II entrega
  'terminado' y 'cedido' en minuscula mientras el resto va capitalizado.

  Solo toca la primera letra. No fusiona valores: 'Contratacion directa' y
  'Contratacion Directa (con ofertas)' son modalidades legalmente distintas y
  tienen que seguir separadas.
#}
{% macro capitalizar(c) %}
    upper(substr({{ normalizar_texto(c) }}, 1, 1))
        || substr({{ normalizar_texto(c) }}, 2)
{% endmacro %}


{#
  Version comparable de un texto, para agrupar grafias del mismo nombre.
  quitar_tildes() vive en dialecto.sql porque es de las pocas que no tiene
  equivalente directo entre los dos motores.
#}
{% macro sin_tildes(c) %}
    {%- set base = 'upper(' ~ quitar_tildes("coalesce(cast(" ~ c ~ " as STRING), '')") ~ ')' -%}
    {%- set solo_alfanumerico = regex_reemplazar_global(base, '[^A-Z0-9 ]', '') -%}
    trim({{ regex_reemplazar_global(solo_alfanumerico, '\\s+', ' ') }})
{% endmacro %}
