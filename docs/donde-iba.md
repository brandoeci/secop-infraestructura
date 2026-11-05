# Dónde iba: estado al 1 de noviembre de 2026

La sesión de Claude Code en la que se construyó este proyecto desde el 5 de octubre se
perdió el 1 de noviembre: el PC se congeló, se apagó a la fuerza y Windows descartó el
archivo de la conversación al arrancar. No hay instantáneas de volumen de esa carpeta.

Esta nota existe para que no haga falta esa conversación. Todo lo de abajo está verificado
contra el repositorio y contra los logs, no contra la memoria de nadie.

## El repositorio

37 commits. El último es `251693f Hace el SQL portable entre DuckDB y BigQuery`.

Hay **dos líneas de trabajo abiertas** y conviene no confundirlas: la migración a GCP, que
va por fases y está parada esperando una cuenta, y la orquestación con Airflow, que se hizo
el 1 de noviembre y funciona pero está sin versionar.

## Línea A — Migración a GCP

El plan completo está en [`docs/migracion-gcp.md`](migracion-gcp.md), recuperado del archivo
de planes de la sesión perdida y guardado en el repositorio el 1 de noviembre. Son cinco
fases. La idea de fondo: que el mismo proyecto dbt corra en los dos motores, de modo que
cambiar de DuckDB a BigQuery sea una bandera (`dbt build --target cloud`) y no una copia del
resultado ya transformado.

| Fase | Estado | ¿Necesita cuenta GCP? |
|---|---|---|
| 1 — SQL portable, verificado en local | **hecha**, commit `251693f` | no |
| 2 — La cuenta y bronze en la nube | pendiente | sí |
| 3 — `dbt build --target cloud` | pendiente | sí |
| 4 — Probar que los dos motores dan lo mismo | pendiente | sí |
| 5 — CI y documentación | pendiente | sí |

Lo que la Fase 1 dejó hecho: nueve archivos tocados, entre ellos un
`transformaciones/macros/dialecto.sql` nuevo de 196 líneas, y las claves subrogadas pasadas
de `hash()` a MD5 para que valgan lo mismo en los dos motores.

Cómo comprobar que las fases 3 y 4 siguen pendientes, sin creerle a esta nota:
`transformaciones/profiles.yml` no tiene un output `cloud`, y `etl/comparar_motores.py` no
existe. Tampoco hay `.github/workflows/nube.yml`, que es la Fase 5.

**`gcp/` sigue sin versionar, y es a propósito.** Tiene `01-cargar.sh`, `02-consultas.sql`,
`validar_consultas.py` (las cinco consultas pasan contra DuckDB) y `servicio/`, una API
FastAPI para Cloud Run. El plan decidió dos cosas sobre esa carpeta: `01-cargar.sh` se rehace
como `gcp/01-bronze.sh` porque debe subir **bronze** y no `curated` (con este enfoque la
transformación ocurre dentro de BigQuery), y `servicio/` queda fuera hasta que BigQuery
funcione. Por eso no se commiteó: no es olvido.

## Línea B — Orquestación con Airflow

Hecha el 1 de noviembre. El razonamiento está en [`docs/orquestacion.md`](orquestacion.md),
274 líneas: por qué el pipeline pasó de un script con `if` a un grafo de tareas, habiendo ya
un cron en GitHub Actions.

Archivos, todos sin versionar al cierre del día:

- `orquestacion/docker-compose.yml`
- `orquestacion/dags/secop_pipeline.py`
- `orquestacion/Dockerfile`
- `orquestacion/.env.ejemplo`
- `docs/orquestacion.md`
- `.gitignore` modificado, para excluir `orquestacion/logs/`, `config/` y `plugins/`

### El DAG corrió completo y pasó

Esto es lo importante, y está en los logs, bajo
`orquestacion/logs/dag_id=secop_pipeline/`. Corrida manual del 1 de noviembre, de las 16:01
a las 16:07:57 hora local:

| Tarea | Resultado |
|---|---|
| `descargar` | intento 1 falló, **intento 2 pasó** |
| `dbt_build` | `PASS=63 WARN=4 ERROR=0 SKIP=0 TOTAL=67`, código de salida 0 |
| `exportar` | «escrito en data/curated/», código 0 |
| `registrar_corrida` | «12 corridas en auditoria_corridas.parquet», código 0 |

Que `descargar` fallara y reintentara **solo esa tarea**, sin repetir las anteriores, es
justo el argumento que `docs/orquestacion.md` da para preferir Airflow al cron. Queda
demostrado en los logs del propio proyecto, que es mejor que afirmarlo.

Antes de eso, a las 15:36, terminaron de construirse las cuatro imágenes:
`airflow-apiserver`, `airflow-dag-processor`, `airflow-init` y `airflow-scheduler`.

## Lo siguiente

1. **Commitear la línea B:** `orquestacion/`, `docs/orquestacion.md` y el `.gitignore`. No
   `gcp/`, por lo explicado arriba. Va primero porque es trabajo terminado y probado que hoy
   vive solo en el directorio de trabajo, que es exactamente lo que el corte de energía puso
   en riesgo.
2. **Fase 2 de la migración**, cuando exista la cuenta GCP. El plan trae los comandos
   exactos. El coste a esta escala es cero permanente: 12 MB contra 10 GB gratis de
   almacenamiento y 1 TB al mes de consultas. La prueba gratuita sí pide tarjeta.
3. **Pendiente viejo, anterior a todo esto:** el cruce con la red vial de INVIAS no se hizo.
   El README y varios CV prometen SECOP + INVIAS, y hoy el proyecto es SECOP solo. O se
   cierra, o se le quita INVIAS al título.

## Rastros de la sesión perdida, por si hace falta algo

- `~/.claude/file-history/5ad09def-1b46-43d4-9e1f-208ad19674a5/` — 48 instantáneas con
  versiones de los archivos que esa sesión editó, entre el 5 de octubre y el 1 de noviembre.
  Si algo se perdió con el corte, la versión anterior está ahí.
- `%TEMP%/claude/C--Users-Asus-Tuf-Gaming-secop-infraestructura/5ad09def-.../scratchpad/` —
  respaldo de los nueve Parquet de `data/curated/` hecho el 1 de noviembre a las 15:44, el
  `build.log` de la construcción de las imágenes y un `compose-oficial.yml`.
- La memoria del proyecto, dos notas: usar `.venv` y no el Python global para dbt, y no meter
  una herramienta pesada hasta que el volumen la exija.
