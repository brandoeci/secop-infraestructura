# El modelo en estrella

Lo que `etl/transformar.py` escribe en `data/curated/` y lee Power BI en modo Import.
Cifras de la corrida del 2026-10-05 sobre 66.875 contratos.

```bash
pip install -r requirements.txt
python etl/descargar.py --universo obra
python etl/transformar.py
```

| Tabla | Filas | MB |
|---|---|---|
| `hecho_contratos` | 66.875 | 10,47 |
| `dim_proveedor` | 34.031 | 1,10 |
| `dim_fecha` | 13.879 | 0,21 |
| `dim_entidad` | 3.057 | 0,12 |
| `dim_categoria` | 1.545 | 0,02 |
| `dim_tipo_contrato` | 19 | 0,00 |
| `dim_modalidad` | 12 | 0,00 |
| `dim_estado` | 8 | 0,00 |

Modelo completo: ~12 MB. Por eso Power BI no se conecta a la API: lee esto.

El proyecto de Power BI está en `powerbi/` como **PBIP** (modelo semántico en TMDL, versionable
en git). Ver [`../powerbi/README.md`](../powerbi/README.md).

### Los tipos del Parquet no son los que pandas elige

`etl/transformar.py` fuerza un esquema Arrow explícito al escribir, en vez de dejar que pandas
decida. No es cosmético:

- pandas 3 escribe los textos como **`large_string`** (LargeUtf8), y el conector Parquet de
  Power Query **no lee ese tipo**: la carga falla. Se fuerza `string`.
- Los enteros estrechos (`int8`, `int16`) se amplían a `int32`. Son tipos innecesariamente
  exóticos para el conector y no ahorran nada a esta escala.
- Las fechas sin componente de hora se escriben como `date32`, que llega a Power BI como Fecha
  y no como Fecha y hora.

Si algún día falla la carga en Power BI, ese es el primer sitio donde mirar.

---

## Hecho `contratos`

**Grano: un contrato.** Verificado, no supuesto: 66.875 filas con 66.875
`id_contrato` distintos, cero duplicados.

| Columna | Tipo | Papel |
|---|---|---|
| `id_contrato` | texto | clave del hecho |
| `entidad_key`, `proveedor_key`, `tipo_contrato_key`, `estado_key`, `modalidad_key`, `categoria_key` | entero | claves a dimensiones |
| `fecha_firma_key`, `fecha_inicio_key`, `fecha_fin_key` | entero | claves a `dim_fecha` (yyyymmdd) |
| `valor_contratado`, `valor_pagado`, `valor_facturado`, `valor_pendiente` | decimal | medidas base |
| `duracion_dias` | entero | medida derivada |
| `objeto_del_contrato` | texto | atributo degenerado |
| `valor_confiable`, `fechas_coherentes`, `pago_exigible`, `pagado_excede` | booleano | banderas de calidad |
| `veces_p99_modalidad` | decimal | magnitud del atípico |

### Por qué tres claves de fecha y una sola `dim_fecha`

Las tres fechas apuntan a la misma tabla. En Power BI solo una relación puede
estar activa: **`fecha_firma_key` es la activa**, porque la pregunta del informe
es cuándo se comprometió el dinero. Las otras dos quedan inactivas y se activan
puntualmente con `USERELATIONSHIP` cuando una medida necesite el eje de inicio o
de fin. Tres tablas de fechas separadas darían tres ejes de tiempo que no se
pueden comparar entre sí.

### Por qué `duracion_dias` se calcula aquí y no se toma de la fuente

El dataset trae `duraci_n_del_contrato`, pero es **texto**. La duración se calcula
restando fechas, que ya vienen como fecha. Un número derivado de fechas limpias
es más confiable que un texto de la fuente.

Queda **nula en 2.619 contratos**: 2.583 sin fecha de inicio y 36 donde la resta
saldría negativa. Una duración negativa no es una duración corta, es un dato malo;
promediarla contaminaría la medida.

---

## Dimensiones y su grano

### `dim_entidad` — grano: la unidad que contrata

**3.057 unidades sobre 2.692 NIT.** El NIT no sirve solo como clave: el NIT
`899999034` es el SENA y aparece con **81 nombres distintos** (SENA Regional
Atlántico, Regional Caldas, Centro Agropecuario de Buga…). El NIT es la entidad
jurídica; el nombre es la unidad que efectivamente contrata.

El informe pregunta *quién contrata*, y esas regionales contratan por separado, así
que el grano es `(nit_entidad, nombre_entidad)`. Se conserva `nit_entidad` como
atributo para poder agregar a entidad jurídica cuando haga falta.

