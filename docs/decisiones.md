# Decisiones de modelado

Cada decisión con la medición que la sustenta. Las cifras vienen de
[`estructura.md`](estructura.md) y todas salieron de correr el código contra la API.

---

## D1 — Cómo se identifica un contrato de infraestructura

**Decidido el 2026-10-05: la unión de los dos criterios.**

```sql
fecha_de_firma >= '2023-10-05T00:00:00'
AND (
      tipo_de_contrato IN ('Obra', 'Interventoría', 'Consultoría',
                           'Concesión', 'Asociación Público Privada')
   OR codigo_de_categoria_principal LIKE 'V1.72%'
)
```

**Resultado verificado: 66.831 contratos** (contados contra la API el 2026-10-05).

### Por qué la unión y no uno de los dos

Se midieron los dos criterios por separado sobre la población completa antes de decidir:

| Conjunto | Contra la API<br>2026-10-05, mañana | En el universo descargado<br>2026-10-05, 19:17 |
|---|---|---|
| A — por `tipo_de_contrato` | 36.276 | 36.317 |
| B — por UNSPSC `V1.72%` | 43.163 | 43.176 |
| A ∩ B | 12.608 | 12.618 |
| A ∪ B | **66.831** | **66.875** |

**Las dos columnas son correctas, y la diferencia entre ellas es el dato interesante.** La
primera es el conteo que sustentó la decisión; la segunda, el recuento sobre las filas que
efectivamente se descargaron esa misma tarde. `jbjy-vk9h` **se actualiza a diario**: entre
una medición y otra entraron 44 contratos nuevos al universo.

De ahí una regla del repositorio: **ninguna cifra se escribe sin la fecha en que se midió**.
Contra un origen vivo, un número sin fecha no es verificable. Las cifras del `README.md` y de
`docs/pitch.md` son las de la columna derecha, porque describen el universo que el informe
realmente contiene.

**Los dos criterios casi no se solapan**: solo 12.618 contratos cumplen ambos, de 66.875. Es
decir, cada criterio por separado deja fuera entre 23.000 y 30.000 contratos que el otro sí
encuentra. Usar uno solo no es una simplificación, es perder un tercio del universo.

Las dos razones concretas:

1. **Hay obra contratada bajo otro tipo.** De los 30.555 contratos que B encuentra y A pierde,
   15.746 están clasificados como *Prestación de servicios* y 10.614 como *Otro*, pese a tener
   categoría UNSPSC de construcción.
2. **El UNSPSC no siempre se diligencia.** De los 25.203 contratos tipo `Obra`, **7.519 (30 %)
   traen la categoría en `UNSPECIFIED`**.

### Por qué no se filtra por texto del objeto

Se probó y se descartó como criterio principal: `objeto_del_contrato LIKE '%VIA%'` devuelve
90.679 filas, pero sin fronteras de palabra captura también **VIAJE, LLUVIA, PREVIA,
VIABILIDAD**. El texto libre sirve para afinar o para detectar atípicos, no para definir el
universo.

### Limitación asumida

La unión incluye contratos de servicios de mantenimiento de instalaciones que alguien podría no
llamar "obra". Se asume a propósito: el informe responde *en qué se gasta la plata de
infraestructura*, y el mantenimiento de infraestructura es gasto de infraestructura. Queda
documentado para poder defenderlo.

---

## D2 — Qué 20 columnas se conservan de las 95

**Decidido el 2026-10-05.**

### Hecho `contratos` — grano: un contrato

| Columna | Papel |
|---|---|
| `id_contrato` | clave del hecho |
| `valor_del_contrato` | medida |
| `valor_pagado` | medida |
| `valor_facturado` | medida |
| `valor_pendiente_de_pago` | medida |
| `fecha_de_firma` | clave a dim `fecha` |
| `fecha_de_inicio_del_contrato` | clave a dim `fecha` |
| `fecha_de_fin_del_contrato` | clave a dim `fecha` |
| `objeto_del_contrato` | atributo degenerado (detección de atípicos, drillthrough) |

### Dimensiones

