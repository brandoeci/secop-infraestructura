# El proyecto en 60 segundos

Para decirlo en voz alta en una entrevista. Todas las cifras son reales y están respaldadas por
el repositorio: si alguien pregunta de dónde sale una, se corre el código.

---

## El párrafo

> Hice un proyecto de datos sobre en qué se gasta la plata de infraestructura en Colombia, con
> los datos abiertos de contratación del Estado. Son **seis millones de contratos** y noventa y
> cinco columnas.
>
> Lo primero fue acotarlo, y ahí estuvo la decisión que define el proyecto: **no hay una columna
> que diga «esto es obra».** Probé dos criterios, el tipo de contrato y el código de categoría
> del bien o servicio, y los medí los dos antes de elegir. Resultó que **casi no se solapan**:
> de sesenta y siete mil contratos, solo doce mil cumplen los dos. Así que el universo es la
> unión de ambos, y lo puedo defender con números en vez de con una corazonada.
>
> Con eso armé un **esquema en estrella** —un hecho de sesenta y siete mil contratos y siete
> dimensiones— con dbt sobre DuckDB, que alimenta un informe de Power BI de cuatro páginas.
>
> Y el hallazgo que más me gusta no es de negocio, es de **calidad de datos**: al sumar el valor
> contratado me daba cuatro veces el PIB del país. Era **un solo registro mal digitado que valía
> el noventa y ocho por ciento del total**.
>
> Lo último que hice fue convertirlo de un script en un **pipeline**: carga incremental con
> MERGE, y un control de calidad que **bloquea la publicación** si algo falla. Y las dos cosas
> están probadas, no afirmadas: hay un script que corre el pipeline dos veces y comprueba que la
> segunda no escribe nada, y otro que **inyecta un registro corrupto a propósito** y verifica
> que el informe no se actualiza.

Unos 60 segundos. Si hay menos tiempo, los dos primeros párrafos solos funcionan.

---

## Las preguntas que vienen después

### «¿Por qué no usaste Spark, con seis millones de filas?»

Porque el volumen no lo pedía. Con los filtros de alcance el universo queda en **66.875 filas**,
y a esa escala un clúster no aporta nada. Lo que sí justificaría Spark son los **26 gigas** del
dataset completo en crudo, y ese paso todavía no hace falta.

Prefiero poder explicar por qué **no** usé una herramienta a tenerla ahí de adorno.

### «¿Cómo supiste que ese contrato era un error y no un hallazgo?»

Porque el propio registro se contradice. Está clasificado como **mínima cuantía**, que es la
modalidad para las compras más pequeñas del Estado: de los 18.781 contratos de esa modalidad la
mediana son 33 millones de pesos y el percentil 99 son 169 millones. Ese registro es **38
millones de veces el percentil 99 de su propia modalidad**. Y duró menos de tres meses.

Antes de tratar una cifra escandalosa como hallazgo, hay que descartar que sea un error de
datos. En este caso lo era.

De ahí salió la regla de detección de atípicos del modelo: comparar cada contrato contra el
percentil 99 de **su propia modalidad**, no del universo completo, porque la modalidad refleja un
rango de cuantía definido por ley. Un atípico en mínima cuantía no es lo mismo que uno en
licitación pública.

### «¿Y qué hiciste con ese registro? ¿Lo borraste?»

No. Lo dejé en el modelo con una bandera `valor_confiable` en falso. Todas las medidas de dinero
filtran por esa bandera, así que no contamina ninguna suma, pero sigue visible en la página de
atípicos.

Borrarlo daba el mismo total y era más fácil. Pero una fila que desaparece no deja rastro de que
existió, y el informe describe **cómo se reporta** el gasto público: un registro con esa cifra es
parte de cómo se reporta.

### «¿Cuánto se ejecuta de lo contratado?»

Depende de cómo se mida, y esa es la parte interesante. **El 62 % de los contratos reporta cero
pagado.** En los que están aprobados o en ejecución eso es normal, todavía no tenían por qué
haber pagado nada.

Si calculo el porcentaje ejecutado sobre todo el universo da **13 %**, que no describe la
realidad. Acotándolo a contratos que ya terminaron da **47 %**.

Y aun así, **5.234 contratos ya terminados reportan cero pagado**. Eso no lo escondí: lo publiqué
como una medida propia del informe. Cuánto del gasto de infraestructura no tiene ejecución
reportada es un resultado en sí mismo.

### «¿Qué decisión de modelado te costó más?»

El grano de la dimensión de entidades. Lo obvio era usar el NIT como clave, pero el NIT del SENA
aparece con **81 nombres distintos**: son sus regionales, y cada una contrata por separado. Si
agrupo por NIT, el informe dice que el SENA contrata mucho y no dice cuál regional.

Así que el grano es la **unidad contratante**, no la entidad jurídica: 3.057 unidades sobre 2.692
NIT. El NIT se queda como atributo para poder agregar cuando haga falta.

Algo parecido pasó con los proveedores: el 6 % de los contratos trae el documento como «No
Definido» porque son consorcios y uniones temporales. Son 3.889 proveedores distintos que una
clave ingenua habría colapsado en una sola fila.

### «¿Seguridad a nivel de fila?»

Sí, implementada y documentada. Un rol dinámico que resuelve el departamento del usuario
conectado con `USERPRINCIPALNAME()` contra una tabla puente. Un rol por departamento serían 34
roles que hay que mantener a mano.

El detalle que conviene decir: filtra por el departamento **de la entidad contratante**, no por
dónde se ejecuta la obra. En este dataset el departamento describe a la entidad. La dirección de
ejecución existe pero es texto libre sin normalizar —2.475 valores distintos en 10.000 filas— y
no sirve como dimensión sin geocodificar.

