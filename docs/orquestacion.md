# Orquestación con Airflow

Por qué el pipeline pasó de un script con `if` a un grafo de tareas, y qué
decisión hay detrás de cada pieza.

Airflow **no reimplementa el pipeline: lo llama.** Ni una línea de `etl/` ni de
`transformaciones/` cambió. `python etl/correr_pipeline.py` sigue funcionando
igual. Un orquestador que se mete dentro de la lógica se vuelve imposible de
abandonar.

---

## Qué aporta sobre el cron que ya había

`.github/workflows/pipeline.yml` corre un solo comando y ese comando lleva los
cinco pasos dentro, en Python. Funciona. Esto es lo que no da:

| | Con el cron | Con Airflow |
|---|---|---|
| Falla el paso 3 | se repiten los pasos 1 y 2 — se vuelven a bajar 67.000 contratos para nada | se reintenta solo la tarea que falló, las anteriores siguen en verde |
| «¿Qué pasó?» | leer un log de 400 líneas | se mira el grafo y se ve el cuadro rojo |
| Reintentos | del workflow entero o de nada | una política por tarea, con un motivo |
| Historia | el log de Actions caduca | el estado de cada tarea de cada corrida, en Postgres |

Y la que más vale en una entrevista:

### El gate deja de ser un `if` y pasa a ser la forma del grafo

En `correr_pipeline.py` el control de calidad es control de flujo:

```python
codigo_gate = dbt(...)
python("registrar_corrida.py")
if codigo_gate != 0:
    sys.exit(codigo_gate)      # y exportar.py nunca corre
python("exportar.py")
```

En el DAG es una declaración de dependencias:

```python
descargar >> aterrizar >> dbt_build >> exportar   # exportar exige éxito
dbt_build >> registrar                            # registrar corre igual
```

La misma garantía, pero **declarada en vez de codificada**, y Airflow la hace
cumplir. No hay forma de que `exportar` corra si `dbt_build` falló, ni de
olvidarse de `registrar`.

Las dos reglas que lo consiguen:

- **`exportar` no declara `trigger_rule`**, así que usa la de por defecto,
  `all_success`: no arranca si algo de arriba no terminó en verde. *Eso es
  literalmente el gate*, sin condición que escribir ni recordar.
- **`registrar_corrida` declara `trigger_rule="all_done"`**: arranca cuando las
  tareas de arriba *terminaron*, sin importar cómo. Hace falta porque una
  corrida que falló es justo la que más interesa tener registrada. Con la regla
  por defecto, la bitácora solo tendría las corridas buenas, que es la mitad
  inútil de la historia.

---

## La política de reintentos: dónde sí y dónde no

Es la decisión de diseño más interesante del DAG, y la respuesta no es «ponle 3
a todo».

| Tarea | Reintentos | Por qué |
|---|---|---|
| `descargar` | **4, con backoff exponencial** | Es la única tarea cuyo fallo es *transitorio*. La API pública se cae, da 503 o corta la conexión; el segundo intento puede salir bien sin que nadie arregle nada. Backoff porque reintentar cada 10 segundos contra una API saturada la satura más: espera 2, 4, 8 y 16 minutos. Y la descarga es reanudable, así que el reintento continúa donde quedó. |
| `aterrizar` | **0** | Si falla es porque el crudo está truncado o el esquema cambió. Reintentar da el mismo error y retrasa el diagnóstico. |
| `dbt_build` | **0** | **La más importante.** Un test de calidad que falló expresa un hecho sobre los datos, no un accidente: volver a correrlo da exactamente el mismo resultado. Un reintento aquí solo sirve para tardar cuatro veces más en enterarse, y para dar la falsa impresión de que el fallo es intermitente. |
| `registrar` / `exportar` | **0** | Deterministas: leen el almacén y escriben archivos. |

El criterio general: **se reintenta lo que falla por causas ajenas al código, y
no se reintenta lo que falla por lo que dicen los datos.**

---

## El compose: cinco servicios, no ocho

El `docker-compose.yaml` oficial levanta ocho servicios porque usa
`CeleryExecutor`, que reparte tareas entre varias máquinas y por eso necesita
Redis como cola y un worker aparte. Aquí todo corre en un portátil, así que se
usa **`LocalExecutor`**: el scheduler lanza las tareas él mismo, en subprocesos.

