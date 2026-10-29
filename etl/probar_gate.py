"""Prueba que el control de calidad bloquea de verdad.

Un gate que avisa pero deja pasar no es un gate, y la unica forma de saber de
que lado esta el nuestro es romperlo a proposito.

La prueba inyecta en bronze un contrato con el mismo perfil del error que se
encontro a mano en este dataset (uno de minima cuantia por 6,45 cuatrillones
de pesos, que explicaba el 98,6 % del valor total) y comprueba tres cosas:

  1. `dbt build` termina en error, no en aviso.
  2. El test que lo caza es concentracion_de_valor, el que se escribio para
     esto.
  3. **data/curated/ queda byte a byte identico.** Esto es lo importante: el
     registro malo si entra al gold de DuckDB, porque es ahi donde el test
     puede verlo, pero no llega a los Parquet que lee Power BI. El informe
     sigue mostrando el ultimo modelo bueno en vez de refrescar sobre datos
     malos.

Al terminar deja bronze y el almacen como estaban, pase o falle.

Uso:
  python etl/probar_gate.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb

PROYECTO = Path("transformaciones")
BRONZE = Path("data/bronze/contratos.parquet")
CURATED = Path("data/curated")

# Mismo perfil que el error real documentado en docs/calidad-datos.md.
ID_INYECTADO = "CO1.PCCNTR.PRUEBA-GATE"
VALOR_ABSURDO = "6453840000000000"
TEST_ESPERADO = "concentracion_de_valor"


def dbt(proyecto: Path, *args: str) -> tuple[int, str]:
    exe = Path(sys.executable).parent / "dbt.exe"
    if not exe.exists():
        exe = Path(sys.executable).parent / "dbt"
    r = subprocess.run([str(exe), "build", "--profiles-dir", ".", *args],
                       cwd=proyecto, capture_output=True, text=True)
    return r.returncode, r.stdout


def huella(carpeta: Path) -> str:
    """sha256 del contenido completo de los Parquet de la carpeta."""
    h = hashlib.sha256()
    for f in sorted(carpeta.glob("*.parquet")):
        h.update(f.read_bytes())
    return h.hexdigest()


def inyectar(bronze: Path) -> None:
    """Agrega a bronze una copia de la primera fila con un valor absurdo."""
    respaldo = bronze.with_suffix(".parquet.respaldo")
    shutil.copy2(bronze, respaldo)
    con = duckdb.connect(":memory:")
    con.execute(f"""
        copy (
            select * from read_parquet('{respaldo.as_posix()}')
            union all
            select * from (
                select * replace (
                    '{ID_INYECTADO}' as id_contrato,
                    '{VALOR_ABSURDO}' as valor_del_contrato
                )
                from read_parquet('{respaldo.as_posix()}')
                limit 1
            )
        ) to '{bronze.as_posix()}' (format parquet, compression snappy)
    """)
    con.close()


def restaurar(bronze: Path, proyecto: Path) -> None:
    respaldo = bronze.with_suffix(".parquet.respaldo")
    if respaldo.exists():
        shutil.move(str(respaldo), str(bronze))
    dbt(proyecto, "--full-refresh")


def tests_fallidos(proyecto: Path) -> list[str]:
    datos = json.loads((proyecto / "target" / "run_results.json")
                       .read_text(encoding="utf-8"))
    return [r["unique_id"].split(".")[-1]
            for r in datos["results"] if r["status"] == "fail"]


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--proyecto", type=Path, default=PROYECTO)
    p.add_argument("--bronze", type=Path, default=BRONZE)
    p.add_argument("--curated", type=Path, default=CURATED)
    a = p.parse_args()

    if not a.bronze.exists():
        raise SystemExit(f"falta {a.bronze}. Corra primero:\n"
                         "  python etl/aterrizar.py")

    print("=" * 68)
    print("PRUEBA DEL CONTROL DE CALIDAD")
    print("=" * 68)
    fallos: list[str] = []

    antes = huella(a.curated)
    print(f"\n0. Estado inicial de data/curated/: sha256 {antes[:32]}")

    print(f"\n1. Se inyecta en bronze un contrato por {VALOR_ABSURDO} pesos")
    print(f"   ({ID_INYECTADO}, mismo perfil que el error real)")
    inyectar(a.bronze)

    try:
        print("\n2. Se corre el pipeline completo")
        codigo, salida = dbt(a.proyecto)
        resumen = next((L for L in salida.splitlines() if "Done." in L), "?")
        print(f"   dbt termino con codigo {codigo}  (esperado distinto de 0)")
        print(f"   {resumen.strip()}")
        if codigo == 0:
            fallos.append("dbt build termino en exito con un registro corrupto "
                          "en bronze: el gate no bloquea")

        print("\n3. Que test lo cazo")
        cazadores = tests_fallidos(a.proyecto)
        print(f"   tests en fallo: {', '.join(cazadores) or 'ninguno'}")
        if TEST_ESPERADO not in cazadores:
            fallos.append(f"se esperaba que {TEST_ESPERADO} fallara, "
                          f"y fallaron: {cazadores or 'ninguno'}")

        print("\n4. Lo que importa: data/curated/ no debe haberse tocado")
        despues = huella(a.curated)
        print(f"   sha256 ahora {despues[:32]}")
        if despues != antes:
            fallos.append("data/curated/ cambio aunque el gate fallo: "
                          "Power BI habria cargado datos malos")

        con = duckdb.connect(str(a.proyecto.parent / "data" / "warehouse.duckdb"),
                             read_only=True)
        en_gold = con.execute(
            "select count(*) from main_gold.hecho_contratos "
            f"where id_contrato = '{ID_INYECTADO}'").fetchone()[0]
        en_curated = con.execute(
            f"select count(*) from read_parquet('{(a.curated / 'hecho_contratos.parquet').as_posix()}') "
            f"where id_contrato = '{ID_INYECTADO}'").fetchone()[0]
        con.close()
        print(f"   el registro malo esta en gold (DuckDB): {en_gold}  "
              "(es ahi donde el test puede verlo)")
        print(f"   el registro malo esta en curated (Power BI): {en_curated}  "
              "(esperado 0)")
        if en_curated:
            fallos.append("el registro corrupto llego a data/curated/")

    finally:
        print("\n5. Se restaura bronze y se reconstruye")
        restaurar(a.bronze, a.proyecto)
        final = huella(a.curated)
        print(f"   sha256 restaurado {final[:32]}"
              f"  {'igual al inicial' if final == antes else 'DISTINTO al inicial'}")

    print("\n" + "=" * 68)
    if fallos:
        print(f"EL GATE NO PROTEGE. {len(fallos)} problemas:")
        for f in fallos:
            print(f"  - {f}")
        sys.exit(1)
    print("EL GATE BLOQUEA")
    print("  - un registro corrupto hace fallar 'dbt build' con codigo distinto de 0")
    print(f"  - lo caza el test {TEST_ESPERADO}, escrito para eso")
    print("  - y data/curated/ queda intacto, asi que Power BI sigue leyendo")
    print("    el ultimo modelo bueno en vez de refrescar sobre datos malos")


if __name__ == "__main__":
    main()
