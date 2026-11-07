# Migración a GCP: el mismo dbt corriendo en DuckDB y en BigQuery

## Contexto

El pipeline medallion está terminado y probado, corriendo en DuckDB local con 75 tests,
idempotencia y un gate que bloquea la publicación. El usuario quiere **aprender nube** y
hacer una migración a GCP, y tuvo el buen criterio de parar una tanda de trabajo que
apareció en `gcp/` sin versionar para hacerlo por fases.

El objetivo no es «subir los datos a la nube». Es que **el mismo proyecto dbt corra en los
dos motores**, de modo que cambiar de DuckDB a BigQuery sea una bandera:

```bash
dbt build                   # DuckDB local: 3 s, gratis
dbt build --target cloud    # BigQuery: los MISMOS modelos y los MISMOS tests
```

Eso es portabilidad real y no una copia del resultado. En entrevista se cuenta en una
frase, y obliga a entender de verdad en qué se diferencian los dos motores.

### Decisiones ya tomadas

| | |
|---|---|
| Enfoque | dbt con dos targets, no cargar el resultado ya transformado |
| Cloud Run | Después, cuando BigQuery funcione |
| Cuenta GCP | creada el 2026-11-04: `golden-capsule-446717-s8`, **sin facturación**, en *sandbox* |
| Claves subrogadas | **Idénticas en los dos motores** |

### Lo que ya existe y se aprovecha

`gcp/` tiene trabajo de otra sesión, sin versionar: `01-cargar.sh` (GCS + BigQuery),
`02-consultas.sql` (5 consultas), `validar_consultas.py` (las ensaya con DuckDB antes de
gastar en BigQuery — **las 5 pasan hoy**) y `servicio/` (API FastAPI para Cloud Run).

Se reutiliza: las consultas, el validador y el razonamiento de `01-cargar.sh`. Se rehace:
el script cargará **bronze** y no `curated`, porque con este enfoque la transformación
ocurre *en* BigQuery. `servicio/` queda intacto y sin versionar hasta su fase.

### Restricciones

1. **Power BI no se rompe.** Sigue leyendo `data/curated/*.parquet` producidos por el
   target local. Las cifras publicadas (66.875 contratos, $88,27 bill., 46,8 %) no cambian.
2. **Las tres pruebas existentes siguen pasando**: `comparar_salidas.py`,
   `probar_idempotencia.py` y `probar_gate.py`.
3. **Las claves cambian de valor** (de `hash()` a MD5). Nada visible cambia en el informe,
   pero el usuario tendrá que **refrescar Power BI una vez más**. El PDF sigue válido.

---

## Fase 1 — SQL portable, verificado en local (sin cuenta GCP)

Es el grueso del aprendizaje y se comprueba gratis. **No depende de que exista la cuenta.**

### Las claves, idénticas en los dos motores

Hoy: `(hash(...) & 9223372036854775807)::BIGINT`, que es nativo de DuckDB y no existe en
BigQuery. Pasa a MD5, que sí está en los dos:

```sql
-- DuckDB      cast('0x' || substr(md5(X), 1, 15) as bigint)
-- BigQuery    cast(concat('0x', substr(to_hex(md5(X)), 1, 15)) as int64)
```

Verificado en DuckDB el 2026-10-30: devuelve `468445596631364263`. Son **60 bits**, siempre
positivo, dentro de `int64`, y con 34.031 proveedores el riesgo de colisión es ~5·10⁻¹⁰.

`clave_subrogada()` y `clave_fecha()` en `transformaciones/macros/claves.sql` pasan a
emitir una u otra según `target.type`.

### Las 16 construcciones a portar

El inventario está hecho. Casi todas son sustitución directa:

