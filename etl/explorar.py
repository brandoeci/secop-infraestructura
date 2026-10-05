"""Describe la estructura real de una muestra NDJSON de SECOP II.

Cruza la muestra con el esquema publicado en la API de metadatos para no
depender de lo que traiga una fila: Socrata omite los campos nulos en cada
fila, asi que una fila cualquiera muestra menos de 95 columnas.

Uso:
    python etl/explorar.py --muestra data/raw/muestra_10k.ndjson
    python etl/explorar.py --columna tipo_de_contrato --tope 40
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import requests

METADATOS = "https://www.datos.gov.co/api/views/jbjy-vk9h.json"


def esquema() -> list[dict]:
    """Las 95 columnas con su nombre de API, nombre visible y tipo."""
    cols = requests.get(METADATOS, timeout=120).json()["columns"]
    return [{"api": c["fieldName"], "visible": c["name"], "tipo": c["dataTypeName"]}
            for c in cols if not c["fieldName"].startswith(":")]


def leer(ruta: Path) -> list[dict]:
    with ruta.open(encoding="utf-8") as f:
        return [json.loads(linea) for linea in f if linea.strip()]


def es_nulo(fila: dict, campo: str) -> bool:
    """Ausente, None o cadena vacia cuentan como nulo.

    Socrata no envia la clave cuando el valor es nulo, asi que la ausencia
    es el caso mas comun.
    """
    v = fila.get(campo)
    return v is None or (isinstance(v, str) and not v.strip())


def informe_nulos(filas: list[dict], cols: list[dict]) -> list[dict]:
    n = len(filas)
    out = []
    for c in cols:
        nulos = sum(es_nulo(f, c["api"]) for f in filas)
        out.append({**c, "nulos": nulos, "pct_nulo": 100 * nulos / n if n else 0.0})
    return out


def distintos(filas: list[dict], campo: str) -> Counter:
    return Counter(f.get(campo) or "(nulo)" for f in filas)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--muestra", type=Path, default=Path("data/raw/muestra_10k.ndjson"))
    p.add_argument("--columna", default=None,
                   help="si se indica, lista los valores distintos de esa columna")
    p.add_argument("--tope", type=int, default=30,
                   help="cuantos valores distintos mostrar")
    a = p.parse_args()

    filas = leer(a.muestra)
    print(f"# muestra: {a.muestra}  ({len(filas):,} filas)\n")

    if a.columna:
        cuenta = distintos(filas, a.columna)
        print(f"valores distintos de {a.columna}: {len(cuenta)}\n")
        for valor, veces in cuenta.most_common(a.tope):
            print(f"{veces:7,}  {100*veces/len(filas):5.1f}%  {valor}")
        return

    cols = esquema()
    print(f"columnas en el esquema: {len(cols)}")
    tipos = Counter(c["tipo"] for c in cols)
    print("tipos:", dict(tipos), "\n")

    rep = informe_nulos(filas, cols)
    # Se imprime tambien el conteo crudo: un 99.96% redondeado a "100.0%"
    # haria creer que la columna esta vacia cuando no lo esta.
    print(f"{'#':>3} {'columna (API)':42} {'tipo':15} {'% nulo':>7} {'nulos':>8}")
    print("-" * 82)
    for i, c in enumerate(rep, 1):
        print(f"{i:3d} {c['api'][:42]:42} {c['tipo']:15} "
              f"{c['pct_nulo']:6.1f}% {c['nulos']:8,}")

    vacias = [c for c in rep if c["nulos"] == len(filas)]
    print(f"\ncolumnas totalmente vacias en la muestra: {len(vacias)}")
    for c in vacias:
        print("  -", c["api"])


if __name__ == "__main__":
    main()
