"""Exporta las tablas gold del almacen DuckDB a los Parquet que lee Power BI.

Este paso esta separado de `dbt build` a proposito, y ese es el control de
calidad bloqueante del proyecto:

    dbt build        construye y prueba. Si un test falla, termina en error.
    exportar.py      solo corre si lo anterior salio bien.

Como la exportacion es posterior, un modelo que no pasa los tests **nunca
llega a data/curated/**. Power BI se queda leyendo el ultimo modelo bueno en
vez de refrescar sobre datos malos. Un gate que avisa pero deja pasar no es un
gate; este deja el dato viejo, que es el comportamiento seguro.

Entrada : data/warehouse.duckdb   (main_gold.*)
Salida  : data/curated/*.parquet
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

import duckdb

ALMACEN = Path("data/warehouse.duckdb")
SALIDA = Path("data/curated")

# El orden es el del modelo semantico: el hecho primero, luego las
# dimensiones. No importa para la carga, pero hace el log legible.
TABLAS = [
    "hecho_contratos",
    "dim_entidad", "dim_proveedor", "dim_fecha",
    "dim_tipo_contrato", "dim_estado", "dim_modalidad", "dim_categoria",
]


def exportar(almacen: Path, salida: Path) -> None:
    con = duckdb.connect(str(almacen), read_only=True)

    existentes = {r[0] for r in con.execute(
        "select table_name from information_schema.tables "
        "where table_schema = 'main_gold'").fetchall()}
    faltan = [t for t in TABLAS if t not in existentes]
    if faltan:
        raise SystemExit(
            "faltan tablas en main_gold: " + ", ".join(faltan) +
            "\nCorra primero:  cd transformaciones && dbt build --profiles-dir .")

    salida.mkdir(parents=True, exist_ok=True)

    # Se escribe a un temporal y se mueve al final. Si la exportacion falla a
    # mitad de camino, data/curated/ no queda con unas tablas nuevas y otras
    # viejas, que es un modelo incoherente y el peor estado posible: Power BI
    # lo cargaria sin quejarse.
    with tempfile.TemporaryDirectory(dir=salida.parent) as tmp:
        tmp = Path(tmp)
        for t in TABLAS:
            destino = tmp / f"{t}.parquet"
            con.execute(
                f"copy (select * from main_gold.{t}) to '{destino.as_posix()}' "
                "(format parquet, compression snappy)")

        print(f"{'tabla':22} {'filas':>9} {'MB':>7}")
        print("-" * 42)
        for t in TABLAS:
            origen = tmp / f"{t}.parquet"
            n = con.execute(f"select count(*) from main_gold.{t}").fetchone()[0]
            print(f"{t:22} {n:>9,} {origen.stat().st_size / 1e6:>7.2f}")
            shutil.move(str(origen), str(salida / f"{t}.parquet"))

    print(f"\nescrito en {salida}/")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--almacen", type=Path, default=ALMACEN)
    p.add_argument("--salida", type=Path, default=SALIDA)
    a = p.parse_args()
    if not a.almacen.exists():
        raise SystemExit(f"falta {a.almacen}. Corra primero:\n"
                         "  cd transformaciones && dbt build --profiles-dir .")
    exportar(a.almacen, a.salida)


if __name__ == "__main__":
    main()
