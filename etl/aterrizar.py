"""Aterriza el NDJSON crudo en la capa bronze, en Parquet.

Bronze es **fiel al origen**: no limpia, no normaliza, no interpreta. Cada
columna entra como texto, tal como la devolvio la API, y se le agregan dos
columnas de metadatos de ingesta. Toda la limpieza vive de bronze hacia
arriba, en los modelos de dbt.

Esa frontera no es decoracion. Si la limpieza estuviera aqui, un cambio de
criterio obligaria a volver a descargar los datos; con bronze intacto se
vuelve a correr `dbt build` y ya. Y cuando una cifra no cuadra, bronze es la
unica capa contra la que se puede comprobar que el origen decia eso.

Por que todo como texto: la API entrega JSON sin esquema y **omite las claves
nulas**, asi que una fila puede traer 20 campos y la siguiente 17. Si se deja
que pandas infiera, el tipo de una columna depende de que filas le tocaron en
el lote, que es justo la clase de fallo silencioso que esta capa evita. El
casteo se hace en silver, declarado y en un solo sitio.

Entrada : data/raw/obra.ndjson        (etl/descargar.py --universo obra)
Salida  : data/bronze/contratos.parquet
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from descargar import COLUMNAS_OBRA  # noqa: E402  la lista de columnas vive alli

CRUDO = Path("data/raw/obra.ndjson")
SALIDA = Path("data/bronze/contratos.parquet")


def leer_ndjson(ruta: Path) -> pd.DataFrame:
    """Lee el NDJSON a texto plano, con las 20 columnas siempre presentes.

    Se lee linea por linea y no con pd.read_json porque este fuerza una
    inferencia de tipos que aqui no queremos: un `valor_pagado` que venga
    vacio en las primeras mil filas no debe convertir la columna en nula.
    """
    filas = []
    with ruta.open(encoding="utf-8") as f:
        for n, linea in enumerate(f, 1):
            linea = linea.strip()
            if not linea:
                continue
            try:
                filas.append(json.loads(linea))
            except json.JSONDecodeError as e:
                raise SystemExit(f"{ruta}:{n} no es JSON valido: {e}") from e

    if not filas:
        raise SystemExit(f"{ruta} no tiene filas")

    df = pd.DataFrame(filas)

    # La API omite las claves nulas, asi que una columna que venga vacia en
    # todo el lote simplemente no existe. Se reindexan las 20 para que el
    # esquema de bronze sea estable corrida tras corrida.
    faltantes = [c for c in COLUMNAS_OBRA if c not in df.columns]
    if faltantes:
        print(f"aviso: el origen no trajo {len(faltantes)} columnas: "
              f"{', '.join(faltantes)}")
    df = df.reindex(columns=list(COLUMNAS_OBRA))

    # Columnas inesperadas: el origen cambio y conviene enterarse, no ignorarlo.
    sobrantes = [c for c in pd.DataFrame(filas).columns if c not in COLUMNAS_OBRA]
    if sobrantes:
        print(f"aviso: el origen trajo {len(sobrantes)} columnas no pedidas: "
              f"{', '.join(sobrantes[:10])}")

    return df.astype("string")


def aterrizar(crudo: Path, salida: Path) -> None:
    df = leer_ndjson(crudo)

    # Metadatos de ingesta. Van con guion bajo delante para que se distingan a
    # simple vista de las columnas que vienen del origen.
    # Truncada al segundo: el Parquet se escribe en timestamp('ms') y los
    # microsegundos de pd.Timestamp.now() no caben. La hora de ingesta no
    # necesita esa resolucion.
    df["_ingestado_en"] = (pd.Timestamp.now(tz=timezone.utc)
                           .tz_localize(None).floor("s"))
    df["_origen"] = crudo.name

    esquema = pa.schema(
        [(c, pa.string()) for c in COLUMNAS_OBRA]
        + [("_ingestado_en", pa.timestamp("ms")), ("_origen", pa.string())]
    )
    tabla = pa.Table.from_pandas(df, schema=esquema, preserve_index=False)

    salida.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(tabla, salida, compression="snappy", version="2.4")

    mb = salida.stat().st_size / 1e6
    print(f"bronze: {len(df):,} filas x {len(df.columns)} columnas "
          f"-> {salida} ({mb:.1f} MB)")

    nulos = df[list(COLUMNAS_OBRA)].isna().sum()
    vacias = nulos[nulos == len(df)]
    if len(vacias):
        print(f"aviso: {len(vacias)} columnas llegaron completamente vacias: "
              f"{', '.join(vacias.index)}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--crudo", type=Path, default=CRUDO)
    p.add_argument("--salida", type=Path, default=SALIDA)
    a = p.parse_args()
    if not a.crudo.exists():
        raise SystemExit(f"falta {a.crudo}. Corra primero:\n"
                         "  python etl/descargar.py --universo obra")
    aterrizar(a.crudo, a.salida)


if __name__ == "__main__":
    main()
