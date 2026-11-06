"""Comprueba que DuckDB y BigQuery producen el MISMO modelo en estrella.

El objetivo de la migracion no es copiar a la nube el resultado ya
transformado: es que los mismos 10 modelos y los mismos 57 tests corran en los
dos motores. Esta prueba es la que convierte eso en una afirmacion verificable.

Compara tres cosas, de menos a mas exigente:

  1. Filas por tabla en las 9 tablas gold. Es la comprobacion debil: dos
     tablas pueden tener las mismas filas y distinto contenido.
  2. Suma de las CLAVES SUBROGADAS del hecho. Esta es la fuerte. Las claves
     salen de un hash MD5 de la clave natural, asi que si coinciden sobre
     67 mil filas es que el hash, el casteo y el orden de los campos se
     comportan igual en los dos motores. Si las claves coinciden, los joins
     coinciden, y el modelo es el mismo modelo.
  3. Suma de los importes, EXACTA. Esta comprobacion nacio con tolerancia y
     la perdio: ahi esta la historia que vale la pena contar.

LOS IMPORTES NO CUADRABAN, Y DEJARON DE NO CUADRAR
--------------------------------------------------
Cuando los importes eran FLOAT64, las dos sumas no coincidian en el ultimo
digito y no era un error de nadie: la suma de flotantes NO es asociativa
-(a+b)+c no es siempre a+(b+c)- y cada motor reparte las 67.299 filas entre
sus hilos en un orden distinto, asi que acumula en otro orden.

Medido el 2026-11-04: 6.546.904.372.188.142 contra 6.546.904.372.188.158,
una diferencia relativa de 2,4e-15, justo la precision de un float de 64
bits. Y peor: el MISMO DuckDB daba numeros distintos entre dos corridas.

Lo causaba el registro corrupto de la decision D5. Ese contrato de 6,45
cuatrillones lleva el acumulado a un rango donde la distancia entre dos
float64 consecutivos es de un peso entero, asi que los centavos de los otros
67.298 contratos no caben. La suma exacta es 6.546.904.372.188.138,10 y la de
FLOAT64 daba ...134: cuatro pesos con diez, perdidos por un unico dato.

El 2026-11-06 los importes pasaron a decimal exacto -DECIMAL(38,2) en DuckDB,
NUMERIC en BigQuery, ver el macro tipo_dinero()- y la tolerancia se pudo
BORRAR. Ahora la comparacion exige igualdad, que es una afirmacion mucho mas
fuerte, y la hace en Decimal de Python para no reintroducir por la puerta de
atras el flotante que se acaba de quitar.

Uso:
  python etl/comparar_motores.py
  python etl/comparar_motores.py --proyecto otro-proyecto-gcp
"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

import duckdb
from google.cloud import bigquery

ALMACEN = Path(os.environ.get("SECOP_DUCKDB", "data/warehouse.duckdb"))
PROYECTO = os.environ.get("GCP_PROYECTO", "golden-capsule-446717-s8")
ESQUEMA = "main_gold"

TABLAS = ("hecho_contratos", "dim_entidad", "dim_proveedor", "dim_fecha",
          "dim_tipo_contrato", "dim_estado", "dim_modalidad", "dim_categoria",
          "dim_territorial_vial")

CLAVES = ("entidad_key", "proveedor_key", "tipo_contrato_key", "estado_key",
          "modalidad_key", "categoria_key", "territorial_key",
          "fecha_firma_key")

IMPORTES = ("valor_contratado", "valor_pagado", "valor_facturado",
            "valor_pendiente")

# Ya no hay tolerancia. Los importes son decimales exactos en los dos motores,
# asi que cualquier diferencia es un defecto y no ruido del tipo de dato.

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

    print("\n3. Suma de importes (igualdad exacta: ver el modulo)")
    for m in IMPORTES:
        d = duck.execute(
            f"select sum({m}) from {ESQUEMA}.hecho_contratos").fetchone()[0]
        b = en_bq(f"select sum({m}) as s "
                  f"from `{a.proyecto}.{ESQUEMA}.hecho_contratos`")[0]
        # Decimal, no float: pasar por float aqui volveria a introducir el
        # error de representacion que el cambio de tipo acaba de eliminar.
        d = Decimal(str(d if d is not None else 0))
        b = Decimal(str(b if b is not None else 0))
        comprobar(m, d == b,
                  f"{d:,}" if d == b else f"duckdb {d:,} vs bigquery {b:,}")

    if FALLOS:
        print(f"\nLOS MOTORES NO COINCIDEN EN: {', '.join(FALLOS)}")
        sys.exit(1)
    print("\nDuckDB y BigQuery producen el mismo modelo en estrella.")


if __name__ == "__main__":
    main()
