# Imagen de Airflow con las dependencias del pipeline en su PROPIO venv.
#
# POR QUE UN VENV APARTE Y NO pip install -r requirements.lock SOBRE AIRFLOW
# --------------------------------------------------------------------------
# Airflow y dbt dependen los dos de Jinja2, y con rangos de version que no
# siempre se solapan. Instalar dbt-duckdb encima de Airflow acaba en uno de dos
# sitios: pip degrada algo de Airflow para contentar a dbt, o se niega a
# resolver. Los dos son peores que tenerlos separados.
#
# Es el mismo razonamiento que ya esta en el proyecto para no usar el Python
# global de la maquina, un nivel mas arriba. El pipeline necesita SUS versiones
# de pandas y pyarrow (pyarrow es quien escribe los Parquet que lee Power BI, y
# ya rompio una vez con large_string). El orquestador necesita las suyas. Se
# hablan por la linea de comandos, que es una frontera mucho mas estable que un
# arbol de dependencias compartido.
#
# Consecuencia practica: el DAG nunca hace "import pandas". Llama a
# /opt/dbt-venv/bin/python, que es otro interprete.

FROM apache/airflow:3.3.2

USER root

# git lo usa etl/registrar_corrida.py para anotar con que commit se corrio cada
# corrida. Sin git el pipeline funciona igual, pero la bitacora guarda git_sha
# nulo y la corrida deja de ser reproducible, que es justo para lo que existe.
RUN apt-get update \
 && apt-get install --no-install-recommends -y git \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# El contexto de build es la RAIZ del repo (ver docker-compose.yml), no esta
# carpeta, para poder copiar requirements.lock sin duplicarlo.
COPY requirements.lock /tmp/requirements.lock

# dbt --version al final del RUN a proposito: si el venv quedo mal, falla aqui
# al construir la imagen y no dentro de una tarea a las 6 de la manana.
RUN python -m venv /opt/dbt-venv \
 && /opt/dbt-venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/dbt-venv/bin/pip install --no-cache-dir -r /tmp/requirements.lock \
 && chmod -R a+rX /opt/dbt-venv \
 && /opt/dbt-venv/bin/dbt --version

# Sin esto, instalar git no sirve de nada: el repo montado pertenece al usuario
# de Windows y el contenedor corre como uid 50000, asi que git se niega con
# "detected dubious ownership" y sale con codigo 128. registrar_corrida.py trata
# el fallo como "no hay git" y anota git_sha nulo, sin avisar de nada.
#
# Es una proteccion real de git (un repo ajeno puede traer hooks que se
# ejecutan), pero aqui el "otro usuario" es el dueno de la maquina. Va --system
# y no --global para que aplique a cualquier usuario del contenedor.
RUN git config --system --add safe.directory /opt/secop

USER airflow
