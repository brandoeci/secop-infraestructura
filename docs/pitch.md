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
> dimensiones— en Parquet, que es lo que lee Power BI.
>
> Y el hallazgo que más me gusta no es de negocio, es de **calidad de datos**: al sumar el valor
> contratado me daba cuatro veces el PIB del país. Era **un solo registro mal digitado que valía
> el noventa y ocho por ciento del total**.

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

---

## Lo que no hay que decir

- **No exagerar el volumen.** El proyecto procesa 66.875 filas, no seis millones. Los seis
  millones son el dataset de origen, y hay que decirlo en esos términos.
- **No decir que se encontró corrupción.** El proyecto describe cómo se reporta el gasto
  público. Los problemas documentados son de diligenciamiento de la información, no denuncias.
  Un contrato con una cifra imposible es un error de digitación hasta que se demuestre otra cosa.
- **No vender Spark ni herramientas que no están.** Si alguien pregunta por qué no hay Spark, la
  respuesta de arriba es mejor que haberlo metido.
