# Contratación de infraestructura en Colombia

Proyecto de datos de punta a punta sobre el gasto público en obra e infraestructura, con datos
abiertos de **SECOP II**, la plataforma de contratación estatal de Colombia.

ETL en Python sobre un dataset de **6.102.286 contratos** y modelo en estrella listo para
Power BI.

---

## La pregunta que responde

**¿En qué se gasta la plata de infraestructura en Colombia?** Quién contrata, cuánto se ejecuta
de verdad frente a lo contratado, qué departamentos concentran el dinero y qué contratos se
salen del patrón.

---

## Hallazgos

Todas las cifras salen de correr el código de este repositorio contra la API de datos.gov.co
el **2026-10-05**. Ninguna está estimada.

### La obra pública es menos del 1 % de los contratos

De los 3.030.270 contratos firmados en los últimos tres años, el **86,84 % es prestación de
servicios** y solo el **0,83 % está clasificado como obra**. Eso obligó a buscar el gasto de
infraestructura más allá del tipo de contrato.

### Los dos criterios para identificar infraestructura casi no se solapan

| Criterio | Contratos |
|---|---|
| Por tipo de contrato (obra, interventoría, consultoría, concesión, APP) | 36.317 |
| Por categoría UNSPSC de construcción (`V1.72`) | 43.176 |
| **Cumplen los dos** | **12.618** |
| **Universo final (unión)** | **66.875** |

Filtrar solo por tipo pierde 30.558 contratos con categoría de construcción, la mayoría
registrados como «prestación de servicios». Filtrar solo por UNSPSC pierde 23.699, entre ellos
los 7.519 contratos de obra cuya categoría viene como `UNSPECIFIED`. El universo es la unión de
ambos.

### Un solo registro valía el 98,6 % del total

Sumar el valor contratado daba **$6.542 billones COP**, unas cuatro veces el PIB anual de
Colombia para tres años de obra. La causa era **un contrato** de
**$6.453.840.000.000.000** (6,45 cuatrillones de pesos).

Es un error de digitación, y tres campos del propio registro lo delatan: está clasificado como
**mínima cuantía** (modalidad cuya mediana es $33,8 millones y su percentil 99 son $169
millones), duró **menos de tres meses**, y supera el percentil 99,99 del universo unas 10
millones de veces.

| | Con el registro | Sin el registro |
|---|---|---|
| Valor contratado | $6.542,11 B | **$88,27 B** |
| Departamento con más valor | `No Definido` (98,7 %) | Bogotá D.C. (41,8 %) |

De ahí sale la regla de detección de atípicos del modelo: comparar cada contrato contra el
percentil 99 de **su propia modalidad de contratación**, no del universo, porque la modalidad
refleja un rango de cuantía definido por ley.

### La ejecución reportada pasa de 13,4 % a 46,8 % según cómo se mida

El **61,8 % del universo reporta cero pagado**. En contratos aprobados o en ejecución eso es
plausible; en contratos ya terminados no lo es.

| Medida | Resultado |
|---|---|
| `% ejecutado` sobre todo el universo | 13,4 % |
| Acotado a los 17.814 contratos ya terminados | **46,8 %** |

El 13,4 % no describe la realidad: mezcla contratos que todavía no tenían por qué haber pagado
nada. Aun acotando, **5.234 de 13.885 contratos terminados reportan cero pagado**. Esa brecha
se publica como medida propia del informe en lugar de esconderla: cuánto del gasto de
infraestructura no tiene ejecución reportada es un resultado en sí mismo.

### Una fecha en el año 0206 rompía la tabla de fechas

Un contrato trae la fecha de fin en el **año 0206** (casi seguro 2026). Esa sola fila estiraba
la tabla de fechas del modelo a **675.699 filas**, unos 1.850 años. Con la ventana de fechas
plausibles quedó en 13.879.

La ventana llega hasta 2060 a propósito: **94 contratos terminan después de 2035** y son
concesiones de obra a 20 y 30 años, no errores.

---

## Datos

