-- Contratos donde lo pagado supera lo contratado.
--
-- Son 43 hoy. Dejarian el % ejecutado por encima del 100 %, asi que conviene
-- tenerlos contados antes de que alguien pregunte por un indicador del 140 %.
{{ config(severity = 'warn', warn_if = '>0', error_if = '>200') }}

select id_contrato, valor_contratado, valor_pagado
from {{ ref('hecho_contratos') }}
where pagado_excede
