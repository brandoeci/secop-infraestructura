-- dim_fecha tiene que quedarse dentro de la ventana plausible.
--
-- Severidad error: una fecha fuera de rango no es un dato feo, es una tabla
-- de fechas inservible. Un solo contrato con fecha de fin en el anio 0206
-- la estiro una vez a 675.699 dias, unos 1.850 anios, y con ella la
-- inteligencia de tiempo de Power BI deja de tener sentido.
{{ config(severity = 'error') }}

select fecha_key, anio
from {{ ref('dim_fecha') }}
where anio not between {{ var('anio_min') }} and {{ var('anio_max') }}