---

### «¿Esto es ingeniería de datos o es un informe?»

Empezó siendo un informe y lo convertí en un pipeline, y sé exactamente cuál era la diferencia,
porque los tres agujeros eran concretos:

**Uno: las claves subrogadas eran posicionales.** Las asignaba con un `range(1, n+1)` sobre un
conjunto ordenado. Si el origen traía una entidad nueva que ordenaba en la mitad, se renumeraban
todas las de después, y la clave de ayer apuntaba a otra entidad hoy. Eso no es un detalle de
estilo: con claves así **no se puede hacer carga incremental**, no porque falte el MERGE, sino
porque no hay nada estable contra lo que hacerlo. Ahora la clave sale de un hash de la clave
natural: determinista, sin estado y estable ante filas nuevas.

**Dos: nada bloqueaba un dato malo.** Había un documento con los problemas de calidad, pero era
prosa que nadie comprobaba. Ahora son 67 tests de dbt, y la exportación a los Parquet que lee
Power BI va **después** de los tests: un modelo que no pasa nunca llega al informe.

**Tres: nada lo corría y un fallo era silencioso.** Era `python etl/transformar.py` cuando me
acordaba. Ahora corre en GitHub Actions, en cada push contra un fixture y en cron semanal contra
la API, y cada corrida deja una fila en una bitácora con su resultado.

### «¿Cómo sabes que el control de calidad funciona?»

Porque lo rompo a propósito. `etl/probar_gate.py` inyecta en la capa bronze un contrato con el
mismo perfil del error real y comprueba tres cosas: que `dbt build` falla con código distinto de
cero, que lo caza el test escrito para eso, y sobre todo que **los Parquet del informe quedan
byte a byte idénticos**.

Y el test de calidad más importante tuvo **dos versiones malas**, que descubrió el fixture de
280 filas del CI. La primera medía la concentración como fracción del valor total, y eso depende
del tamaño del dataset: el contrato más grande pesa 1,55 % sobre el universo completo y 12,54 %
sobre 280 filas, así que el test saltaba por el tamaño de la muestra. La segunda medía contra el
p99 de la modalidad, y falló por algo más sutil: en una modalidad con pocos contratos, **el
registro corrupto entra en el cálculo de su propio p99 y lo infla**, así que la razón vuelve a
ser cerca de uno y el test no dispara. La versión que funciona mide contra la **mediana**, que es
robusta: una fila extrema la mueve una posición.

Me gusta contar eso porque el fixture pagó su coste el primer día.

### «¿Y cómo pruebas que es idempotente?»

`etl/probar_idempotencia.py` corre el pipeline dos veces sobre la misma entrada y comprueba que
el MERGE de la segunda recibe **cero filas** —no que las actualizó con el mismo valor: que no las
tocó— y que las ocho tablas dan el mismo checksum.

Pero lo que hace que la prueba valga es el **control positivo**: después ensucia a propósito el
hash de un contrato y verifica que el filtro detecta exactamente ese. Un test que siempre da cero
no prueba nada; si el filtro estuviera mal escrito y no detectara ningún cambio, el caso normal
pasaría igual de limpio.

### «¿Por qué dbt y DuckDB, y no Spark o un warehouse?»

La ingesta se quedó en Python porque es paginación HTTP con reanudación: control de flujo, no una
transformación. De ahí hacia arriba todo es SQL con dbt, porque un esquema en estrella *es* SQL y
porque dbt trae de fábrica los tests, el linaje y la materialización incremental, que si no hay
que escribir a mano.

DuckDB porque no es un servidor, es una librería embebida: el repo se clona y se corre sin
levantar nada. Y la migración la **probé**: comparé la salida de dbt contra la del ETL anterior
emparejando por clave natural, porque las subrogadas cambiaron a propósito, y dio **cero
diferencias en las ocho tablas**.

## Las cifras, por si preguntan

| | |
|---|---|
| Contratos en el dataset | 6.102.286 |
| Columnas | 95 |
| Firmados en los últimos 3 años | 3.030.270 |
| Universo de obra e infraestructura | 66.875 |
| Contratos que cumplen los dos criterios de filtro | 12.618 |
| Valor contratado (sin el registro corrupto) | $88,27 billones COP |
| Valor contratado si no se detecta el error | $6.542 billones COP |
| % ejecutado sobre todo el universo | 13,4 % |
| % ejecutado acotado a contratos terminados | 46,8 % |
| Contratos terminados sin pago reportado | 5.234 de 13.885 |
| Tamaño del modelo en Parquet | ~12 MB |
| Tamaño del dataset completo en crudo | ~26 GB |
| Tests de calidad sobre el modelo | 67: 63 pasan, 4 avisan |
| Duración del pipeline completo | ~15 s |
| Filas que el MERGE toca en una segunda corrida | 0 |
| El registro corrupto, veces la mediana de su modalidad | 190.693.033× |
| El contrato legítimo más extremo, por la misma medida | 14.884× |

---

## Lo que no hay que decir

- **No exagerar el volumen.** El proyecto procesa 66.875 filas, no seis millones. Los seis
  millones son el dataset de origen, y hay que decirlo en esos términos.
- **No decir que se encontró corrupción.** El proyecto describe cómo se reporta el gasto
  público. Los problemas documentados son de diligenciamiento de la información, no denuncias.
  Un contrato con una cifra imposible es un error de digitación hasta que se demuestre otra cosa.
- **No vender Spark ni herramientas que no están.** Si alguien pregunta por qué no hay Spark, la
  respuesta de arriba es mejor que haberlo metido.