| DuckDB | BigQuery |
|---|---|
| `try_cast` · `x::TIPO` | `safe_cast` · `cast(x as TIPO)` |
| `strftime(d,'%Y%m%d')` · `make_date(y,m,d)` | `format_date('%Y%m%d',d)` · `date(y,m,d)` |
| `year(d)` · `month` · `quarter` · `day` | `extract(YEAR from d)` … |
| `quantile_cont(x,p) over` · `median(x) over` | `percentile_cont(x,p) over` |
| `bool_and` · `* exclude (c)` | `logical_and` · `* except (c)` |
| `generate_series(a,b,interval 1 day)` | `generate_date_array(a,b,interval 1 day)` |
| `regexp_full_match(x,p)` | `regexp_contains(x, '^p$')` |
| `strip_accents(x)` | `regexp_replace(normalize(x,NFD), r'\pM','')` |
| `list_value(...)[month(d)]` | `[...][offset(extract(MONTH from d)-1)]` |

**La trampa:** `date_diff('day', a, b)` en DuckDB es `DATE_DIFF(b, a, DAY)` en BigQuery —
**los argumentos van al revés**. Un error aquí no rompe nada, solo cambia el signo de
`duracion_dias`, que es justo el tipo de fallo que la Fase 4 existe para atrapar.

Dónde: `macros/limpieza.sql`, `macros/claves.sql`,
`models/staging/stg_contratos.sql`, `models/intermedio/int_contratos_calidad.sql`,
`models/marts/dim_fecha.sql` y `tests/valor_fuera_de_escala.sql`.

### El criterio: eliminar la diferencia antes que abstraerla

Donde haya SQL portable que funcione igual en los dos motores, se usa ese y **no** se
escribe un macro con dos ramas. Solo donde no hay equivalente se ramifica con
`{% if target.type == 'bigquery' %}`, con un comentario que explique por qué difieren.

El caso que mejor lo ilustra es `histogram()` + `map_keys` + `unnest` (el macro `moda_de`
en `macros/claves.sql`), que no tiene equivalente en BigQuery. Se reemplaza por un CTE con
`row_number() over (order by veces desc, valor asc)`, que **funciona en los dos** y además
es más legible que la versión con mapas. Portarlo mejora el código local, no lo empeora.

Lo usan `dim_entidad` (departamento, ciudad, orden) y `dim_proveedor` (proveedor).

### Cómo se verifica la Fase 1, sin tocar la nube

```bash
python etl/correr_pipeline.py --full-refresh
python etl/comparar_salidas.py --curated data/curated_referencia_pandas   # 0 diferencias
python etl/probar_idempotencia.py                                         # idempotente
python etl/probar_gate.py                                                 # el gate bloquea
```

Las tres tienen que seguir pasando. Si el SQL portado cambia un solo dato, salta.

---

## Fase 2 — La cuenta y bronze en la nube

El usuario crea la cuenta; esta fase le da los comandos exactos.

- Proyecto GCP, SDK instalado, `gcloud auth login`, `gcloud config set project`.
- **`gcp/01-bronze.sh`**, reescrito a partir de `01-cargar.sh`: habilita APIs, crea el
  bucket, sube **`data/bronze/contratos.parquet`** y lo carga en una tabla nativa
  `<proyecto>.secop_bronze.contratos`.
- El cambio de fondo frente al script original: antes subía `data/curated/` (el resultado
  ya transformado); ahora sube bronze, porque la transformación la hará BigQuery.

**Coste:** 12 MB contra 10 GB gratis de almacenamiento y 1 TB/mes de consultas. A esta
escala es gratis de forma permanente, no solo durante la prueba. La prueba gratuita sí
pide tarjeta.

---

## Fase 3 — `dbt build --target cloud`

- `transformaciones/profiles.yml`: segundo output `cloud` con `type: bigquery`,
  `method: oauth` (usa las credenciales de `gcloud`, sin archivo de clave que se pueda
  filtrar), `project` por `env_var`, `dataset: secop`.
- `models/fuentes.yml`: la fuente `bronze` resuelve a `read_parquet(...)` en DuckDB y a
  `secop_bronze.contratos` en BigQuery, según `target.type`.
- `dbt_project.yml`: esquemas por capa en los dos motores.
- `hecho_contratos` sigue `incremental` con `merge`: BigQuery lo soporta nativamente, así
  que la idempotencia se mantiene.
