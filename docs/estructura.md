# Estructura real de los datos de SECOP II

Todas las cifras de este documento salieron de correr el código del repo contra la API de
Socrata el **2026-10-05**. Ninguna está estimada ni copiada del catálogo.

Cómo reproducirlo:

```bash
python etl/descargar.py --filas 10000 --salida data/raw/muestra_10k.ndjson
python etl/explorar.py
python etl/explorar.py --columna tipo_de_contrato
python etl/explorar.py --columna estado_contrato
```

---

## 1. Tamaño real del dataset

El catálogo dice "unos 6,1 millones". Confirmado con un `count(1)` contra la API:

| Medición | Valor |
|---|---|
| Filas totales | **6.102.286** |
| Columnas | **95** (64 texto, 19 número, 11 fecha, 1 url) |
| Rango de `Fecha de Firma` | 2015-06-11 a 2026-10-02 |
| Filas con firma en los últimos 3 años (desde 2023-10-05) | **3.030.270** |

El catálogo tenía razón. La muestra de 10.000 filas pesa **43 MB** en NDJSON; a ese ritmo las
6,1 millones de filas son del orden de **26 GB** de JSON crudo. Ahí es donde Spark empieza a
justificarse solo, y no antes.

### Por qué una fila no muestra 95 columnas

Socrata **omite las claves nulas en cada fila**. La primera fila descargada trae 87 campos, no
95. Por eso el esquema no se deduce de los datos: se lee de la API de metadatos
(`/api/views/jbjy-vk9h.json`), que es lo que hace `etl/explorar.py`.

---

## 2. ¿La muestra es representativa?

La paginación va ordenada por `:id`, que **no es un orden aleatorio**, así que había que
comprobarlo antes de usar la muestra para decidir nada. Contraste de la muestra contra la
población completa de los últimos 3 años (conteos del servidor, no de la muestra):

| `tipo_de_contrato` | En la muestra (10k) | En la población (3,03 M) |
|---|---|---|
| Prestación de servicios | 85,4 % | 86,84 % |
| Obra | 0,9 % | 0,83 % |
| Suministros | 2,8 % | 2,15 % |

Las proporciones coinciden, y la muestra abarca 2016–2026. **Sirve para explorar la
estructura.** Aun así, todas las cifras que deciden el filtro de este documento se sacaron con
conteos del servidor sobre la población completa, no de la muestra.

---

## 3. Las 95 columnas: tipo y nulos

El `% nulo` cuenta clave ausente, `null` y cadena vacía, sobre las 10.000 filas de la muestra.

> **Trampa importante:** casi todas las columnas marcan **0 % nulo**, y eso es engañoso. El
> dataset no usa nulos: usa textos de relleno como `No Definido`, `No` o el número `0`. La
> última columna de la tabla señala cuándo un valor de relleno es mayoritario. Una columna con
> 0 % de nulos y 99 % de `No Definido` está vacía en la práctica.

El resultado es tajante: **las únicas 11 columnas con algún nulo son exactamente las 11
columnas de tipo fecha**. Las otras 84 marcan 0 % nulo sin excepción, porque rellenan con texto
en lugar de dejar el campo vacío.

| Columna (todas `calendar_date`) | % nulo | Nulos de 10.000 |
|---|---|---|
| `fecha_inicio_reversi_n` | 100,0 % | 10.000 |
| `fecha_fin_reversi_n` | 100,0 % | 10.000 |
| `fecha_inicio_obligaciones_posconsumo` | 99,96 % | 9.996 |
| `fecha_fin_obligaciones_posconsumo` | 99,96 % | 9.996 |
| `fecha_de_notificaci_n_de_prorrogaci_n` | 90,47 % | 9.047 |
| `fecha_inicio_liquidacion` | 89,34 % | 8.934 |
| `fecha_fin_liquidacion` | 89,34 % | 8.934 |
| `ultima_actualizacion` | 42,29 % | 4.229 |
| `fecha_de_inicio_del_contrato` | 7,93 % | 793 |
| `fecha_de_firma` | 7,04 % | 704 |
| `fecha_de_fin_del_contrato` | 0,89 % | 89 |