| Dimensión | Columnas |
|---|---|
| `entidad` | `nit_entidad` (clave), `nombre_entidad`, `departamento`, `ciudad`, `orden` |
| `proveedor` | `documento_proveedor` (clave), `proveedor_adjudicado` |
| `tipo_contrato` | `tipo_de_contrato` |
| `estado` | `estado_contrato` |
| `categoria` | `codigo_de_categoria_principal` |
| `modalidad` | `modalidad_de_contratacion` |

### Notas de modelado

- **`duraci_n_del_contrato` se descarta aunque exista.** Viene como **texto**. La duración se
  calcula restando `fecha_de_fin` menos `fecha_de_inicio`, que ya son `calendar_date`. Un
  número derivado de fechas limpias es más confiable que un texto de la fuente.
- **`objeto_del_contrato` se queda en el hecho, no en una dimensión.** Es texto largo y casi
  único por contrato: una dimensión con una fila por hecho no es una dimensión. Va como
  atributo degenerado.
- **`estado_contrato` hay que normalizar al cargarlo.** La fuente trae `terminado`, `cedido` y
  `enviado Proveedor` sin capitalizar mientras el resto sí. Sin normalizar, la dimensión
  muestra valores que parecen distintos y no lo son.
- **`departamento` y `ciudad` van en `entidad`, no en una dimensión geográfica propia.** En este
  dataset describen a la entidad contratante, no el lugar de ejecución de la obra. Llamarla
  "geografía" sería afirmar algo que los datos no dicen. La dirección de ejecución existe en
  `direcci_n_de_ejecuci_n_del_contrato`, pero es texto libre sin normalizar: **2.475 valores
  distintos en 10.000 filas, con saltos de línea dentro del propio campo**. No sirve como
  dimensión sin un trabajo de geocodificación que está fuera del alcance.
- **`modalidad_de_contratacion` también trae inconsistencias de capitalización**: coexisten
  `Contratación directa` (76,0 %) y `Contratación Directa (con ofertas)` (1,3 %). Hay que
  normalizar esta dimensión igual que `estado`.

### Qué se descarta y por qué

| Grupo | Columnas | Razón |
|---|---|---|
| Datos personales | representante legal (6), ordenador del gasto (3), supervisor (3), ordenador de pago (3) | Nombres y documentos de personas naturales. Sin valor analítico y no corresponde publicarlos en un informe de portafolio. |
| Datos bancarios | `nombre_del_banco`, `tipo_de_cuenta`, `n_mero_de_cuenta` | Igual: dato sensible, cero uso analítico. |
| Columnas ambientales | 6 columnas de criterios y obligaciones ambientales | Entre 98,5 % y 99,9 % con el valor `No Definido`. Vacías en la práctica. |
| Fechas vacías | `fecha_inicio/fin_reversi_n`, `fecha_inicio/fin_obligaciones_posconsumo` | 100 % y 99,96 % nulas en la muestra. |
| Postconflicto | `espostconflicto`, `puntos_del_acuerdo`, `pilares_del_acuerdo` | 99,3 % en `No` / `No aplica`. |
| Desgloses de fuente de recursos | PGN, SGP, regalías, crédito, recursos propios | Entre 79 % y 99,7 % en 0. Quedan como candidatas si más adelante hace falta el origen del dinero. |

### Candidatas si se quiere ampliar a 24

`sector` (dim entidad), `es_pyme` (dim proveedor), `dias_adicionados` (medida), `urlproceso`
(drillthrough al proceso real en SECOP).

---

## D3 — Umbral de contratos atípicos

**Decidido el 2026-10-05 al validar la descarga.**

El atípico se mide contra el percentil 99 de **su propia `modalidad_de_contratacion`**, no
contra el del universo completo, porque la modalidad refleja un rango de cuantía definido por
ley. La regla salió de un caso real: un contrato de *mínima cuantía* por 6,45 cuatrillones de
pesos, 38 millones de veces el p99 de su modalidad. Ver [`calidad-datos.md`](calidad-datos.md).

---

## D4 — La definición de `% ejecutado`

**Decidido el 2026-10-05 al construir el modelo.** Se acota a contratos donde el pago ya es
exigible (`estado` en `Cerrado` o `Terminado`), y la cobertura del dato se publica como medida
propia.