- **Primero `dbt compile --target cloud`**, que no cuesta nada y caza los errores de
  dialecto antes de ejecutar una sola consulta.

> A verificar aquí: que BigQuery acepte `cast('0x...' as int64)`. La documentación dice que
> sí para literales hexadecimales, pero no se puede probar sin cuenta. Si fallara, el plan
> B es construir el entero desde dos mitades de 8 dígitos hex con aritmética, que es
> portable pero más feo.

---

## Fase 4 — Probar que los dos motores dan lo mismo

Esta es la fase que convierte la migración en un hecho verificado.

**`etl/comparar_motores.py`** (nuevo, calcado de `comparar_salidas.py`): lee las 9 tablas
gold de DuckDB y de BigQuery y las compara fila a fila. Como las claves ahora son
idénticas, **se comparan también las claves**, no solo los atributos: es una igualdad más
fuerte que la que se usó para la migración a dbt.

Criterio: **0 diferencias en las 9 tablas**. Y `dbt build --target cloud` debe reportar los
mismos tests que DuckDB, con 4 warn y 0 error.

---

## Fase 5 — CI y documentación

- **`.github/workflows/nube.yml`**: `dbt build --target cloud` en cron y a mano.
  Autenticación con **Workload Identity Federation**, no con una clave de servicio en un
  secreto: WIF no deja credenciales de larga vida en GitHub y es gratis. Es más trabajo de
  configurar y por eso va al final.
- `docs/arquitectura.md`: sección nueva con los dos motores, la tabla de equivalencias de
  dialecto y por qué se eligió portar el SQL en vez de copiar el resultado.
- `README.md` y `docs/pitch.md`: la frase de los dos targets, y la pregunta de entrevista
  «¿qué cambia entre DuckDB y BigQuery?» con la trampa de `date_diff` como ejemplo.

---

## Ejecutado el 2026-11-04: las fases 2, 3 y 4, en sandbox

Se hizo sin activar la facturación, y eso condiciona el diseño. Lo que el
*sandbox* de BigQuery permite y lo que no, **comprobado, no leído**:

| | |
|---|---|
| `SELECT` y `CREATE OR REPLACE TABLE ... AS SELECT` | sí |
| Los modelos y los tests completos, el conteo de ese día | sí |
| `MERGE`, `UPDATE`, `DELETE` | **no**: *"DML queries are not allowed in the free tier"* |
| Bucket de Cloud Storage | no, necesita facturación |
| Permanencia de las tablas | caducan a los 60 días |

Dos consecuencias para el plan original:

1. **La Fase 2 no usa bucket.** El Parquet se carga directo desde el disco con
   `bq load --source_format=PARQUET bronze.contratos data/bronze/contratos.parquet`.
   Un paso menos que el `01-bronze.sh` previsto, y una dependencia menos.
2. **En BigQuery hay que correr con `--full-refresh`**, porque el `MERGE` de
   `hecho_contratos` es DML y está bloqueado. Un *full refresh* materializa la
   tabla con `CREATE OR REPLACE`, que es DDL y sí pasa. La carga incremental
   sigue viva en DuckDB, con su prueba de idempotencia.

### Dos huecos de portabilidad que la Fase 1 no había visto

La Fase 1 se verificó **compilando**, no ejecutando. El SQL compilaba en los dos
lados; los problemas aparecieron al mandárselo a BigQuery de verdad, los dos en
`regexp_replace`:

- **El flag `'g'`.** DuckDB reemplaza solo la primera coincidencia salvo que se
  pase `'g'` como cuarto argumento. BigQuery siempre es global y acepta tres:
  el cuarto da error de aridad.
- **Las secuencias de escape.** BigQuery rechaza `'\s'` en una cadena normal
  (*"Illegal escape sequence"*) y exige cadena cruda `r'\s'`. DuckDB no entiende
  el prefijo `r`.

