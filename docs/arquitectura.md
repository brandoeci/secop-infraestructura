# Arquitectura del pipeline

Cómo está construido el proyecto y, sobre todo, **por qué así**. Las cifras de
este documento se midieron el **2026-10-29** corriendo el código.

---

## El recorrido del dato

```
         API Socrata  jbjy-vk9h  (6,1 M contratos, 95 columnas, diaria)
                     │
                     │  etl/descargar.py      paginación reanudable, $order=:id
                     ▼
BRONZE   data/bronze/contratos.parquet        66.875 × 22 · 12 MB
                     │                        crudo fiel al origen, todo texto
                     │  dbt + DuckDB
                     ▼
SILVER   stg_contratos                        tipado y limpieza
         int_contratos_calidad                banderas de calidad, p99 por modalidad
                     │
                     ▼
GOLD     dim_entidad · dim_proveedor · dim_fecha · dim_tipo_contrato
         dim_estado · dim_modalidad · dim_categoria
         hecho_contratos                      66.875 filas, MERGE incremental
                     │
                     │  67 tests  ◄── el gate: si algo rompe, aquí se detiene
                     │
                     │  etl/exportar.py       solo si el gate pasó
                     ▼
         data/curated/*.parquet  ──────►  Power BI (Import)  ──────►  informe
```

Un solo comando lo corre todo:

```bash
python etl/correr_pipeline.py
```

## Qué garantiza cada capa

| Capa | Garantía | Si se rompe |
|---|---|---|
| **bronze** | Es lo que dijo el origen, sin interpretar | Hay que volver a descargar |
| **silver** | Tipos declarados y texto normalizado | Se arregla y se vuelve a correr `dbt build` |
| **gold** | Esquema en estrella cargable, claves estables | El gate lo detiene antes de publicar |
| **curated** | Último modelo que pasó todos los controles | Power BI nunca ve un modelo malo |

Esa frontera entre bronze y el resto no es decoración. Si la limpieza viviera en
la ingesta, un cambio de criterio obligaría a volver a descargar 67 MB. Con
bronze intacto se vuelve a correr `dbt build` y tarda tres segundos. Y cuando
una cifra no cuadra, bronze es la única capa contra la que se puede comprobar
qué decía el origen de verdad.

---

## Las cuatro decisiones que definen el pipeline

### 1. Claves subrogadas deterministas, no posicionales

**El defecto que había.** La primera versión del ETL asignaba las claves así:

```python
g.insert(0, "entidad_key", range(1, len(g) + 1))   # sobre un conjunto ORDENADO
```

Parece inofensivo y no lo es. Si el origen trae una entidad nueva que ordena en
la mitad, **se renumeran todas las que van después**: el `entidad_key` de ayer
apunta a otra entidad hoy. Con claves así no hay carga incremental posible, no
porque falte el `MERGE`, sino porque no hay nada estable contra lo que hacerlo.

**Lo que hay ahora.** La clave sale de un hash de la clave natural:

```sql
(hash(coalesce(nit_entidad,'∅') || '|' || coalesce(nombre_entidad,'∅'))
    & 9223372036854775807)::BIGINT
```

Dos propiedades que importan:

- **Determinista y sin estado.** Se clona el repo, se corre, y salen las mismas
  claves. No hay que versionar ningún registro de asignaciones.
- **Estable ante filas nuevas.** Una entidad nueva no mueve la clave de ninguna
  otra.

La máscara a 63 bits no es cosmética: `hash()` de DuckDB devuelve `UBIGINT` y
desborda el `int64` que el modelo semántico declara para las columnas `*_key`.

**Lo que se descartó.** El enfoque clásico de bodega —un registro persistente
que asigna 1, 2, 3… y nunca los reutiliza— es más correcto en una bodega real y
es **imprescindible para SCD Type 2**. Aquí se descartó porque viviría en
`data/`, que no se versiona, y se perdería al clonar: el repo dejaría de ser
reproducible. El día que haga falta historia de dimensiones, ese registro es el
primer paso.

### 2. pandas en la ingesta, SQL de silver a gold