Lo que decidió: medir las dos y comparar.

| Medida | Resultado |
|---|---|
| Sobre los 66.874 contratos confiables | **13,4 %** |
| Acotada a los 17.814 con `pago_exigible` | **46,8 %** |

El 13,4 % no describe la realidad: mete contratos aprobados y en ejecución que todavía no
tenían por qué haber pagado nada. El 46,8 % es la cifra defendible.

Y como el vacío de reporte es en sí mismo un resultado interesante, se añade una medida
`% sin ejecución reportada`: qué porcentaje de los contratos ya terminados reporta cero pagado.
Son 5.234 de 13.885 contratos `Terminado`. Eso es un hallazgo del informe, no un defecto que
haya que esconder.

El DAX de las dos medidas está en [`modelo.md`](modelo.md).

---

## D5 — Qué hacer con el registro corrupto

**Decidido el 2026-10-05: marcar, no borrar.**

`CO1.PCCNTR.5972834` se queda en el hecho con `valor_confiable = False`. Todas las medidas de
dinero filtran por esa bandera, así que no contamina ninguna suma, pero sigue visible en la
página de atípicos.

Borrarlo habría sido más simple y habría dado el mismo total. Se descartó porque una fila que
desaparece del modelo no deja rastro de que existió: el informe describe cómo se reporta el
gasto público, y un registro con 6,45 cuatrillones de pesos **es** parte de cómo se reporta.
Marcarlo también demuestra que se detectó y se diagnosticó, en lugar de hacerlo desaparecer.

La misma bandera se aplica a `fechas_coherentes` (200 filas) y `pagado_excede` (43).

---

## D6 — El cruce con la red vial de INVÍAS, y qué significa

**Decidida el 2026-11-05.** Construida como `dim_territorial_vial`.

### Lo primero: la nota anterior estaba equivocada

Decía que el dataset tiene `Territorial` y `Departamento`. **No tiene ninguna columna de
departamento**, y `territorial` no es un nombre sino **un número**: `territorial = 22`. Igual
`categoria`, `superficie`, `calzada` y `administrador`. Por eso el cruce llevaba un mes sin
resolverse: no se estaba mirando el dato real.

Los diccionarios sí existen, publicados en los metadatos del propio dataset:

```
https://www.datos.gov.co/api/views/ie7y-asdn.json  ->  columns[].description
territorial :: 1: "Antioquia" ... 25: "Valle del Cauca", 26: "Ocaña",
               27: "Planta Central", 28: "ANI", 29: "Por Definir", 0: "No Aplica"
```

Van en el seed `territoriales_invias`, no en un `CASE`: son datos de referencia, y además un
`CASE` de 30 ramas con `VALUES` no es portable a BigQuery.

### Por dónde une

Por el **nombre del departamento**: el de la entidad contratante contra el del territorial.
Medido el 2026-11-05, los 25 territoriales que son departamento cruzan, con **un único alias**:
INVÍAS escribe `Guajira` y SECOP `La Guajira`. Esa equivalencia está declarada como dato en el
seed, en la columna `departamento_secop`, y no como un `replace` escondido en el SQL.

### Qué es y qué no es

**No es "la vía de este contrato".** El origen no dice en qué vía se gastó cada peso, y no hay
forma de deducirlo. Es el territorial del departamento donde está **registrada la entidad**, que
no es lo mismo: una entidad nacional con sede en Bogotá contrata obra en todo el país.

Las cifras lo dicen solas:

| | contratos | valor |
|---|---|---|
| En departamentos con red vial nacional | 48.369 (71,9 %) | 54,3 % |
| Sin territorial | 18.930 (28,1 %) | 45,7 % |

El 45,7 % del dinero queda fuera porque se concentra en Bogotá. **Es una dimensión de contexto,
y hay que presentarla así.**

### Para qué sirve entonces

Para normalizar. *"Quién gasta más"* siempre responde los grandes; *"quién gasta más por
kilómetro de red que administra"* es otra pregunta, y cambia el ranking:

