-- Ningun contrato debe superar 100.000 veces la mediana de su modalidad.
--
-- Es la regla que habria atrapado sola el error que se encontro a mano: un
-- contrato de minima cuantia registrado por 6,45 cuatrillones de pesos, que
-- explicaba el 98,6 % del valor del universo entero. Se tardaron horas en
-- verlo; con este test la corrida se habria detenido en la primera.
--
-- Dos decisiones, y las dos salieron de que la primera version del test no
-- funcionaba:
--
-- 1. Contra una proporcion interna de la modalidad, no contra una fraccion
--    del valor total. La fraccion del total depende de cuantas filas haya:
--    el contrato mas grande pesa 1,55 % sobre el universo completo y 12,54 %
--    sobre una muestra de 280 filas. Un umbral asi saltaria por el tamano de
--    la muestra y no por un error, y un control que depende de cuantos datos
--    le toquen no es un control.
--
-- 2. Contra la MEDIANA y no contra el p99. El p99 parecia la referencia
--    natural, siendo la misma de la decision D3, pero no sirve aqui: en una
--    modalidad con pocos contratos, el registro corrupto entra en el calculo
--    de su propio p99 y lo infla, asi que la razon vuelve a ser cerca de 1 y
--    el test no dispara. Se comprobo en el fixture de 280 filas, donde el
--    error inyectado pasaba sin que nadie lo cazara. La mediana es robusta:
--    una sola fila extrema, por grande que sea, la mueve una posicion.
--
-- Umbral 100.000x, con los datos medidos el 2026-10-29 sobre el universo:
--
--   contrato legitimo mas extremo                  14.884x
--   contratos por encima de 100.000x (sin el corrupto)   0
--   el registro corrupto                      190.693.033x
--
-- Casi siete veces de holgura sobre el peor caso real, y aun asi mil
-- novecientas veces por debajo del error que tiene que cazar.
--
-- Se mide solo sobre las filas confiables, es decir excluyendo los errores
-- ya diagnosticados y marcados: lo que se vigila es que aparezca uno NUEVO.
-- Los atipicos normales (mas de 10x el p99, hoy 27) los cubre
-- tests/atipicos_sobre_p99.sql con severidad de aviso.
{{ config(severity = 'error') }}

with referencia as (

    select
        id_contrato,
        valor_del_contrato,
        modalidad_de_contratacion,
        median(valor_del_contrato) over (
            partition by modalidad_de_contratacion
        ) as mediana_modalidad
    from {{ ref('int_contratos_calidad') }}
    where valor_confiable

)

select
    id_contrato,
    modalidad_de_contratacion,
    valor_del_contrato,
    mediana_modalidad,
    round(valor_del_contrato / mediana_modalidad) as veces_la_mediana
from referencia
where mediana_modalidad > 0
  and valor_del_contrato / mediana_modalidad > 100000
