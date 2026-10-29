{{ config(materialized = 'table') }}

-- Dimension de un solo atributo. La forma es identica en las cuatro, asi que
-- la definicion vive una sola vez en el macro dimension_simple.
{{ dimension_simple('tipo_de_contrato', 'tipo_contrato') }}
