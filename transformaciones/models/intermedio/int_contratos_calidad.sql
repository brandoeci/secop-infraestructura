{{ config(materialized = 'table') }}

-- Banderas de calidad, anadidas en vez de borrar filas.
--
-- Marcar y no borrar es deliberado: una fila que desaparece del modelo no
-- deja rastro de que existio, y el vacio de reporte es parte de lo que el
-- informe describe. Las medidas DAX que hablan de dinero filtran por
-- valor_confiable; las que cuentan contratos, no.

with contratos as (

    select * from {{ ref('stg_contratos') }}

),

marcado as (

    select
        *,

        -- Un unico registro, diagnosticado como error de digitacion en
        -- docs/calidad-datos.md: un contrato de minima cuantia por 6,45
        -- cuatrillones de pesos que explicaba el 98,6 % del valor total.
        id_contrato <> '{{ var("contrato_corrupto") }}' as valor_confiable,

        -- True solo donde el contrato ya termino, asi que el % ejecutado se
        -- puede medir sin que los contratos aun en curso lo hundan. Esa
        -- distincion es el hallazgo central del informe: 13,4 % sobre todo
        -- el universo contra 46,8 % acotado aqui. Ver docs/decisiones.md, D4.
        estado_contrato in ('Cerrado', 'Terminado') as pago_exigible,

        valor_pagado > valor_del_contrato as pagado_excede,

        -- Un contrato no puede terminar antes de firmarse. Son unos 200
        -- casos, mas uno con la fecha de fin en el anio 0206.
        coalesce(
            fecha_de_fin_del_contrato >= fecha_de_firma
            and year(fecha_de_fin_del_contrato)
                between {{ var('anio_min') }} and {{ var('anio_max') }},
            false
        ) as fechas_coherentes,

        -- La duracion se deja nula cuando saldria negativa: un numero
        -- negativo de dias no es una duracion corta, es un dato malo, y
        -- promediarlo contaminaria la medida.
        case
            when date_diff('day', fecha_de_inicio_del_contrato,
                                  fecha_de_fin_del_contrato) >= 0
            then date_diff('day', fecha_de_inicio_del_contrato,
                                  fecha_de_fin_del_contrato)
        end::INTEGER as duracion_dias

    from contratos

),

referencia_p99 as (

    select
        *,

        -- Cuanto vale el p99 de la propia modalidad de contratacion.
        --
        -- Se compara contra la modalidad y no contra el universo porque la
        -- modalidad refleja un rango de cuantia definido por ley: un atipico
        -- en minima cuantia no es lo mismo que uno en licitacion publica.
        -- Ver docs/decisiones.md, D3.
        --
        -- El p99 se calcula solo sobre las filas confiables, para que el
        -- registro corrupto no infle el umbral que deberia delatarlo.
        quantile_cont(
            case when valor_confiable then valor_del_contrato end, 0.99
        ) over (partition by modalidad_de_contratacion) as p99_modalidad

    from marcado

)

select
    * exclude (p99_modalidad),

    case
        when p99_modalidad > 0
        then round(valor_del_contrato / p99_modalidad, 2)
    end as veces_p99_modalidad

from referencia_p99