Las dos de `obligaciones_posconsumo` se imprimen como "100,0 %" por redondeo pero tienen 4
filas con dato. Por eso `etl/explorar.py` muestra el conteo crudo al lado del porcentaje.

El **7 % de nulos en `fecha_de_firma`** importa: son contratos en `Borrador` y estados previos,
que todavía no se han firmado. Cualquier filtro por fecha de firma los excluye, y eso está bien,
pero hay que saberlo.

La tabla completa de las 95 columnas está en [`_tabla_columnas.md`](_tabla_columnas.md).

---

## 4. `Tipo de Contrato`: 17 valores en la muestra, 23 en la población

Población completa, últimos 3 años (3.030.270 filas):

| Tipo | Filas | % |
|---|---|---|
| Prestación de servicios | 2.631.415 | 86,84 % |
| Decreto 092 de 2017 | 114.966 | 3,79 % |
| Otro | 101.003 | 3,33 % |
| Suministros | 65.214 | 2,15 % |
| Compraventa | 45.814 | 1,51 % |
| **Obra** | **25.203** | **0,83 %** |
| Arrendamiento de inmuebles | 20.945 | 0,69 % |
| Seguros | 5.901 | 0,19 % |
| **Interventoría** | **5.621** | **0,19 %** |
| Comodato | 5.418 | 0,18 % |
| **Consultoría** | **5.265** | **0,17 %** |
| Arrendamiento de muebles | 1.109 | 0,04 % |
| Servicios financieros | 665 | 0,02 % |
| Operaciones de Crédito Público | 351 | 0,01 % |
| No Especificado | 345 | 0,01 % |
| Acuerdo Marco de Precios | 338 | 0,01 % |
| Venta muebles | 238 | 0,01 % |
| **Asociación Público Privada** | **105** | 0,00 % |
| Negocio fiduciario | 103 | 0,00 % |
| **Concesión** | **82** | 0,00 % |
| No Definido | 77 | 0,00 % |
| Comisión | 59 | 0,00 % |
| Venta inmuebles | 33 | 0,00 % |

En negrita los tipos relacionados con infraestructura. **La contratación estatal colombiana es
abrumadoramente prestación de servicios**: la obra pública es menos del 1 % de los contratos
(no necesariamente del dinero).

---

## 5. `Estado Contrato`: 11 valores, con mayúsculas inconsistentes

Muestra de 10.000 filas:

| Estado | Filas | % |
|---|---|---|
| En ejecución | 2.991 | 29,9 % |
| Cerrado | 2.846 | 28,5 % |
| Modificado | 1.761 | 17,6 % |
| `terminado` | 1.295 | 12,9 % |
| Borrador | 414 | 4,1 % |
| Aprobado | 342 | 3,4 % |
| Cancelado | 189 | 1,9 % |
| `enviado Proveedor` | 63 | 0,6 % |
| `cedido` | 53 | 0,5 % |
| En aprobación | 39 | 0,4 % |
| Suspendido | 7 | 0,1 % |

**`terminado`, `cedido` y `enviado Proveedor` vienen sin capitalizar** mientras el resto sí lo
está. Es inconsistencia de la fuente y hay que normalizarla en el ETL, o la dimensión `estado`
va a tener valores duplicados visualmente.

`Modificado` (17,6 %) no es un estado terminal: es un contrato vigente que ya tuvo adiciones o
prórrogas. Conviene no leerlo como "cerrado".

---

## 6. Las tres maneras de aislar "obra e infraestructura"

Esta es la decisión que define el proyecto, así que se midió en lugar de suponerse. Las tres
sobre la población completa de los últimos 3 años.

### A. Por `tipo_de_contrato`

| Filtro | Filas |
|---|---|
| `tipo_de_contrato = 'Obra'` | 25.203 |
| `Obra` + `Interventoría` + `Consultoría` + `Concesión` + `APP` | 36.276 |

### B. Por `codigo_de_categoria_principal` (UNSPSC)

