"""Acumula en una tabla lo que hizo cada corrida del pipeline.

Antes de esto, un fallo era silencioso y no quedaba constancia de ninguna
corrida: habia que acordarse de haberla lanzado. Con la bitacora hay historia
de ejecucion, que es la diferencia entre 'corri el script' y 'tengo un
pipeline'.

No instrumenta nada a mano. dbt ya escribe `target/run_results.json` y
`target/manifest.json` en cada corrida con el estado de cada modelo y de cada
test; esto solo los lee y los acumula. Una observabilidad que hay que
mantener aparte se deja de mantener.

Columnas de data/curated/auditoria_corridas.parquet:

  run_id              el invocation_id de dbt, unico por corrida
  ejecutada_en        cuando arranco (UTC)
  git_sha             commit con el que se corrio, para poder reproducirla
  duracion_segundos   lo que tardo
  resultado           PASS, WARNING o FAIL
  modelos_ok          modelos construidos sin error
  tests_pass/warn/fail/error
  filas_bronze/silver/gold

Se escribe despues de `dbt build`, haya ido bien o mal: una corrida que
fallo es justo la que mas interesa tener registrada.

Uso:
  python etl/registrar_corrida.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import duckdb

PROYECTO = Path("transformaciones")
ALMACEN = Path("data/warehouse.duckdb")
SALIDA = Path("data/curated/auditoria_corridas.parquet")


def git_sha() -> str | None:
    """El commit actual, para que una corrida se pueda reproducir."""
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def ruta_bronze(proyecto: Path) -> Path:
    """Donde esta el bronze de esta corrida.

    Se lee de SECOP_BRONZE, la misma variable que usa la fuente de dbt, para
    que la bitacora cuente el bronze que de verdad se proceso. En el CI eso es
    el fixture de tests/fixtures/, no data/bronze/, y antes se reportaba como
    n/d por mirar siempre la ruta por defecto.

    La variable es relativa al directorio del proyecto dbt, igual que en
    fuentes.yml, asi que se resuelve desde ahi.
    """
    base = os.environ.get("SECOP_BRONZE")
    if base:
        return (proyecto / base / "contratos.parquet").resolve()
    return Path("data/bronze/contratos.parquet")


def contar_filas(almacen: Path, proyecto: Path) -> dict[str, int | None]:
    """Filas en cada capa, para ver de un vistazo donde se quedo el dato."""
    if not almacen.exists():
        return {"bronze": None, "silver": None, "gold": None}
    con = duckdb.connect(str(almacen), read_only=True)
    try:
        def una(sql: str) -> int | None:
            try:
                return con.execute(sql).fetchone()[0]
            except duckdb.Error:
                return None
        bronze = ruta_bronze(proyecto)
        return {
            "bronze": (una("select count(*) from "
                           f"read_parquet('{bronze.as_posix()}')")
                       if bronze.exists() else None),
            "silver": una("select count(*) from main_silver.int_contratos_calidad"),
            "gold": una("select count(*) from main_gold.hecho_contratos"),
        }
    finally:
        con.close()


def leer_corrida(proyecto: Path) -> dict:
    """Resume run_results.json en una fila de bitacora."""
    ruta = proyecto / "target" / "run_results.json"
    if not ruta.exists():
        raise SystemExit(f"falta {ruta}. Corra primero:\n"
                         "  cd transformaciones && dbt build --profiles-dir .")
    d = json.loads(ruta.read_text(encoding="utf-8"))

    manifest = proyecto / "target" / "manifest.json"
    tipos = {}
    if manifest.exists():
        nodos = json.loads(manifest.read_text(encoding="utf-8")).get("nodes", {})
        tipos = {k: v.get("resource_type") for k, v in nodos.items()}

    conteo = {"model_ok": 0, "model_error": 0,
              "pass": 0, "warn": 0, "fail": 0, "error": 0}
    for r in d["results"]:
        es_test = tipos.get(r["unique_id"], "").startswith("test") \
            or ".test." in r["unique_id"] or r["unique_id"].startswith("test.")
        estado = r["status"]
        if es_test:
            conteo[estado] = conteo.get(estado, 0) + 1
        elif estado in ("success", "pass"):
            conteo["model_ok"] += 1
        else:
            conteo["model_error"] += 1

    # Semantica del gate: FAIL si algo rompio, WARNING si hay avisos
    # conocidos, PASS si esta todo limpio.
    if conteo["fail"] or conteo["error"] or conteo["model_error"]:
        resultado = "FAIL"
    elif conteo["warn"]:
        resultado = "WARNING"
    else:
        resultado = "PASS"

    arranque = d["metadata"].get("generated_at")
    return {
        "run_id": d["metadata"].get("invocation_id"),
        "ejecutada_en": arranque,
        "duracion_segundos": round(d.get("elapsed_time") or 0.0, 3),
        "resultado": resultado,
        "modelos_ok": conteo["model_ok"],
        "modelos_error": conteo["model_error"],
        "tests_pass": conteo["pass"],
        "tests_warn": conteo["warn"],
        "tests_fail": conteo["fail"] + conteo["error"],
    }


def registrar(proyecto: Path, almacen: Path, salida: Path) -> None:
    fila = leer_corrida(proyecto)
    fila["git_sha"] = git_sha()
    fila.update({f"filas_{k}": v
             for k, v in contar_filas(almacen, proyecto).items()})
    if not fila["ejecutada_en"]:
        fila["ejecutada_en"] = datetime.now(UTC).isoformat(timespec="seconds")

    con = duckdb.connect(":memory:")
    columnas = ["run_id", "ejecutada_en", "git_sha", "duracion_segundos",
                "resultado", "modelos_ok", "modelos_error",
                "tests_pass", "tests_warn", "tests_fail",
                "filas_bronze", "filas_silver", "filas_gold"]

    con.execute("""
        create table nueva (
            run_id VARCHAR, ejecutada_en TIMESTAMP, git_sha VARCHAR,
            duracion_segundos DOUBLE, resultado VARCHAR,
            modelos_ok INTEGER, modelos_error INTEGER,
            tests_pass INTEGER, tests_warn INTEGER, tests_fail INTEGER,
            filas_bronze BIGINT, filas_silver BIGINT, filas_gold BIGINT
        )
    """)
    con.execute(f"insert into nueva values ({', '.join('?' * len(columnas))})",
                [fila.get(c) for c in columnas])

    salida.parent.mkdir(parents=True, exist_ok=True)
    if salida.exists():
        # Se acumula, no se reemplaza: la bitacora es la historia. Si la misma
        # corrida se registra dos veces, se queda una (el run_id es unico).
        con.execute(f"""
            copy (
                select * from read_parquet('{salida.as_posix()}')
                where run_id not in (select run_id from nueva)
                union all by name
                select * from nueva
                order by ejecutada_en
            ) to '{salida.as_posix()}.nuevo' (format parquet, compression snappy)
        """)
        Path(f"{salida}.nuevo").replace(salida)
    else:
        con.execute(f"copy nueva to '{salida.as_posix()}' "
                    "(format parquet, compression snappy)")

    total = con.execute(
        f"select count(*) from read_parquet('{salida.as_posix()}')").fetchone()[0]

    print(f"corrida {fila['run_id']}")
    print(f"  resultado          {fila['resultado']}")
    print(f"  duracion           {fila['duracion_segundos']} s")
    print(f"  commit             {fila['git_sha']}")
    print(f"  modelos            {fila['modelos_ok']} ok, "
          f"{fila['modelos_error']} con error")
    print(f"  tests              {fila['tests_pass']} pass, "
          f"{fila['tests_warn']} warn, {fila['tests_fail']} fail")
    # Cada capa se formatea por separado: si una no se pudo contar, se dice de
    # esa y no se pierden las otras dos. Antes el guard miraba filas_gold y
    # reventaba cuando la que faltaba era filas_bronze.
    def mil(clave: str) -> str:
        v = fila.get(clave)
        return f"{v:,}" if isinstance(v, int) else "n/d"

    print(f"  filas              bronze {mil('filas_bronze')} -> "
          f"silver {mil('filas_silver')} -> gold {mil('filas_gold')}")
    print(f"\n{total} corridas en {salida}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--proyecto", type=Path, default=PROYECTO)
    p.add_argument("--almacen", type=Path, default=ALMACEN)
    p.add_argument("--salida", type=Path, default=SALIDA)
    a = p.parse_args()
    registrar(a.proyecto, a.almacen, a.salida)


if __name__ == "__main__":
    main()