| Fuente | Dataset | Tamaño |
|---|---|---|
| SECOP II – Contratos Electrónicos | [`jbjy-vk9h`](https://www.datos.gov.co/resource/jbjy-vk9h.json) | 6.102.286 filas × 95 columnas, actualización diaria |
| Red Vial – INVÍAS | [`ie7y-asdn`](https://www.datos.gov.co/resource/ie7y-asdn.json) | 715 filas × 18 columnas, estático |

Acceso sin cuenta por la API de Socrata. El app token es opcional y solo sube el límite de
peticiones; si lo tienes, expórtalo como `SOCRATA_APP_TOKEN`.

---

## Arquitectura

```
API Socrata  ->  descarga paginada  ->  NDJSON en data/raw/
                                              |
                                        transformación
                                              |
                                   esquema en estrella en Parquet
                                        data/curated/
                                              |
                                     Power BI (modo Import)
```

Power BI no se conecta a los millones de filas crudas: lee el Parquet ya filtrado, que son
**~12 MB**.

### Por qué no hay Spark

El universo filtrado son 66.875 filas. A ese volumen un clúster no aporta nada y pandas sobra,
así que el ETL es pandas. Lo que sí justificaría Spark son los **~26 GB** del dataset completo
en crudo (extrapolado de 43 MB por 10.000 filas), y ese paso todavía no hace falta. Una
herramienta puesta sin que el volumen la exija es ruido.

---

## Cómo correrlo

```bash
pip install -r requirements.txt

# 1. Descarga el universo de obra: 66.875 contratos, 20 columnas
python etl/descargar.py --universo obra

# 2. Construye el esquema en estrella en data/curated/
python etl/transformar.py
```

La descarga es **reanudable**: si se corta, el mismo comando continúa donde quedó. Reanuda
contando las líneas ya escritas en vez de confiar en un archivo de estado, y recorta una última
línea truncada si el proceso murió a mitad de escritura.

Otros comandos útiles:

```bash
# Cuántas filas tiene el dataset ahora mismo
python etl/descargar.py --contar

# Perfil de una muestra: tipos, nulos y valores de relleno por columna
python etl/explorar.py --muestra data/raw/obra.ndjson

# Valores distintos de una columna
python etl/explorar.py --columna tipo_de_contrato
```

> El dataset se actualiza a diario, así que el total crece con cada corrida. El límite inferior
> de fecha está fijo en el código y no es «hoy menos tres años», para que las cifras sean
> comparables entre corridas.

---

## El modelo

Ocho tablas, grano del hecho: **un contrato** (verificado, 66.875 filas con 66.875
`id_contrato` distintos).

| Tabla | Filas |
|---|---|
| `hecho_contratos` | 66.875 |
| `dim_proveedor` | 34.031 |
| `dim_fecha` | 13.879 |
| `dim_entidad` | 3.057 |
| `dim_categoria` | 1.545 |
| `dim_tipo_contrato` | 19 |
| `dim_modalidad` | 12 |
| `dim_estado` | 8 |

Dos granos que los datos obligaron a decidir:

- **`dim_entidad` va a nivel de unidad contratante, no de NIT.** El NIT del SENA aparece con 81
  nombres distintos (Regional Atlántico, Regional Caldas…) y esas regionales contratan por
  separado. Son 3.057 unidades sobre 2.692 NIT.
- **`dim_proveedor` usa clave condicional.** El 6,1 % de los contratos trae el documento del
  proveedor como centinela (`No Definido`, ceros): son consorcios y uniones temporales sin NIT
  propio en el campo, **3.889 proveedores distintos** que usar ese campo como clave habría
  colapsado en una sola fila.

El ETL valida integridad referencial y **falla antes de escribir** si el modelo no es cargable.

### Calidad: marcar en vez de borrar

El hecho lleva banderas de calidad en lugar de filas eliminadas, porque una fila que desaparece
no deja rastro de que existió y el vacío de reporte es parte de lo que el informe describe.

| Bandera | Filas |
|---|---|
| `valor_confiable = False` (el registro de 6,45 cuatrillones) | 1 |
| `fechas_coherentes = False` (termina antes de firmarse) | 200 |
| `pagado_excede = True` (pagado mayor que contratado) | 43 |
| `pago_exigible = True` (el contrato ya terminó) | 17.814 |

El detalle está en [`docs/modelo.md`](docs/modelo.md), con el DAX de las medidas y el RLS
dinámico por departamento.

---

## Documentación

| Documento | Contenido |
|---|---|
| [`docs/estructura.md`](docs/estructura.md) | Las 95 columnas con tipo, nulos y valores de relleno; los tipos y estados con conteos de la población completa |
| [`docs/decisiones.md`](docs/decisiones.md) | Las cinco decisiones de modelado con la medición que sustenta cada una |
| [`docs/calidad-datos.md`](docs/calidad-datos.md) | Los problemas de los datos de origen y cómo se trataron |
| [`docs/modelo.md`](docs/modelo.md) | El esquema en estrella, las medidas DAX y el RLS |

---

## Estructura

```
etl/            descarga, exploración y transformación
data/raw/       NDJSON crudo          (no versionado)
data/curated/   Parquet para Power BI (no versionado)
powerbi/        el .pbix
docs/           decisiones y notas técnicas
```

Los datos no se versionan. El repositorio se clona y se reproduce corriendo el ETL.

---

## Estado

Hecho: la descarga, la exploración, las decisiones de modelado y el ETL al esquema en estrella.

Pendiente:

- El **`.pbix`**: cargar las ocho tablas, marcar `dim_fecha` como tabla de fechas, crear las
  medidas y el rol de RLS.
- El **cruce con la red vial de INVÍAS** para la dimensión `territorial_vial`. Falta definir
  por dónde se une: el departamento de la entidad contratante no es necesariamente el
  departamento donde está la vía.

---

## Nota

Este proyecto describe cómo se reporta el gasto público; **no acusa a nadie**. Cuando una cifra
parece escandalosa, lo primero es revisar si es un error en los datos, y en el caso más grande
de este dataset lo era. Los problemas documentados son de diligenciamiento de la información,
no denuncias.

Datos abiertos de Colombia Compra Eficiente e INVÍAS, publicados en
[datos.gov.co](https://www.datos.gov.co).
