-- Contratos cuya ejecucion empieza ANTES de la fecha de firma.
--
-- Son 20 el 2026-11-06, y NO son un indicio de irregularidad. Se miraron uno
-- por uno antes de escribir esto, y son dos cosas distintas:
--
-- 18 tienen un desfase de 3 a 6 anios, y 12 de ellos son de AEROCIVIL. Ocho
-- de esos doce llevan EXACTAMENTE la misma fecha de firma: el 2024-03-27.
-- Ocho obras no empezaron antes de firmarse el mismo dia por casualidad: lo
-- que paso es que se cargo un lote de contratos viejos a SECOP II esa fecha.
-- Para esos registros `fecha_de_firma` no dice cuando se firmo el contrato,
-- dice cuando se digito en el sistema.
--
-- Los otros 2 se adelantan 2 y 5 dias, que es demora administrativa normal:
-- la obra arranca y el papeleo se firma esa semana.
--
-- Por eso avisa y no rompe. No es un defecto del pipeline ni algo que se
-- pueda corregir aguas arriba: es como el origen registra las cargas
-- retroactivas, y va a seguir haciendolo. Son 20 sobre 64.813 contratos que
-- tienen las dos fechas. Si esto detuviera la publicacion, el informe no
-- saldria nunca.
--
-- El tope de error va en 60, tres veces lo medido. Por encima de eso ya no
-- seria una carga retroactiva ocasional sino un cambio en como el origen
-- escribe las fechas, y eso si hay que mirarlo antes de publicar nada.
{{ config(severity = 'warn', warn_if = '>0', error_if = '>60') }}

select id_contrato, fecha_firma_key, fecha_inicio_key
from {{ ref('hecho_contratos') }}
where fecha_firma_key > fecha_inicio_key