Lo que se cayó con ese cambio, y por qué:

| Servicio quitado | Para qué servía |
|---|---|
| `redis` | la cola entre scheduler y workers. Sin Celery no hay cola. |
| `airflow-worker` | saca tareas de la cola. Con `LocalExecutor` lo hace el scheduler. |
| `flower` | panel de monitoreo de Celery. |
| `airflow-cli` | atajo para comandos sueltos; se hace con `docker compose run`. |
| `triggerer` | solo hace falta para operadores *diferibles*, que liberan su slot mientras esperan algo externo. Este DAG no usa ninguno. |

Lo que queda:

| Servicio | Qué hace |
|---|---|
| `postgres` | la base de metadatos: estado de cada corrida y cada tarea |
| `airflow-init` | migra el esquema y crea el usuario. Corre una vez y termina |
| `airflow-apiserver` | la interfaz web y la API REST (puerto 8080) |
| `airflow-scheduler` | decide qué toca ejecutar y, con `LocalExecutor`, lo ejecuta |
| `airflow-dag-processor` | parsea los archivos de `dags/`. En Airflow 3 es un proceso separado: un DAG con un error de sintaxis ya no puede tumbar al planificador |

---

## Las dos trampas de Airflow 3

Las dos cuestan una tarde si no se sabe que están ahí.

### 1. El secreto JWT tiene que ser fijo y compartido

En Airflow 3 las tareas ya **no hablan con la base de datos**: hablan con la
*Execution API* del apiserver y se autentican con un token JWT. Si el secreto no
se declara, cada servicio se genera uno aleatorio en memoria, el del scheduler no
coincide con el del apiserver, y las tareas mueren con un 401 que no explica
nada. Hay que poner el **mismo** valor en todos los servicios:

```yaml
AIRFLOW__CORE__EXECUTION_API_SERVER_URL: 'http://airflow-apiserver:8080/execution/'
AIRFLOW__API_AUTH__JWT_SECRET: ${AIRFLOW__API_AUTH__JWT_SECRET:-...}
```

### 2. `catchup` por defecto rellena el pasado

Con `catchup=True` (o sin declararlo, según la versión), al despausar el DAG se
disparan de golpe **todas** las ventanas desde `start_date`. Con un cron semanal
y una `start_date` de hace un año, son 52 corridas simultáneas contra una API
pública. En este DAG va `catchup=False` y `max_active_runs=1`.

---

## dbt en su propio venv dentro de la imagen

`orquestacion/Dockerfile` no hace `pip install -r requirements.lock` sobre
Airflow. Crea un entorno aparte en `/opt/dbt-venv` y el DAG llama a
`/opt/dbt-venv/bin/python`, que es **otro intérprete**.

El motivo es que Airflow y dbt dependen los dos de Jinja2, con rangos de versión
que no siempre se solapan. Instalar `dbt-duckdb` encima de Airflow acaba en uno
de dos sitios: pip degrada algo de Airflow para contentar a dbt, o se niega a
resolver.

Es **el mismo razonamiento que ya estaba en el proyecto** para no usar el Python
global de la máquina, un nivel más arriba. El pipeline necesita sus versiones de
pandas y pyarrow — pyarrow es quien escribe los Parquet que lee Power BI, y ya
rompió una vez con `large_string`. El orquestador necesita las suyas. Se hablan
por la línea de comandos, que es una frontera mucho más estable que un árbol de
dependencias compartido.

## El almacén DuckDB vive en un volumen, no en el repo montado

```yaml
SECOP_DUCKDB: /opt/airflow/almacen/warehouse.duckdb
```

Dos motivos:

1. **DuckDB bloquea su archivo**, y el bind mount de Windows pasa por la VM de
   Docker Desktop, donde el bloqueo de archivos no es fiable.
2. **Separa el estado del orquestador del directorio de trabajo.** Si el
   pipeline corre en Airflow y también a mano en Windows, no se pisan.

Los Parquet sí van al repo montado: escribir un archivo completo no necesita
bloqueo, y Power BI tiene que poder leer `data/curated/`.

---

## Cómo se corre

```bash
cd orquestacion
cp .env.ejemplo .env          # y poner un JWT propio
docker compose up -d --build
```

