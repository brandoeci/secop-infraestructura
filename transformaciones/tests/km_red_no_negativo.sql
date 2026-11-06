-- Los kilometros de red salen de sumar longitudes, asi que un negativo solo
-- puede venir de un shape__length corrupto en el origen o de un error en el
-- casteo. Las dos cosas hay que verlas, no suponerlas.
--
-- Tambien comprueba que los totales cuadran: la suma de la dimension tiene
-- que ser la suma del staging, sin kilometros perdidos por el camino.

select 'km negativos' as problema, territorial, km_red
from {{ ref('dim_territorial_vial') }}
where km_red < 0

union all

select 'la dimension pierde kilometros', 'TOTAL', d.km - s.km
from (select sum(km_red) as km from {{ ref('dim_territorial_vial') }}) d
cross join (select sum(longitud_km) as km from {{ ref('stg_red_vial') }}) s
where abs(d.km - s.km) > 0.001