`departamento` y `ciudad` varían dentro de la unidad en 6 y 5 casos de 3.057. Se
resuelve con el valor más frecuente de la unidad: una dimensión no puede tener dos
filas para la misma unidad porque un contrato trae la ciudad mal diligenciada.

### `dim_proveedor` — grano: el proveedor, con clave condicional

**34.031 proveedores.** La clave depende de si el documento sirve:

- **Documento válido (93,9 %)** → la clave es el documento. 206 proveedores traen
  el nombre con varias grafías; se toma la más frecuente como nombre canónico en
  lugar de partirlos en varias filas.
- **Documento centinela (6,1 %, 4.084 contratos)** → la fuente trae `No Definido`,
  `0`, `000000000`. Son casi todos consorcios y uniones temporales sin NIT propio
  en el campo: **3.889 proveedores distintos**. Usar el documento como clave los
  colapsaría todos en una fila. Para ellos la clave se construye sobre el nombre
  normalizado y la fila queda marcada con `tiene_documento = False`.

Partir por `(documento, nombre)` habría sido más simple, pero duplicaría al
proveedor que aparece escrito de dos maneras, que es justo lo que una dimensión
debe evitar.

### `dim_fecha` — tabla de fechas común

**13.879 filas, de 2018-01-01 a 2055-12-31.** Arranca en un 1 de enero y termina
en un 31 de diciembre: si no, `SAMEPERIODLASTYEAR` y la demás inteligencia de
tiempo da resultados parciales en los años de los extremos.

**Hay que marcarla como tabla de fechas en Power BI** (Modelado → Marcar como tabla
de fechas, columna `fecha`). Sin eso, DAX genera jerarquías automáticas por cada
columna de fecha y la inteligencia de tiempo se comporta de forma impredecible.

Llega a 2055 a propósito: 94 contratos terminan después de 2035 y son concesiones
de obra a 20 y 30 años, no errores. Lo que sí era error se trató aparte, abajo.

### `dim_tipo_contrato`, `dim_estado`, `dim_modalidad`, `dim_categoria`

Dimensiones de un solo atributo. `dim_categoria` son los 1.545 códigos UNSPSC
presentes. `dim_estado` y `dim_modalidad` salen ya normalizados: la fuente entrega
`terminado` y `cedido` en minúscula mientras el resto va capitalizado.

La normalización **solo toca la primera letra, no fusiona valores**:
`Contratación directa` y `Contratación Directa (con ofertas)` son modalidades
legalmente distintas y siguen separadas.

---

## Banderas de calidad: marcar en vez de borrar

Una fila que desaparece del modelo no deja rastro de que existió, y el vacío de
reporte es parte de lo que el informe describe.

| Bandera | Filas | Qué marca |
|---|---|---|
| `valor_confiable = False` | 1 | El registro de 6,45 cuatrillones diagnosticado en [`calidad-datos.md`](calidad-datos.md). **Toda medida de dinero debe filtrar por esta bandera.** |
| `fechas_coherentes = False` | 200 | El contrato termina antes de firmarse. Incluye uno con fecha de fin en el año **0206**. |
| `pagado_excede = True` | 43 | Pagado mayor que contratado; dejaría `% ejecutado` sobre 100 %. |
| `pago_exigible = True` | 17.814 | El contrato ya terminó, así que el pago debería estar reportado. |

### El año 0206 y por qué importó

Un contrato (`CO1.PCCNTR.8725754`, Puerto Gaitán, firmado el 2025-12-23) trae la
fecha de fin en el **año 0206**. Esa sola fila estiraba `dim_fecha` a **675.699
filas**, unos 1.850 años, dejándola inservible y engordando el modelo.

La corrección no fue adivinar la fecha ni borrar el contrato: las fechas fuera de
la ventana plausible (2015–2060) no entran a `dim_fecha`, la clave del hecho queda
en nulo y la fila queda marcada. `dim_fecha` bajó a 13.879 filas.

---

## Medidas DAX

```dax
-- Base. Todas filtran el registro no confiable.
Valor contratado =
CALCULATE ( SUM ( hecho_contratos[valor_contratado] ),
            hecho_contratos[valor_confiable] = TRUE () )

Valor pagado =
CALCULATE ( SUM ( hecho_contratos[valor_pagado] ),
            hecho_contratos[valor_confiable] = TRUE () )
```

### `% ejecutado`: la decisión que estaba pendiente

Medida sobre todo el universo frente a medida acotada a contratos ya terminados:

