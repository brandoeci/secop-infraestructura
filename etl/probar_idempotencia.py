"""Prueba que correr el pipeline dos veces seguidas no cambia nada.

Idempotencia: f(f(x)) = f(x). Es la propiedad que separa un script de un
pipeline. Sin ella no se puede reintentar una corrida que fallo a la mitad,
no se puede programar en un cron sin miedo, y no hay forma de saber si el
origen cambio o si solo se reescribio todo otra vez.

Lo que hace:

  1. `dbt build --full-refresh`  deja un estado limpio y conocido.
  2. `dbt build`                 segunda corrida sobre el MISMO bronze: el
                                 MERGE tiene que recibir 0 filas. No 'las
                                 actualizo con el mismo valor': no las toco.
  3. Control positivo            se ensucia el hash de un contrato y se
                                 comprueba que la corrida detecta exactamente
                                 ese. Un test que siempre da cero no prueba
                                 nada: si el filtro estuviera mal escrito y no
                                 detectara ningun cambio, el paso 2 pasaria
                                 igual.
  4. `dbt build`                 repara esa fila y vuelve al estado inicial.

Ademas compara el contenido de las 8 tablas gold por checksum. El checksum es
`bit_xor` sobre el hash de cada fila: no depende del orden en que DuckDB
devuelva las filas, que puede variar entre corridas por el paralelismo y no
significaria nada.

Uso:
  python etl/probar_idempotencia.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import duckdb

PROYECTO = Path("transformaciones")
ALMACEN = Path("data/warehouse.duckdb")

TABLAS = [
    "hecho_contratos",
    "dim_entidad", "dim_proveedor", "dim_fecha",
    "dim_tipo_contrato", "dim_estado", "dim_modalidad", "dim_categoria",
]


def dbt(proyecto: Path, *args: str) -> None:
    """Corre dbt y falla la prueba si dbt falla."""
    exe = Path(sys.executable).parent / "dbt.exe"
    if not exe.exists():
        exe = Path(sys.executable).parent / "dbt"
    cmd = [str(exe), "build", "--profiles-dir", ".", *args]
    print(f"     $ dbt build {' '.join(args)}")
    r = subprocess.run(cmd, cwd=proyecto, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-3000:])
        print(r.stderr[-2000:])
        raise SystemExit(f"dbt build {' '.join(args)} fallo con codigo {r.returncode}")


def filas_candidatas(proyecto: Path, almacen: Path) -> int:
    """Filas que el MERGE recibio en la ultima corrida incremental.

    dbt-duckdb no reporta rows_affected en run_results.json, asi que el dato
    se saca de donde no puede mentir: el SQL que dbt compilo y ejecuto, que
    queda en target/compiled/. Contar sobre ese mismo SQL mide exactamente lo
    que le llego al MERGE, sin reescribir aqui la logica del filtro, que
    seria probar una copia en lugar del original.
    """
    sql = (proyecto / "target" / "compiled" / "secop" / "models" / "marts"
           / "hecho_contratos.sql").read_text(encoding="utf-8")
    con = duckdb.connect(str(almacen), read_only=True)
    try:
        con.execute("use main_silver")   # el SQL compilado no cualifica el ref
        return con.execute(f"select count(*) from ({sql})").fetchone()[0]
    finally:
        con.close()


def desincronizar_una_fila(almacen: Path) -> str:
    """Ensucia el hash de un contrato, para simular que el origen lo cambio."""
    con = duckdb.connect(str(almacen))
    try:
        id_contrato = con.execute(
            "select min(id_contrato) from main_gold.hecho_contratos").fetchone()[0]
        con.execute("update main_gold.hecho_contratos "
                    "set hash_atributos = hash_atributos - 1 "
                    "where id_contrato = ?", [id_contrato])
        return id_contrato
    finally:
        con.close()


def leer_huellas(almacen: Path) -> dict[str, tuple]:
    """Conteo y checksum de cada tabla gold, independiente del orden de filas."""
    con = duckdb.connect(str(almacen), read_only=True)
    try:
        return {
            t: con.execute(
                f"select count(*), bit_xor(hash(t::VARCHAR)) from main_gold.{t} t"
            ).fetchone()
            for t in TABLAS
        }
    finally:
        con.close()


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--proyecto", type=Path, default=PROYECTO)
    p.add_argument("--almacen", type=Path, default=ALMACEN)
    a = p.parse_args()

    print("=" * 68)
    print("PRUEBA DE IDEMPOTENCIA")
    print("=" * 68)
    fallos: list[str] = []

    print("\n1. Primera corrida (--full-refresh), para partir de un estado limpio")
    dbt(a.proyecto, "--full-refresh")
    primera = leer_huellas(a.almacen)
    print(f"     hecho_contratos: {primera['hecho_contratos'][0]:,} filas escritas")

    print("\n2. Segunda corrida sobre el mismo bronze, sin --full-refresh")
    dbt(a.proyecto)
    segunda = leer_huellas(a.almacen)
    tocadas = filas_candidatas(a.proyecto, a.almacen)
    print(f"     el MERGE recibio {tocadas} filas  (esperado 0)")
    if tocadas != 0:
        fallos.append(f"el MERGE recibio {tocadas} filas en una corrida sin cambios")

    print("\n3. Control positivo: se ensucia el hash de un contrato")
    id_sucio = desincronizar_una_fila(a.almacen)
    detectadas = filas_candidatas(a.proyecto, a.almacen)
    print(f"     contrato {id_sucio}")
    print(f"     el filtro detecta {detectadas} fila  (esperado 1)")
    if detectadas != 1:
        fallos.append(f"el filtro detecto {detectadas} filas tras ensuciar una, "
                      "esperaba 1: no distingue lo que cambio de lo que no")

    print("\n4. Tercera corrida: repara esa fila y vuelve al estado inicial")
    dbt(a.proyecto)
    tras_reparar = filas_candidatas(a.proyecto, a.almacen)
    tercera = leer_huellas(a.almacen)
    print(f"     el MERGE recibio {tras_reparar} filas despues de reparar  (esperado 0)")
    if tras_reparar != 0:
        fallos.append(f"tras reparar quedaron {tras_reparar} filas pendientes")
    if tercera != primera:
        fallos.append("el estado tras reparar no coincide con el inicial")

    print("\n" + "=" * 68)
    print("CONTENIDO DE LAS TABLAS GOLD")
    print("=" * 68)
    print(f"{'tabla':22} {'filas':>9}  {'checksum':>22}  corrida 1 vs 2")
    print("-" * 68)
    for t in TABLAS:
        n1, c1 = primera[t]
        n2, c2 = segunda[t]
        igual = (n1, c1) == (n2, c2)
        print(f"{t:22} {n2:>9,}  {c2:>22}  {'identica' if igual else 'CAMBIO'}")
        if not igual:
            fallos.append(f"{t}: {n1:,} filas/{c1} -> {n2:,} filas/{c2}")

    print("=" * 68)
    if fallos:
        print(f"NO ES IDEMPOTENTE. {len(fallos)} problemas:")
        for f in fallos:
            print(f"  - {f}")
        sys.exit(1)
    print("IDEMPOTENTE")
    print("  - la segunda corrida no inserto ni actualizo ninguna fila")
    print("  - el contenido de las 8 tablas gold no cambio")
    print("  - y el mecanismo si detecta un cambio real cuando lo hay")


if __name__ == "__main__":
    main()