| | por gasto total | por gasto por kilómetro |
|---|---|---|
| 1.º | Antioquia | **Atlántico** — 290 km, 13.549 millones/km |
| 2.º | Valle del Cauca | Bolívar |
| 3.º | Bolívar | Antioquia |

Antioquia es primera en plata absoluta y tercera por kilómetro. Eso es lo que justifica la
dimensión.

### Dos centinelas, no uno

`-1 Sin territorial` recoge los contratos de departamentos sin red vial nacional, y tiene **cero
kilómetros a propósito**: si tuviera, el gasto por kilómetro de ese miembro sería un número
inventado. `-2 Territorial no informado` recoge los 9 segmentos de vía cuyo territorial llegó
nulo (243 km), que no tienen contratos pero tampoco pueden desaparecer de los totales de red.
Marcar y no borrar, igual que en D5.

### Por qué no hay `pct_pavimentado`

Porque el origen no lo soporta. De 715 segmentos, **515 traen `superficie = 'Por Definir'`**
—17.876 de los 22.635 km, el 79 %— y solo **3** dicen `'Sin Pavimentar'`. Un porcentaje
calculado sobre eso diría que Boyacá tiene el 1,3 % de su red pavimentada, y es falso: lo que
pasa es que no se sabe.

Se exponen `km_pavimentados`, `km_sin_pavimentar` y `km_superficie_sin_definir` por separado,
para que el hueco se vea en vez de disfrazarse de dato.

---

## D7 — El dinero es decimal exacto, no punto flotante

**Decidido el 2026-11-06.** Los cuatro importes del hecho —`valor_contratado`, `valor_pagado`,
`valor_facturado`, `valor_pendiente`— se castean a `DECIMAL(38,2)` en DuckDB y a `NUMERIC` en
BigQuery. El macro es `tipo_dinero()` en `transformaciones/macros/dialecto.sql`.

### Por qué

Un importe en pesos es una cantidad decimal con dos cifras, no una medida continua. En punto
flotante la suma **no es asociativa**: `(a+b)+c` no siempre es `a+(b+c)`. El orden en que el
motor acumula las filas lo decide el planificador y cambia entre corridas, así que el total no
era estable **ni dentro del mismo motor**: dos corridas seguidas del mismo DuckDB sobre los
mismos datos dieron `6.546.904.372.188.142` y `6.546.904.372.188.134`.

Una suma cuyo último dígito depende de cómo el motor reparta los hilos no se puede poner en un
informe.

### Cuánto costaba, medido

| | |
|---|---|
| Suma exacta de los 67.299 contratos | 6.546.904.372.188.138,10 |
| La misma suma en `FLOAT64` | 6.546.904.372.188.134 |
| Diferencia | **4,10 pesos** |

Y lo interesante es **de dónde salía esa diferencia**: de un solo dato. El registro corrupto de
la decisión D5 vale 6.453.840.000.000.000, y a esa magnitud la distancia entre dos `float64`
consecutivos es de **un peso entero**, así que los centavos de los otros 67.298 contratos no
caben. Entre los contratos confiables el total son 93.064.372.188.138,10 y en ese rango el
`FLOAT64` es exacto: su límite para enteros es 2^53, unos 9.007 billones.

O sea que el error no estaba repartido por el tipo de dato: lo causaba un dato. Pero el tipo era
lo que dejaba que un dato lo causara.

### La trampa de BigQuery

El supertipo de `NUMERIC` y `FLOAT64` en BigQuery es `FLOAT64`. Así que esto:

```sql
coalesce(safe_cast(valor_del_contrato as NUMERIC), 0.0)
```

devuelve `FLOAT64` y **deshace el cambio en silencio**: compila, corre y da un número creíble.
Hay que coalescer contra un entero —`0`—, cuyo supertipo con `NUMERIC` sí es `NUMERIC`. Es el
tipo de defecto que no falla, solo miente, igual que el `to_hex(md5())` de la migración.

### Lo que NO pasó a decimal, a propósito

`veces_p99_modalidad` y el umbral del p99 se quedan en punto flotante. Un percentil y un
cociente son referencias estadísticas, no cantidades de dinero: exigirles exactitud no
significa nada, y dividir decimales arrastra reglas de precisión distintas en cada motor.

