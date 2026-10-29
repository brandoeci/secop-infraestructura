-- Contratos que superan 10 veces el p99 de su propia modalidad.
--
-- Son 27 hoy, y no son un defecto: son el contenido de la pagina 'Atipicos'
-- del informe. El test existe para que el numero no se dispare sin que nadie
-- se entere. Se compara contra la modalidad y no contra el universo porque la
-- modalidad refleja un rango de cuantia definido por ley (decision D3).
{{ config(severity = 'warn', warn_if = '>0', error_if = '>100') }}

select id_contrato, veces_p99_modalidad
from {{ ref('hecho_contratos') }}
where veces_p99_modalidad > 10
