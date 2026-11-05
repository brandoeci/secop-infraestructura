"""Comprueba que DuckDB y BigQuery producen el MISMO modelo en estrella.

El objetivo de la migracion no es copiar a la nube el resultado ya
transformado: es que los mismos 10 modelos y los mismos 57 tests corran en los
dos motores. Esta prueba es la que convierte eso en una afirmacion verificable.

Compara tres cosas, de menos a mas exigente:

  1. Filas por tabla en las 8 tablas gold. Es la comprobacion debil: dos
     tablas pueden tener las mismas filas y distinto contenido.
  2. Suma de las CLAVES SUBROGADAS del hecho. Esta es la fuerte. Las claves
     salen de un hash MD5 de la clave natural, asi que si coinciden sobre
     67 mil filas es que el hash, el casteo y el orden de los campos se
     comportan igual en los dos motores. Si las claves coinciden, los joins
     coinciden, y el modelo es el mismo modelo.
  3. Suma de los importes, CON TOLERANCIA. Y aqui esta el hallazgo: no dan
     exactamente igual, y no es un error.

POR QUE LOS IMPORTES NO CUADRAN AL ULTIMO DIGITO
------------------------------------------------
`valor_contratado` es de coma flotante, y la suma de flotantes NO es
asociativa: (a+b)+c no es siempre a+(b+c). Cada motor reparte las 67.299
filas entre sus hilos en un orden distinto, asi que acumula en otro orden.

Medido el 2026-11-04: 6.546.904.372.188.142 contra 6.546.904.372.188.158.
Difieren en 16 sobre 6,5 cuatrillones, o sea 2,4e-15, que es justo la
precision de un flotante de 64 bits.

Lo hace visible el registro corrupto de la decision D5: ese contrato de 6,45
cuatrillones domina la suma y se come la precision de los otros 67.298.

La leccion de modelado: el dinero no deberia ser FLOAT64 sino DECIMAL, que es
exacto. Esta pendiente de decidir, y mientras tanto la prueba compara con
tolerancia relativa en vez de fingir una igualdad que no existe.

Uso:
  python etl/comparar_motores.py
  python etl/comparar_motores.py --proyecto otro-proyecto-gcp
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb
from google.cloud import bigquery

ALMACEN = Path(os.environ.get("SECOP_DUCKDB", "data/warehouse.duckdb"))
PROYECTO = os.environ.get("GCP_PROYECTO", "golden-capsule-446717-s8")
ESQUEMA = "main_gold"

TABLAS = ("hecho_contratos", "dim_entidad", "dim_proveedor", "dim_fecha",
          "dim_tipo_contrato", "dim_estado", "dim_modalidad", "dim_categoria")

CLAVES = ("entidad_key", "proveedor_key", "tipo_contrato_key", "estado_key",
          "modalidad_key", "categoria_key", "fecha_firma_key")

IMPORTES = ("valor_contratado", "valor_pagado", "valor_facturado",
            "valor_pendiente")

# 1e-12 deja pasar el error de acumulacion de 67 mil flotantes y sigue siendo
# mil veces mas estricto que cualquier diferencia que importara en el informe.
TOLERANCIA = 1e-12

FALLOS: list[str] = []


def comprobar(nombre: str, ok: bool, detalle: str) -> None:
    print(f"  {'OK   ' if ok else 'FALLA'} {nombre:28} {detalle}")
    if not ok:
        FALLOS.append(nombre)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--proyecto", default=PROYECTO, help="proyecto de GCP")
    p.add_argument("--almacen", type=Path, default=ALMACEN,
                   help="archivo DuckDB")
    a = p.parse_args()

    if not a.almacen.exists():
        raise SystemExit(f"No existe {a.almacen}. Corra el pipeline primero.")

    duck = duckdb.connect(str(a.almacen), read_only=True)
    bq = bigquery.Client(project=a.proyecto)

    def en_bq(sql: str) -> tuple:
        return list(bq.query(sql).result())[0]

    print(f"\nDuckDB   {a.almacen}")
    print(f"BigQuery {a.proyecto}.{ESQUEMA}\n")

    print("1. Filas por tabla")
    for t in TABLAS:
        d = duck.execute(f'select count(*) from {ESQUEMA}."{t}"').fetchone()[0]
        b = en_bq(f"select count(*) as n from `{a.proyecto}.{ESQUEMA}.{t}`")[0]
        comprobar(t, d == b, f"duckdb {d:,} | bigquery {b:,}")

    print("\n2. Suma de las claves subrogadas del hecho")
    for k in CLAVES:
        d = duck.execute(
            f"select sum({k}) from {ESQUEMA}.hecho_contratos").fetchone()[0]
        # CAST a NUMERIC: en BigQuery la suma de int64 se desborda.
        b = en_bq(f"select sum(cast({k} as numeric)) as s "
                  f"from `{a.proyecto}.{ESQUEMA}.hecho_contratos`")[0]
        comprobar(k, int(d) == int(b), f"{int(d)}")

    d = duck.execute("select count(distinct id_contrato) "
                     f"from {ESQUEMA}.hecho_contratos").fetchone()[0]
    b = en_bq(f"select count(distinct id_contrato) as n "
              f"from `{a.proyecto}.{ESQUEMA}.hecho_contratos`")[0]
    comprobar("id_contrato distintos", d == b, f"{d:,}")

    print("\n3. Suma de importes (con tolerancia: ver el modulo)")
    for m in IMPORTES:
        d = duck.execute(
            f"select sum({m}) from {ESQUEMA}.hecho_contratos").fetchone()[0]
        b = en_bq(f"select sum({m}) as s "
                  f"from `{a.proyecto}.{ESQUEMA}.hecho_contratos`")[0]
        d, b = float(d or 0), float(b or 0)
        rel = abs(d - b) / abs(d) if d else abs(b)
        comprobar(m, rel <= TOLERANCIA,
                  f"diferencia relativa {rel:.2e}  (duckdb {d:,.2f})")

    if FALLOS:
        print(f"\nLOS MOTORES NO COINCIDEN EN: {', '.join(FALLOS)}")
        sys.exit(1)
    print("\nDuckDB y BigQuery producen el mismo modelo en estrella.")


if __name__ == "__main__":
    main()