Resueltos con `regex_reemplazar_global()` en `macros/dialecto.sql`, junto a
`quitar_tildes()`, que ya hacía lo mismo para los diacríticos.

### Las claves coincidían; los importes no, hasta que cambió el tipo

`etl/comparar_motores.py` compara las 9 tablas gold, las 8 claves subrogadas del
hecho y los 4 importes. Resultado del 2026-11-04, cuando el dinero todavía era
`FLOAT64` y había 8 tablas y 7 claves:

- **Las 8 tablas, con el mismo número de filas.**
- **Las 7 sumas de claves subrogadas, idénticas hasta el último dígito** sobre
  67.299 filas. Eso es lo que la Fase 1 perseguía: si las claves coinciden, los
  *join* coinciden y el modelo es el mismo modelo.
- **Los importes difieren en el dígito 16** (diferencia relativa de 1e-15 a
  4e-15).

Esa última diferencia **no es entre motores**. Dos corridas seguidas de DuckDB
sobre los mismos datos dieron `6.546.904.372.188.142` y
`6.546.904.372.188.134`. La suma de flotantes no es asociativa y el reparto
entre hilos cambia de corrida en corrida, así que el total no es estable ni
dentro del mismo motor.

**Conclusión de modelado, aplicada el 2026-11-06:** los importes pasaron a
`DECIMAL(38,2)` en DuckDB y `NUMERIC` en BigQuery, que son exactos. Ver el macro
`tipo_dinero()` en `transformaciones/macros/dialecto.sql` y la decisión D7.

La medición que lo justifica: la suma exacta de los 67.299 contratos es
`6.546.904.372.188.138,10` y la de `FLOAT64` daba `...134`. Faltaban **4,10
pesos**, y faltaban por un solo dato: el registro corrupto de la decisión D5
lleva el acumulado a 6,45 cuatrillones, un rango donde la distancia entre dos
`float64` consecutivos es de un peso entero, así que los centavos de los otros
67.298 contratos no caben. Entre los confiables el total es de 93 billones y ahí
el `FLOAT64` es exacto: el límite son 2^53, unos 9.007 billones.

Con el tipo exacto, `comparar_motores.py` **borró la tolerancia** y ahora exige
igualdad, que es una afirmación bastante más fuerte.

Lo que no cambió: el Parquet que lee Power BI sigue saliendo en `double`, y es
deliberado. El tipo «Número decimal fijo» de Power BI es un `int64` escalado por
10.000, así que su techo son `922.337.203.685.477,58` y el registro corrupto lo
pasa siete veces. Si el Parquet llevara decimales, Power Query los leería como
decimal fijo y el refresco reventaría en esa fila. La aritmética que tiene que
ser exacta ocurre antes, en el almacén.

---

## Verificación

| Fase | Cómo se comprueba | Necesita GCP |
|---|---|---|
| 1 | Las tres pruebas existentes siguen pasando y `comparar_salidas.py` da 0 diferencias | no |
| 2 | `bq query 'select count(*) from bronze.contratos'` → **67.299** (2026-11-04) | sí |
| 3 | `dbt compile --target cloud` sin errores, luego `dbt build --target cloud` → 63 pass, 4 warn, 0 error | sí |
| 4 | `python etl/comparar_motores.py` → **8 tablas y 7 claves idénticas**; importes dentro de tolerancia | sí |
| 5 | El workflow en verde; prueba negativa: romper un test deja la corrida en rojo | sí |

Y al cerrar: **refrescar Power BI una vez** (las claves cambian de valor aunque nada
visible cambie) y confirmar que las cifras siguen siendo 66.875 / $88,27 bill. / 46,8 %.

## Lo que queda explícitamente fuera

- **Cloud Run y la API** (`gcp/servicio/`). Decidido: después de que BigQuery funcione.
  El código se queda sin versionar hasta entonces.
- **Power BI contra BigQuery** en vez de contra los Parquet locales. Es posible y sería el
  cierre natural, pero añade conector y autenticación, y hoy el informe funciona.
- **Spark**, igual que antes: 66.875 filas no lo exigen.
