{{ config(severity='error') }}

--  Los importes tienen que seguir siendo DECIMAL exacto, en los dos motores.
--
--  POR QUE HACE FALTA UN TEST PARA ESTO
--  ------------------------------------
--  En BigQuery el supertipo de NUMERIC y FLOAT64 es FLOAT64. Asi que un solo
--  `0.0` mal puesto -en un coalesce, en un case, en una resta- devuelve la
--  columna a punto flotante sin que nada falle: compila, corre, pasa los 72
--  tests y entrega un numero creible. La decision D7 se desharia sola y nadie
--  se enteraria hasta comparar los dos motores a mano.
--
--  COMO LO DETECTA
--  ---------------
--  Suma la columna tal como esta, y suma la MISMA columna casteada al tipo
--  exacto. Si la columna ya es decimal, el casteo no hace nada y las dos sumas
--  son identicas. Si la columna se hubiera vuelto flotante, la suma de la
--  izquierda pierde los centavos -el registro corrupto de D5 lleva el
--  acumulado a 6,45 cuatrillones, donde la distancia entre dos float64
--  consecutivos es de un peso- y la de la derecha no.
--
--  Medido: con FLOAT64 la diferencia era de 4,10 pesos. Suficiente para que
--  este test dispare, y no detectable de ninguna otra forma automatica.
--
--  El test se apoya en que el universo CONTIENE el registro corrupto. Si D5
--  cambiara y ese contrato dejara de llevar importe, este test dejaria de
--  tener con que disparar: habria que revisarlo, no borrarlo.

with sumas as (

    select
        {%- for importe in ['valor_contratado', 'valor_pagado',
                            'valor_facturado', 'valor_pendiente'] %}
        sum({{ importe }}) as {{ importe }}_tal_cual,
        sum(cast({{ importe }} as {{ tipo_dinero() }})) as {{ importe }}_exacto
        {%- if not loop.last %},{% endif %}
        {%- endfor %}

    from {{ ref('hecho_contratos') }}

)

{% for importe in ['valor_contratado', 'valor_pagado',
                   'valor_facturado', 'valor_pendiente'] %}
select
    '{{ importe }}' as importe,
    {{ importe }}_tal_cual as suma_tal_cual,
    {{ importe }}_exacto   as suma_exacta
from sumas
where {{ importe }}_tal_cual <> {{ importe }}_exacto
{% if not loop.last %}union all{% endif %}
{% endfor %}