### Lo que ganó el proyecto

`etl/comparar_motores.py` **borró su tolerancia**. Nació comparando los importes con una
diferencia relativa de `1e-12` porque la igualdad exacta no existía; ahora exige igualdad, en
`Decimal` de Python para no reintroducir el flotante por la puerta de atrás. Es una afirmación
bastante más fuerte sobre la portabilidad del modelo.

### Y el límite de Power BI, que casi se cuela

El Parquet que lee Power BI **sigue saliendo en `double`**, y eso es deliberado. El tipo
«Número decimal fijo» de Power BI es un `int64` escalado por 10.000, así que su techo son
`922.337.203.685.477,58`. El registro corrupto lo pasa **siete veces**. Si el Parquet llevara
decimales, Power Query los leería como decimal fijo y el refresco reventaría justo en esa fila.

Se midió antes de cambiar el tipo, no después de que fallara un refresco. La conversión está en
`etl/exportar.py` con el motivo al lado.

Perder exactitud en la exportación no cuesta nada medible: el informe filtra por
`valor_confiable` en todas sus medidas, y el universo confiable vive en el rango donde el
`FLOAT64` representa cada peso exactamente. La aritmética que tiene que ser exacta —los tests,
la bitácora, la comparación entre motores— ya ocurrió antes, en el almacén.

### Qué habría que revisar si algún día se elimina el registro corrupto

Si D5 cambiara y ese contrato dejara de llevar un importe, el máximo del universo pasaría a
1.370.285.018.012 y entraría de sobra en el decimal fijo de Power BI. Ahí sí valdría la pena
exportar decimales y declararlos como moneda en el modelo semántico, que daría aritmética exacta
también en DAX.

---

## D8 — El hecho refleja el presente, no el histórico

**Decidido el 2026-11-06.** Un contrato que desaparece del origen desaparece del modelo. Lo
implementa el `post_hook` de `hecho_contratos`, que llama a
`borrar_filas_retiradas('int_contratos_calidad', 'id_contrato')`.

Esto cierra la decisión que estaba abierta aquí abajo desde el incidente del 2026-11-03, cuando
el universo perdió 974 contratos y quedaron 448 claves apuntando a filas de dimensión que ya no
existían.

### Por qué esta y no conservar el histórico

Las dimensiones ya son `table`: se reconstruyen de cero en cada corrida y no acumulan versiones.
Que el hecho conserve filas que sus dimensiones ya no tienen es justamente lo que producía las
claves huérfanas. Hacer que el hecho también refleje el presente es la opción **coherente con el
modelo que ya existe**.

La alternativa —conservar la fila marcada como retirada— obligaba a SCD Type 2 en `dim_entidad` y
a que **todas** las medidas del informe filtraran por `vigente`. Era más trabajo para responder
una pregunta que el informe no hace: el informe responde *qué se está contratando*, no *qué
sabíamos en octubre*.

Consecuencia aceptada: **las cifras se mueven entre corridas.** Por eso toda cifra del README y
de este documento va fechada.

### El intento que borró la tabla entera

El primer intento fue la forma obvia: una estrategia incremental propia que añadía
`WHEN NOT MATCHED BY SOURCE THEN DELETE` dentro del MERGE. DuckDB 2.0.0 lo soporta y la sintaxis
era correcta.

Dejó `hecho_contratos` en **cero filas**.

El motivo es que el origen del MERGE **no es el universo**. El modelo filtra su propio origen con
`is_incremental()` para que solo lleguen las filas nuevas o cambiadas —de eso vive la
idempotencia—. Sobre el mismo bronze ese delta es 0 filas. Y `not matched by source` contra un
origen vacío significa "ninguna fila del destino coincide": borrar todo.

> `WHEN NOT MATCHED BY SOURCE` solo es correcto si el origen del MERGE es el estado completo del
> presente. Con carga por delta, el borrado tiene que ir en una sentencia aparte que compare
> contra el modelo de origen completo.

De ahí que el borrado viva en un `post_hook` y no en el MERGE.

### Lo más grave no fue el borrado