El dataset trae el código UNSPSC de la categoría. La familia **`V1.72`** es construcción y
mantenimiento de instalaciones.

| Filtro | Filas |
|---|---|
| `codigo_de_categoria_principal` empieza por `V1.72` | 43.163 |

Límite conocido: de los 25.203 contratos tipo `Obra`, **7.519 (30 %) tienen la categoría en
`UNSPECIFIED`**. El UNSPSC no está siempre diligenciado.

### C. Por texto en `objeto_del_contrato`

| Filtro | Filas |
|---|---|
| `objeto` contiene `VIA` | 90.679 |
| `objeto` contiene `CONSTRUCC` | 51.638 |
| `objeto` contiene `PAVIMENT` | 2.207 |

Límite conocido: `%VIA%` captura también **VIAJE, LLUVIA, PREVIA, VIABILIDAD**. Sin fronteras de
palabra, el texto libre mete falsos positivos.

### El dato que decide: A y B casi no se solapan

| Conjunto | Filas |
|---|---|
| A (por tipo) | 36.276 |
| B (por UNSPSC `V1.72`) | 43.163 |
| **A ∩ B** | **12.608** |
| **A ∪ B** | **66.831** |
| En B pero no en A (los que el filtro por tipo pierde) | 30.555 |
| En A pero no en B (los que el filtro por UNSPSC pierde) | 23.668 |

Los 30.555 que B encuentra y A pierde están clasificados así por tipo:

| `tipo_de_contrato` | Filas |
|---|---|
| Prestación de servicios | 15.746 |
| Otro | 10.614 |
| Decreto 092 de 2017 | 2.027 |
| Suministros | 1.352 |
| Compraventa | 628 |

**Conclusión:** ninguno de los dos filtros por sí solo captura la obra pública. Cada uno deja
fuera entre 20.000 y 30.000 contratos que el otro sí ve. Hay mucha obra contratada bajo el tipo
"Prestación de servicios" y mucho contrato tipo "Obra" sin categoría UNSPSC.

---

## 7. Problema que afecta la medida principal del informe: `valor_pagado`

El informe pensaba medir `% ejecutado = valor pagado / valor contratado`. Dentro del universo
de obra (los 66.831 de A ∪ B), **`valor_pagado` viene en 0 en el 61,9 % de los contratos**:

| `estado_contrato` | Filas | Con `valor_pagado = 0` | % |
|---|---|---|---|
| Modificado | 22.388 | 14.973 | 66,9 % |
| En ejecución | 22.203 | 16.313 | 73,5 % |
| terminado | 13.865 | 5.224 | **37,7 %** |
| Cerrado | 3.923 | 761 | **19,4 %** |
| Aprobado | 2.639 | 2.639 | 100,0 % |
| Suspendido | 1.726 | 1.355 | 78,5 % |
| cedido | 80 | 66 | 82,5 % |
| Cancelado | 7 | 7 | 100,0 % |
| **Total** | **66.831** | **41.338** | **61,9 %** |

En `Aprobado` y `En ejecución` un 0 es plausible: todavía no se ha pagado. Pero **un contrato
`terminado` con 0 pagado no es creíble**, y son 5.224 casos. Es un vacío de reporte de la
entidad, no un contrato gratis.

Consecuencia para el modelo: un `% ejecutado` calculado sobre todos los contratos va a dar un
número artificialmente bajo que no describe la realidad. Hay que acotar la medida a estados
donde el pago ya debería estar reportado (`Cerrado`, `terminado`) y dejar documentado el vacío.
El dataset trae además `valor_facturado`, `valor_pendiente_de_pago` y `valor_amortizado`, que
conviene contrastar antes de fijar la definición.

---

## 8. Red Vial de INVÍAS

Verificado contra la API el mismo día:

| Medición | Valor |
|---|---|
| Filas | **715** (coincide con el catálogo) |
| Columnas | **18**, no 20 |

El CLAUDE.md dice "715 filas por 20 columnas". Las filas coinciden; las columnas son 18 según
`/api/views/ie7y-asdn.json`. Conviene corregirlo en el CLAUDE.md.