La ingesta se queda en Python porque es **paginación HTTP con reanudación**:
control de flujo, reintentos con backoff, truncado de una última línea
incompleta. Eso no es una transformación y en SQL quedaría peor.

De bronze hacia arriba todo es SQL con dbt, porque un esquema en estrella *es*
SQL —agrupaciones, uniones, ventanas— y porque dbt trae de fábrica tres cosas
que habría que escribir a mano: los tests, el linaje y la materialización
incremental.

**La migración se probó, no se asumió.** `etl/comparar_salidas.py` comparó la
salida de dbt contra la del ETL anterior emparejando **por clave natural** (las
subrogadas cambiaron a propósito, compararlas no diría nada): **0 diferencias en
las 8 tablas**, 21 de 21 columnas del hecho idénticas.

### 3. El gate bloquea porque la exportación va después

```
dbt build      construye y corre 67 tests. Si algo rompe, termina en error.
exportar.py    solo corre si lo anterior salió bien.
```

Como la exportación es un paso **posterior**, un modelo que no pasa los tests
nunca llega a `data/curated/`. Power BI se queda leyendo el último modelo bueno
en vez de refrescar sobre datos malos. Un gate que avisa pero deja pasar no es
un gate; este deja el dato viejo, que es el comportamiento seguro.

Dos severidades:

- **`error`** rompe la corrida. Se reserva para lo que hace el modelo
  incargable o directamente falso.
- **`warn`** deja pasar y queda registrado. Es para los defectos del origen ya
  diagnosticados en [calidad-datos.md](calidad-datos.md): no son sorpresas, son
  el estado conocido del dato público, y el informe los describe en vez de
  ocultarlos.

Hoy: **63 pasan, 4 avisan, 0 rompen**.

### 4. No hay Spark, y es a propósito

El universo filtrado son **66.875 filas** y pesa 12 MB. A esa escala un clúster
no aporta nada: el pipeline completo corre en **15 segundos** en un portátil, y
`dbt build` solo tarda 3. Montar Spark aquí sería más lento, no más rápido.

Lo que sí lo justificaría son los **~26 GB** del dataset completo en crudo, si
algún día hay que barrer los 6,1 millones de contratos sin filtrar. Ese paso
todavía no hace falta.

Poder explicar por qué **no** se usó una herramienta vale más que tenerla de
adorno.

---

## Las pruebas: lo que se afirma, se demuestra

Tres propiedades que sería fácil dar por buenas sin comprobarlas. Las tres
tienen un script que las ejecuta.

### `etl/comparar_salidas.py` — la migración no cambió ningún dato

Empareja por clave natural y compara columna a columna. Debe dar **0
diferencias**.

### `etl/probar_idempotencia.py` — correrlo dos veces no cambia nada

```
2. Segunda corrida sobre el mismo bronze    el MERGE recibe 0 filas
3. Control positivo: se ensucia un hash     el filtro detecta exactamente 1
4. Tercera corrida                          repara esa fila y vuelve al inicio
```

El paso 3 es el que hace que la prueba valga. **Un test que siempre da cero no
prueba nada**: si el filtro estuviera mal escrito y no detectara ningún cambio,
el paso 2 pasaría igual de limpio.

El conteo de filas que recibe el `MERGE` se saca del SQL que dbt compiló y
ejecutó (`target/compiled/`), no de una reimplementación del filtro, porque eso
sería probar una copia en lugar del original. (`dbt-duckdb` no reporta
`rows_affected`.)

### `etl/probar_gate.py` — el control de calidad bloquea de verdad

Inyecta en bronze un contrato con el mismo perfil del error real y comprueba
que `dbt build` falla con código distinto de 0, que lo caza el test escrito
para eso, y sobre todo que **`data/curated/` queda byte a byte idéntico**.

El registro malo sí entra al gold de DuckDB —es ahí donde el test puede verlo—
pero no llega a los Parquet del informe.

### El test que más vale, y los dos defectos que tuvo

`valor_fuera_de_escala` es la regla que **habría atrapado sola** el error que se
encontró a mano: un contrato de mínima cuantía registrado por 6,45 cuatrillones
de pesos, que explicaba el 98,6 % del valor del universo entero.

