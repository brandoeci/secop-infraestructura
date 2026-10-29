-- Contratos por valor cero o negativo.
--
-- Son 630 hoy. No se borran: un contrato en cero suele ser un registro
-- incompleto del origen, y que existan es parte de lo que el informe
-- describe. El umbral de error esta en 1.000 porque un salto de esa
-- magnitud ya no seria el ruido de siempre sino un cambio en el origen.
{{ config(severity = 'warn', warn_if = '>0', error_if = '>1000') }}

select id_contrato, valor_contratado
from {{ ref('hecho_contratos') }}
where valor_contratado <= 0