| Medida | Resultado |
|---|---|
| Sobre los 66.874 contratos confiables | **13,4 %** |
| Acotada a los 17.814 con `pago_exigible` | **46,8 %** |

El 13,4 % no describe la realidad: mete contratos aprobados y en ejecución que
todavía no tenían por qué haber pagado nada. El 46,8 % es la cifra defendible.

```dax
% ejecutado =
VAR Contratado =
    CALCULATE ( SUM ( hecho_contratos[valor_contratado] ),
                hecho_contratos[valor_confiable] = TRUE (),
                hecho_contratos[pago_exigible]   = TRUE () )
VAR Pagado =
    CALCULATE ( SUM ( hecho_contratos[valor_pagado] ),
                hecho_contratos[valor_confiable] = TRUE (),
                hecho_contratos[pago_exigible]   = TRUE () )
RETURN
    DIVIDE ( Pagado, Contratado )
```

Y la cobertura del dato como medida propia, porque es un hallazgo en sí misma:

```dax
-- Qué porcentaje del gasto ya terminado no tiene ejecución reportada.
% sin ejecución reportada =
VAR Terminados =
    CALCULATE ( COUNTROWS ( hecho_contratos ),
                hecho_contratos[pago_exigible] = TRUE () )
VAR SinReporte =
    CALCULATE ( COUNTROWS ( hecho_contratos ),
                hecho_contratos[pago_exigible] = TRUE (),
                hecho_contratos[valor_pagado]  = 0 )
RETURN
    DIVIDE ( SinReporte, Terminados )
```

### Variación anual

```dax
Valor contratado año anterior =
CALCULATE ( [Valor contratado],
            SAMEPERIODLASTYEAR ( dim_fecha[fecha] ) )

Variación anual % =
DIVIDE ( [Valor contratado] - [Valor contratado año anterior],
         [Valor contratado año anterior] )
```

Ojo al interpretarla: el universo arranca el 2023-10-05, así que 2023 es un año
parcial y su comparación contra 2022 no existe. El informe debe empezar el eje en
2024 o advertirlo.

### Ranking de entidades

```dax
Ranking entidad =
IF ( ISINSCOPE ( dim_entidad[nombre_entidad] ),
     RANKX ( ALLSELECTED ( dim_entidad[nombre_entidad] ),
             [Valor contratado], , DESC, DENSE ) )
```

### Contratos atípicos (decisión D3)

El atípico se mide contra el p99 de **su propia modalidad de contratación**, no del
universo, porque la modalidad refleja un rango de cuantía definido por ley: un
atípico en mínima cuantía no es lo mismo que uno en licitación pública.
`veces_p99_modalidad` ya viene calculado en el hecho.

| Umbral | Contratos |
|---|---|
| > 1× el p99 de su modalidad | 663 |
| > 2× | 203 |
| > 10× | 27 |
| > 100× | 6 |

```dax
Contratos atípicos =
CALCULATE ( COUNTROWS ( hecho_contratos ),
            hecho_contratos[veces_p99_modalidad] > 10 )
```

El registro corrupto marca **38.201.335×** el p99 de su modalidad. Por eso la
página de atípicos lo muestra en lugar de esconderlo: es la prueba de que la regla
funciona.

---

## RLS por departamento

Caso de uso: un supervisor regional solo ve los contratos de su región.

El departamento vive en `dim_entidad`, así que el rol se define ahí y el filtro se
propaga al hecho por la relación uno a muchos.

```dax
-- Rol "Supervisor regional", tabla dim_entidad
[departamento] = LOOKUPVALUE (
    mapa_usuarios[departamento],
    mapa_usuarios[correo], USERPRINCIPALNAME ()
)
```

Requiere una tabla puente `mapa_usuarios` (correo, departamento) cargada aparte y
**oculta del panel de campos**. Es dinámico: un rol por departamento sería 34 roles
que hay que mantener a mano.

Importante al probar: el RLS filtra `dim_entidad` por el departamento **de la
entidad contratante**, no por el lugar donde se ejecuta la obra. En este dataset el
departamento describe a la entidad; la dirección de ejecución existe pero es texto
libre sin normalizar (2.475 valores distintos en 10.000 filas) y no sirve como
dimensión sin geocodificar.

---

## Lo que falta

- Cruzar con la red vial de INVÍAS (`ie7y-asdn`, 715 filas por 18 columnas) para la
  dimensión `territorial_vial`. Todavía no está construida.
- El `.pbix`: cargar las ocho tablas, marcar `dim_fecha` como tabla de fechas,
  crear las medidas y el rol de RLS.