Sus dos primeras versiones estaban mal, y las dos las descubrió el fixture de
280 filas del CI:

1. **Medir la concentración como fracción del valor total depende del tamaño del
   dataset.** El contrato más grande pesa 1,55 % sobre el universo completo y
   12,54 % sobre 280 filas. El test saltaba por el tamaño de la muestra, no por
   un error. Un control que depende de cuántos datos le toquen no es un control.

2. **Medir contra el p99 de la modalidad tampoco funciona.** Parecía la
   referencia natural, siendo la misma de la decisión D3, pero en una modalidad
   con pocos contratos **el registro corrupto entra en el cálculo de su propio
   p99 y lo infla**: la razón vuelve a ser cerca de 1 y el test no dispara. El
   error inyectado pasaba sin que nadie lo cazara.

La versión que funciona mide contra la **mediana** de la modalidad, que es
robusta: una sola fila extrema, por grande que sea, la mueve una posición.

| | Veces la mediana de su modalidad |
|---|---|
| Contrato legítimo más extremo | 14.884× |
| Contratos por encima de 100.000× | **0** |
| El registro corrupto | **190.693.033×** |

El umbral queda en **100.000×**: casi siete veces de holgura sobre el peor caso
real y mil novecientas por debajo del error que tiene que cazar. Entre lo
legítimo y lo imposible hay cuatro órdenes de magnitud, y el umbral cae justo en
ese hueco.

Verificado a las dos escalas: el gate bloquea con 66.875 filas y con 280.

---

## Orquestación

| Flujo | Cuándo | Qué hace |
|---|---|---|
| `.github/workflows/ci.yml` | cada push y PR | Pipeline completo contra el fixture de 280 filas, sin red: ruff, los 67 tests, exportación, y las pruebas de idempotencia y del gate. Menos de un minuto. |
| `.github/workflows/pipeline.yml` | cron lunes 06:00 UTC, o a mano | Descarga real de la API (incremental con `--desde`), pipeline completo, y publica el modelo y la bitácora como artefactos. |

Si el gate falla, el workflow falla y GitHub avisa por correo. Eso es lo que
cierra el agujero de origen: antes esto era `python etl/transformar.py` a mano,
un fallo era silencioso y no quedaba constancia de ninguna corrida.

### La bitácora

`etl/registrar_corrida.py` acumula una fila por corrida en
`data/curated/auditoria_corridas.parquet`: `run_id`, cuándo, con qué commit,
duración, resultado (PASS / WARNING / FAIL), modelos y tests por estado, y filas
en cada capa.

No instrumenta nada a mano: dbt ya escribe `target/run_results.json` y
`target/manifest.json` en cada corrida, y esto solo los lee y los acumula. Una
observabilidad que hay que mantener aparte se deja de mantener.

Corre **pase o falle**, porque una corrida que falló es justo la que más
interesa tener registrada.

---

## El fixture, y por qué es una excepción consciente

La regla del repo es que no se versionan datos. `tests/fixtures/contratos_muestra.ndjson`
la rompe a propósito: **280 filas, 261 KB**, fuera de `data/`.

El motivo es que el CI pueda correr el pipeline y sus pruebas **sin red**, y que
cualquiera que clone el repo pueda hacer `dbt build` sin descargar 67 MB. Son
datos públicos de SECOP, así que no hay nada sensible que exponer.

Está muestreado **de forma estratificada por modalidad** (25 por modalidad, 12
modalidades): al azar, las modalidades raras desaparecen y el p99 por modalidad
deja de tener sentido.

Y valió la pena de inmediato: fue el fixture el que rompió el test de calidad
más importante y destapó sus dos defectos.

---

## Lo que falta

- **El cruce con la red vial de INVÍAS** para `territorial_vial`. Sigue sin
  resolverse por dónde une, porque el departamento de la entidad no es el
  departamento de la vía. Es trabajo de modelado, no de ingeniería.
- **SCD Type 2** en `dim_entidad`. Requiere el registro persistente de claves
  que la decisión 1 descartó a propósito.
- **Alertas más allá del correo de GitHub.** Power Automate tiene conector
  nativo para refrescar el dataset de Power BI, que cerraría el ciclo hasta el
  informe.