Fue que **los 74 tests pasaron en verde sobre la tabla vacía.** Todos. `not_null`, `unique` y
`relationships` se cumplen por vacuidad: sobre una tabla sin filas no hay nada que violar. El gate
—la pieza entera de la que depende que Power BI no lea datos malos— habría dejado publicar un
modelo sin un solo contrato.

Lo cierra el test nuevo `tests/hecho_completo.sql`, y su umbral no es inventado: es la invariante
real del modelo. `int_contratos_calidad` tiene una fila por contrato y el hecho sale de ahí con
una unión contra 30 filas de referencia, así que la correspondencia es 1 a 1. Vigila las dos
direcciones:

| | |
|---|---|
| `en_gold < en_silver` | se perdieron filas. Es el caso de la tabla vacía: 0 < 67.299 |
| `en_gold > en_silver` | quedaron filas retiradas sin borrar, o sea D8 no se cumplió |

Son **75 tests**, no 74.

### La guarda, que es la parte delicada

`aterrizar.py` **sobrescribe** bronze con lo que le den, y `descargar.py --desde` baja solo los
contratos firmados después de una fecha. Con bronze parcial, "borrar lo que no está en el origen"
se lleva el resto del universo.

Y hay una razón más de fondo: **una descarga incremental no puede saber qué retiró SECOP.** Solo
trae lo que existe. La ausencia de un contrato en un tramo no dice nada sobre si sigue publicado.
Detectar un retiro exige la descarga completa.

Por eso el borrado está detrás de la variable `origen_completo`, **que por defecto es `false`**:

- `pipeline.yml` en cron no pasa `inputs`, así que `desde` llega vacío, la descarga es completa y
  el paso siguiente recibe `--origen-completo`. D8 activo.
- Un despacho manual con `--desde` **no** lo recibe. D8 en pausa.
- `correr_pipeline.py` lo deduce solo cuando él mismo descargó: `--descargar` sin `--desde`.

La asimetría del valor por defecto es deliberada. Si se olvida la bandera en una corrida completa,
quedan filas retiradas de más y el gate lo grita. Si el valor por defecto fuera `true` y se
olvidara en una corrida parcial, el hecho se vaciaría. **Se elige el fallo que avisa sobre el
fallo que destruye.**

### Las dos salidas son seguras

Esto es lo que hace defendible el diseño. Si el origen pierde un contrato:

| Con permiso para borrar | Sin permiso |
|---|---|
| el hecho lo borra, el modelo queda consistente y se publica | el hecho lo conserva, la dimensión no, la clave queda huérfana y **la integridad referencial pone el gate en rojo** |
| repara | se niega a publicar |

En ningún camino se publica un modelo inconsistente. El segundo es el incidente del 2026-11-03, y
ahora se puede reproducir a voluntad en vez de descubrirlo un lunes.

### La prueba

`python etl/probar_borrado.py`, seis pasos:

1. `--full-refresh` → 67.299 filas.
2. Se quita un contrato de bronze, simulando que SECOP lo retiró.
3. Corrida **sin** declarar el origen completo → el contrato sigue ahí, y el gate falla por
   `relationships_hecho_contratos_proveedor_key`. La prueba afirma *cuál* test falló, no solo que
   algo falló.
4. Corrida **declarando** el origen completo → 67.298 filas, y la que falta es exactamente esa.
5. **Control negativo**: se inyecta en el hecho una fila que no está en el origen y
   `hecho_completo` tiene que fallar. Sin este paso el 4 no prueba nada: un test que no sabe
   fallar siempre está verde.
6. Se restaura bronze y se vuelve a 67.299.

`etl/probar_idempotencia.py` sigue pasando: el MERGE recibe 0 filas y las 9 tablas gold mantienen
el mismo checksum. El borrado no rompió la idempotencia porque sobre un origen completo y sin
cambios no hay nada que borrar.

### Lo que esta decisión cancela

El **SCD Type 2 en `dim_entidad`** sale del pendiente. Dependía de que el hecho conservara
histórico; no lo conserva. Si algún día el informe necesita responder "qué sabíamos entonces", la
pieza que hay que construir primero es el registro persistente de claves, y se revisa D8.
