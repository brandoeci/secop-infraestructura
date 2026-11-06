{{ config(severity='error') }}

--  Los importes tienen que seguir siendo DECIMAL exacto, en los dos motores.
--
--  POR QUE HACE FALTA UN TEST PARA ESTO
--  ------------------------------------
--  En BigQuery el supertipo de NUMERIC y FLOAT64 es FLOAT64. Asi que un solo
--  `0.0` mal puesto -en un coalesce, en un case, en una resta- devuelve la
--  columna a punto flotante sin que nada falle: compila, corre, pasa el resto
--  de los tests y entrega un numero creible. La decision D7 se desharia sola
--  y nadie se enteraria hasta comparar los dos motores a mano.
--
--  COMO LO DETECTA
--  ---------------
--  Suma la columna y luego castea el TOTAL al tipo exacto; aparte, castea
--  cada FILA al tipo exacto y suma. Si la columna ya es decimal las dos
--  cuentas son la misma cuenta. Si se hubiera vuelto flotante, la primera
--  acumula en flotante y pierde centavos por el camino, y la segunda no.
--
--  EL ORDEN DE LOS CASTEOS IMPORTA, Y ES LA TRAMPA QUE SE COLO PRIMERO
--  ------------------------------------------------------------------
--  La primera version comparaba `sum(x) <> sum(cast(x as decimal))`. Si x es
--  flotante, el motor tiene que comparar un FLOAT64 con un DECIMAL, y para
--  eso promueve el decimal a flotante: la diferencia se redondea y desaparece
--  justo antes de ser comprobada. El test se anulaba a si mismo.
--
--  Lo tapaba que sobre el universo real la diferencia es de 4,10 pesos, mayor
--  que el salto del flotante en ese rango, asi que ahi si disparaba. Sobre el
--  fixture del CI la diferencia son 0,23 centavos y NO disparaba. O sea que
--  el test pasaba en los dos sitios por dos motivos distintos, y en uno de
--  ellos por el motivo equivocado.
--
--  Casteando el total de la izquierda, los dos lados son decimales y la
--  comparacion es exacta. Comprobado sobre el fixture simulando la columna
--  degradada: 6.454.462.321.754.717,44 contra 6.454.462.321.754.716,77.
--
--  Para que haya algo que detectar, el universo tiene que contener un importe
--  lo bastante grande como para que el flotante pierda los centavos. El
--  registro corrupto de D5 lo garantiza, y por eso esta en el fixture del CI
--  aunque sea el dato que el proyecto marca como no confiable. Si D5 cambiara
--  y ese contrato dejara de llevar importe, este test se quedaria sin con que
--  disparar: habria que revisarlo, no borrarlo.

{% set importes = ['valor_contratado', 'valor_pagado',
                   'valor_facturado', 'valor_pendiente'] %}

with sumas as (

    select
        {%- for importe in importes %}
        cast(sum({{ importe }}) as {{ tipo_dinero() }}) as {{ importe }}_acumulado,
        sum(cast({{ importe }} as {{ tipo_dinero() }})) as {{ importe }}_exacto
        {%- if not loop.last %},{% endif %}
        {%- endfor %}

    from {{ ref('hecho_contratos') }}

)

{% for importe in importes %}
select
    '{{ importe }}' as importe,
    {{ importe }}_acumulado as suma_acumulada,
    {{ importe }}_exacto    as suma_exacta
from sumas
where {{ importe }}_acumulado <> {{ importe }}_exacto
{% if not loop.last %}union all{% endif %}
{% endfor %}