Luego `http://localhost:8080`, usuario y clave `airflow` / `airflow`.

El DAG nace **pausado** (`DAGS_ARE_PAUSED_AT_CREATION`), así que no se dispara
solo mientras se está probando. Para una corrida de prueba sin bajar de la API,
usar *Trigger DAG w/ config* y desmarcar el parámetro `descargar`: usa el crudo
que ya esté en `data/raw/`.

Para bajarlo:

```bash
docker compose down        # conserva la base de metadatos
docker compose down -v     # la borra también
```

---

## Verificación

Medido el **2026-11-01** en Windows con Docker Desktop (8 CPUs, 7,8 GB para la
VM), corriendo el DAG contra el crudo del 2026-10-05.

| | |
|---|---|
| Imagen base `apache/airflow:3.3.2` | 3,18 GB |
| Los 4 servicios en `healthy` | **30 s** desde `up -d` |
| DAG reconocido, errores de importación | **0** |
| Corrida completa (sin descarga) | **73,4 s** |

Por tarea, en una corrida limpia:

| Tarea | Segundos | Intentos |
|---|---|---|
| `descargar` (omitida por parámetro) | 11,4 | 1 |
| `aterrizar` | 9,3 | 1 |
| `dbt_build` (10 modelos + 57 tests) | 44,5 | 1 |
| `registrar_corrida` | 1,0 | 1 |
| `exportar` | 1,7 | 1 |

Y lo que de verdad había que probar: **el pipeline en Airflow produce los mismos
datos que la corrida local.**

| | |
|---|---|
| Contratos fiables | 66.874 — igual |
| Valor contratado | $88.273.777.947.266 — igual |
| **Diferencias de contenido en las 8 tablas** | **0** |

El `WARNING` de la bitácora es el resultado correcto: son los 4 avisos del
origen ya documentados, no un fallo.

### Un hallazgo: los bytes cambian, el contenido no

Las 8 tablas salieron con **bytes distintos** a los de la corrida local, pero
con **0 diferencias de contenido**. La causa es el **orden de las filas**: en 6
de las 8 tablas cambió.

Es esperable —  los modelos de gold no llevan `order by`, y DuckDB los construye
con varios hilos, así que el orden no está garantizado entre corridas — y para
Power BI es irrelevante, porque una dimensión no se lee por posición.

Pero deja dos cosas claras:

1. **Para Parquet, «byte a byte idéntico» no es el criterio correcto** de que dos
   corridas dieron lo mismo. El criterio es la igualdad de conjuntos, en los dos
   sentidos. `etl/probar_gate.py` sí puede comparar bytes, porque en esa prueba
   los archivos no se reescriben: el gate impide la exportación.
2. Si algún día se quiere que las salidas sean **reproducibles byte a byte**
   (útil para detectar cambios con `git diff` o un hash), haría falta un
   `order by` explícito por la clave subrogada en cada modelo de gold. Hoy no
   hace falta y añadiría una ordenación que nadie usa.

### La trampa de `git` en un repo montado

Instalar git en la imagen no basta. El repo montado pertenece al usuario de
Windows y el contenedor corre como uid 50000, así que git aborta:

```
fatal: detected dubious ownership in repository at '/opt/secop'
```

Sale con código 128, `registrar_corrida.py` lo interpreta como «no hay git» y
anota `git_sha` nulo **sin avisar de nada** — la corrida queda registrada pero
deja de ser reproducible, que es justo para lo que existe la columna. Se arregla
en el Dockerfile con `git config --system --add safe.directory /opt/secop`.

## Pendiente

- **La descarga incremental no está conectada de punta a punta.** Ver la nota en
  [calidad-datos.md](calidad-datos.md) o el detalle abajo: `descargar.py --desde`
  escribe en `data/raw/obra-desde-AAAA-MM-DD.ndjson`, pero `aterrizar.py` solo
  lee `data/raw/obra.ndjson`. Por eso el DAG descarga el universo completo y no
  usa `--desde`.
- **Airflow no está en el CI.** El workflow de GitHub Actions sigue corriendo el
  pipeline con `correr_pipeline.py`, que es lo correcto: levantar cinco
  contenedores en cada push para orquestar un pipeline de 15 segundos no aporta
  nada. Airflow es el orquestador local y programado, no el de integración.
