{# Equivalentes SQL de las funciones de limpieza de etl/transformar.py. #}

{# Quita espacios sobrantes y saltos de linea dentro del propio campo. #}
{% macro normalizar_texto(c) %}
    nullif(trim(regexp_replace(cast({{ c }} as varchar), '\s+', ' ', 'g')), '')
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


{# Version comparable de un texto, para agrupar grafias del mismo nombre. #}
{% macro sin_tildes(c) %}
    trim(regexp_replace(
        regexp_replace(upper(strip_accents(coalesce(cast({{ c }} as varchar), ''))),
                       '[^A-Z0-9 ]', '', 'g'),
        '\s+', ' ', 'g'))
{% endmacro %}
