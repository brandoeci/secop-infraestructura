"""Orquestacion del pipeline SECOP: de la API de Socrata a los Parquet de Power BI.

POR QUE AIRFLOW SI YA HABIA UN CRON EN GITHUB ACTIONS
-----------------------------------------------------
El cron de .github/workflows/pipeline.yml corre un solo comando,
`correr_pipeline.py`, y ese script lleva los cinco pasos DENTRO, en Python, con
codigos de salida y un if. Funciona. Lo que no da:

  1. Si falla el paso 3, hay que volver a correr los pasos 1 y 2. La descarga de
     67.000 contratos se repite para nada. En Airflow se reintenta SOLO la tarea
     que fallo, con las anteriores ya en verde.
  2. "Que paso?" se contesta leyendo un log de 400 lineas. En Airflow se mira el
     grafo y se ve el cuadrito rojo.
  3. Los reintentos son del workflow entero o de nada. Aqui cada tarea tiene su
     politica: la descarga reintenta porque la red falla sola; `dbt build` NO
     reintenta, porque un test que fallo va a volver a fallar.
  4. No hay historia navegable: el log de Actions caduca. Airflow guarda el
     estado de cada tarea de cada corrida en su base de metadatos.

Y la que mas vale en una entrevista:

  5. EL GATE DEJA DE SER UN `if` Y PASA A SER LA FORMA DEL GRAFO.

     En correr_pipeline.py el control de calidad es esto:

         codigo_gate = dbt(...)
         python("registrar_corrida.py")
         if codigo_gate != 0:
             sys.exit(codigo_gate)      # y exportar.py nunca corre
         python("exportar.py")

     Aqui es esto:

         aterrizar >> dbt_build >> exportar     # exportar exige exito
         dbt_build >> registrar                 # registrar corre igual

     La misma garantia, pero declarada en las dependencias en vez de codificada
     en el control de flujo. Airflow la hace cumplir: no hay forma de que
     `exportar` corra si `dbt_build` fallo, ni de olvidarse de `registrar`.

LO QUE NO CAMBIA
----------------
Ni una linea de etl/ ni de transformaciones/. Airflow no reimplementa el
pipeline: lo llama. Si manana se cambia de orquestador, el pipeline sigue
corriendo con `python etl/correr_pipeline.py` como siempre. Un orquestador que
se mete dentro de la logica se vuelve imposible de abandonar.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, Param
from alertas import avisar_fallo

# --- Rutas DENTRO del contenedor ---
#
# El repo se monta en /opt/secop. El pipeline corre con el interprete de su
# propio venv, no con el de Airflow: ver el por que en orquestacion/Dockerfile.
RAIZ = "/opt/secop"
PROYECTO_DBT = f"{RAIZ}/transformaciones"
PY = "/opt/dbt-venv/bin/python"
DBT = "/opt/dbt-venv/bin/dbt"

# Se arma aparte porque lleva comillas dentro y en linea queda ilegible.
# "{{ params.descargar }}" lo sustituye Jinja antes de que bash vea la linea.
COMANDO_DESCARGA = (
    'if [ "{{ params.descargar }}" = "True" ]; then\n'
    f"  {PY} etl/descargar.py --universo obra\n"
    "else\n"
    '  echo "Descarga omitida por parametro: se usa el crudo de data/raw/."\n'
    "fi\n"
)

# Igual que el de la descarga: Jinja resuelve el {% if %} y bash recibe la
# linea ya decidida. Sin el parametro, `dbt build` carga el hecho de forma
# incremental (MERGE); con el, lo reconstruye entero desde el bronze actual.
#
# Hace falta porque el MERGE inserta y actualiza pero NO borra, y las
# dimensiones si se reconstruyen en cada corrida. Cuando el origen pierde
# filas, el hecho se queda con claves que apuntan a dimensiones que ya no
# existen y los tests de integridad referencial se ponen rojos. Paso el
# 2026-11-03 con 974 contratos retirados y 448 claves huerfanas.
#
# Es un parametro y no el comportamiento por defecto porque reconstruir todo
# cada semana haria inutil la carga incremental. Se marca en
# "Trigger DAG w/ config" cuando hay que reparar.
COMANDO_DBT = (
    f"{DBT} build --profiles-dir ."
    "{% if params.reconstruir %} --full-refresh{% endif %}"
)

with DAG(
    dag_id="secop_pipeline",
    description="Medallion SECOP II: bronze, silver, gold, 67 tests y exportacion",
    # Lunes 06:00 en Bogota. El mismo horario que tenia el cron de Actions.
    schedule="0 6 * * 1",
    start_date=pendulum.datetime(2026, 11, 1, tz="America/Bogota"),
    # Sin catchup: al despausar el DAG no se disparan de golpe todas las semanas
    # que pasaron desde start_date. Es el error de principiante mas comun, y
    # aqui significaria varias descargas simultaneas contra una API publica.
    catchup=False,
    # Una corrida a la vez: dos escribiendo el mismo almacen DuckDB se pisan.
    # Es el equivalente del 'concurrency' que ya tiene el workflow de Actions.
    max_active_runs=1,
    default_args={
        # Por defecto NADA reintenta. Se activa tarea por tarea y con un motivo.
        "retries": 0,
        # Avisa solo cuando la tarea se queda SIN reintentos. Airflow tiene un
        # `on_retry_callback` aparte para el otro caso, y mezclarlos llenaria
        # el canal de falsas alarmas: `descargar` falla su primer intento a
        # menudo y se recupera sola. Una alerta que suena cuando no pasa nada
        # deja de mirarse, y entonces es peor que no tenerla.
        "on_failure_callback": avisar_fallo,
    },
    # OJO con el type="boolean": no es decorativo.
    #
    # Declarados como `True` / `False` pelados, Airflow los envuelve en
    # Param(default=...) con el esquema VACIO. El formulario de "Trigger" no
    # sabe entonces que son booleanos, no dibuja una casilla que enlace, y la
    # corrida se crea siempre con los valores por defecto: se marca lo que se
    # marque, la conf sale igual. Paso el 2026-11-03, tres corridas seguidas.
    #
    # Con el tipo declarado, la interfaz pinta una casilla de verdad y manda un
    # booleano. El title y la description son lo que se lee en ese formulario.
    params={
        "descargar": Param(
            True,
            type="boolean",
            title="Descargar de la API",
            description="Desmarcado, usa el crudo que ya esta en data/raw/. "
                        "Sirve para repetir una corrida sin depender de la red.",
        ),
        "reconstruir": Param(
            False,
            type="boolean",
            title="Reconstruir gold desde cero (--full-refresh)",
            description="Reparacion para cuando el origen perdio filas y el "
                        "MERGE dejo claves huerfanas. Ver COMANDO_DBT.",
        ),
    },
    tags=["secop", "medallion", "dbt"],
    doc_md=__doc__,
) as dag:

    # 1. API -> data/raw/obra.ndjson
    #
    # La UNICA tarea que reintenta, y el motivo es que es la unica cuyo fallo es
    # transitorio: la API publica se cae, da 503 o corta la conexion. Reintentar
    # tiene sentido porque el segundo intento puede salir bien sin que nadie
    # haya arreglado nada.
    #
    # Con backoff exponencial: si la API esta saturada, reintentar cada 10
    # segundos la satura mas. Espera 2, 4, 8 y 16 minutos.
    #
    # La descarga es reanudable (el NDJSON se escribe linea por linea y el
    # numero de lineas ya escritas es el proximo offset), asi que un reintento
    # continua donde quedo en vez de empezar de cero.
    descargar = BashOperator(
        task_id="descargar",
        bash_command=COMANDO_DESCARGA,
        cwd=RAIZ,
        retries=4,
        retry_delay=timedelta(minutes=2),
        retry_exponential_backoff=True,
        max_retry_delay=timedelta(minutes=20),
        execution_timeout=timedelta(hours=2),
        doc_md="API de Socrata -> `data/raw/obra.ndjson`. Reanudable.",
    )

    # 2. data/raw/obra.ndjson -> data/bronze/contratos.parquet
    #
    # Sin reintentos: si falla es porque el crudo esta truncado o el esquema
    # cambio. Reintentar da el mismo error y retrasa el diagnostico.
    aterrizar = BashOperator(
        task_id="aterrizar",
        bash_command=f"{PY} etl/aterrizar.py",
        cwd=RAIZ,
        execution_timeout=timedelta(minutes=30),
        doc_md="Bronze: crudo fiel al origen, todo texto. No limpia nada.",
    )

    # 3. silver + gold + los 67 tests. ESTE ES EL GATE.
    #
    # Sin reintentos, y es la decision mas importante del DAG. Un test de
    # calidad que fallo expresa un hecho sobre los datos, no un accidente:
    # volver a correrlo da exactamente el mismo resultado. Un reintento aqui
    # solo sirve para tardar cuatro veces mas en enterarse, y para dar la falsa
    # impresion de que el fallo es intermitente.
    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=COMANDO_DBT,
        cwd=PROYECTO_DBT,
        execution_timeout=timedelta(minutes=30),
        doc_md=(
            "Construye silver y gold y corre los 67 tests. **Si esta tarea "
            "falla, `exportar` no corre** y `data/curated/` se queda con el "
            "ultimo modelo bueno."
        ),
    )

    # 4. La bitacora. Corre PASE O FALLE.
    #
    # trigger_rule="all_done" es la pieza de Airflow que reemplaza al if de
    # correr_pipeline.py. La regla por defecto es "all_success": una tarea solo
    # arranca si TODAS las de arriba salieron bien. Con "all_done" arranca
    # cuando las de arriba TERMINARON, sin importar como.
    #
    # Es lo que hace falta aqui, porque una corrida que fallo es justo la que
    # mas interesa tener registrada. Con la regla por defecto, la bitacora solo
    # tendria las corridas buenas, que es la mitad inutil de la historia.
    #
    # Se pasa como texto y no con el enum TriggerRule para no depender de una
    # ruta de import que cambio entre Airflow 2 y 3. El texto es estable.
    registrar = BashOperator(
        task_id="registrar_corrida",
        bash_command=f'{PY} etl/registrar_corrida.py --almacen "$SECOP_DUCKDB"',
        cwd=RAIZ,
        trigger_rule="all_done",
        doc_md=(
            "Acumula una fila por corrida en `auditoria_corridas.parquet`. "
            "Con `trigger_rule=all_done` corre tambien cuando `dbt_build` falla."
        ),
    )

    # 5. gold -> data/curated/*.parquet, que es lo que lee Power BI.
    #
    # Sin trigger_rule, es decir con la de por defecto (all_success). Eso es
    # literalmente el gate: esta tarea no puede correr si dbt_build no termino
    # en verde. No hay condicion que escribir ni que recordar.
    exportar = BashOperator(
        task_id="exportar",
        bash_command=f'{PY} etl/exportar.py --almacen "$SECOP_DUCKDB"',
        cwd=RAIZ,
        execution_timeout=timedelta(minutes=15),
        doc_md="Solo corre si el gate paso. Escribe lo que refresca Power BI.",
    )

    descargar >> aterrizar >> dbt_build >> exportar
    dbt_build >> registrar
