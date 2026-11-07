{#
  Borra del hecho las filas cuya clave ya no esta en el origen.

  POR QUE NO ES UN 'WHEN NOT MATCHED BY SOURCE' DENTRO DEL MERGE
  --------------------------------------------------------------
  Era el primer intento y borro la tabla entera. El motivo: el modelo
  filtra su propio origen con is_incremental() para que el MERGE solo vea
  las filas nuevas o cambiadas -de eso vive la idempotencia-. Entonces el
  origen del MERGE es un DELTA, no el universo. Y 'not matched by source'
  contra un delta de 0 filas significa "ninguna fila del destino coincide",
  o sea: borrar todo.

  La leccion: 'WHEN NOT MATCHED BY SOURCE' solo es correcto si el origen del
  MERGE es el estado completo del presente. Con carga por delta hay que
  separar las dos operaciones.

  Asi que el borrado va aparte, en un post_hook, y compara contra el modelo
  de origen completo -no contra el delta-. Dos sentencias por corrida, pero
  cada una dice la verdad.

  Es la decision D8: el hecho refleja el PRESENTE de SECOP.

  LA GUARDA, QUE ES LO MAS IMPORTANTE DE ESTE ARCHIVO
  ---------------------------------------------------
  Borrar "lo que no esta en el origen" solo es correcto si el origen ES el
  universo completo del presente. Y aqui no siempre lo es: aterrizar.py
  SOBRESCRIBE bronze con lo que le den, y descargar.py --desde baja solo los
  contratos firmados despues de una fecha. pipeline.yml usa --desde en las
  corridas programadas. Con bronze parcial, este borrado se lleva todo lo
  demas.

  Por eso el borrado esta detras de la variable origen_completo, que por
  defecto es FALSE. Hay que declarar que bronze esta completo para que borre.
  La asimetria es deliberada: si se olvida la bandera en una corrida completa,
  quedan filas retiradas de mas y el test hecho_completo lo grita; si el valor
  por defecto fuera true y se olvidara en una corrida parcial, el hecho se
  vaciaria. Se elige el fallo que avisa sobre el fallo que destruye.
#}

{% macro borrar_filas_retiradas(modelo_origen, clave) %}

{%- if not var('origen_completo', false) %}

    {#
      No-op. El post_hook tiene que ser SQL valido igual, y tiene que valer en
      los DOS motores. Un 'select 1 where 1 = 0' no sirve: BigQuery no acepta
      WHERE sin FROM, aunque DuckDB lo deje pasar. Y un 'delete ... where 1=0'
      tampoco, porque el nivel gratuito de BigQuery bloquea el DML incluso
      cuando no toca ninguna fila. Un select de una constante vale en ambos.
    #}
    select 'borrado omitido: origen_completo no esta declarado' as nota

{%- else %}

    delete from {{ this }}
    where {{ clave }} not in (
        {# El 'is not null' no es decorativo: con un solo NULL en la subconsulta
           el NOT IN se vuelve desconocido para todas las filas y no borraria
           nada, fallando en silencio. #}
        select {{ clave }}
        from {{ ref(modelo_origen) }}
        where {{ clave }} is not null
    )

{%- endif %}

{% endmacro %}
