-- Contratos que terminan antes de firmarse.
--
-- Son 200 hoy. La fila se conserva y queda marcada con
-- fechas_coherentes = false: borrarla no dejaria rastro de que existio.
{{ config(severity = 'warn', warn_if = '>0', error_if = '>500') }}

select id_contrato, fecha_firma_key, fecha_fin_key
from {{ ref('hecho_contratos') }}
where not fechas_coherentes
