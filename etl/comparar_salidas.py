"""Compara el esquema en estrella de dbt contra el que escribio transformar.py.

Es la prueba de que migrar el star schema a dbt no cambio ni un dato. Mientras
no de cero diferencias, no se sustituye nada: el informe de Power BI ya esta
publicado y esta construido sobre esas cifras.

La comparacion **no es por clave subrogada**. Las claves cambiaron a proposito
(de posicionales a hash determinista), asi que compararlas daria diferencias en
todas las filas sin decir nada util. Lo que se compara es la clave natural y
los atributos: el hecho se desnormaliza por los dos lados hasta dejar el nombre
de la entidad, el del proveedor y el resto de atributos en claro, y entonces se
contrastan fila a fila.

Entradas:
  data/curated/*.parquet   la salida de etl/transformar.py (la referencia)
  data/warehouse.duckdb    la salida de dbt (main_gold.*)

Uso:
  python etl/comparar_salidas.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

CURATED = Path("data/curated")
ALMACEN = Path("data/warehouse.duckdb")

# Las columnas de cada dimension que se comparan, y la clave natural por la
# que se emparejan las dos versiones.
DIMENSIONES = {
    "dim_entidad": (
        ["nit_entidad", "nombre_entidad"],
        ["departamento", "ciudad", "orden", "contratos"],
    ),
    "dim_proveedor": (
        ["documento", "proveedor"],
        ["tiene_documento", "contratos"],
    ),
    "dim_tipo_contrato": (["tipo_contrato"], []),
    "dim_estado": (["estado"], []),
    "dim_modalidad": (["modalidad"], []),
    "dim_categoria": (["categoria"], []),
    "dim_fecha": (
        ["fecha_key"],
        ["fecha", "anio", "trimestre", "mes", "dia", "nombre_mes",
         "anio_mes", "anio_trimestre"],
    ),
}

# El hecho, desnormalizado: cada clave foranea se cambia por el atributo al
# que apunta, para poder comparar dos modelos con claves distintas.
HECHO_ATRIBUTOS = [
    "nit_entidad", "nombre_entidad", "proveedor", "tipo_contrato", "estado",
    "modalidad", "categoria",
]
HECHO_MEDIDAS = [
    "fecha_firma_key", "fecha_inicio_key", "fecha_fin_key",
    "valor_contratado", "valor_pagado", "valor_facturado", "valor_pendiente",
    "objeto_del_contrato", "valor_confiable", "veces_p99_modalidad",
    "pago_exigible", "pagado_excede", "fechas_coherentes", "duracion_dias",
]


def registrar_viejo(con: duckdb.DuckDBPyConnection, curated: Path) -> None:
    """Expone los Parquet de transformar.py como vistas viejo_*."""
    for p in sorted(curated.glob("*.parquet")):
        con.execute(
            f"create view viejo_{p.stem} as select * from read_parquet('{p.as_posix()}')")


def desnormalizar(prefijo: str) -> str:
    """SQL que deja el hecho con los atributos en claro en vez de las claves."""
    return f"""
        select
            h.id_contrato,
            e.nit_entidad, e.nombre_entidad,
            p.proveedor,
            t.tipo_contrato, s.estado, m.modalidad, c.categoria,
            {', '.join('h.' + x for x in HECHO_MEDIDAS)}
        from {prefijo}hecho_contratos h
        left join {prefijo}dim_entidad       e on e.entidad_key       = h.entidad_key
        left join {prefijo}dim_proveedor     p on p.proveedor_key     = h.proveedor_key
        left join {prefijo}dim_tipo_contrato t on t.tipo_contrato_key = h.tipo_contrato_key
        left join {prefijo}dim_estado        s on s.estado_key        = h.estado_key
        left join {prefijo}dim_modalidad     m on m.modalidad_key     = h.modalidad_key
        left join {prefijo}dim_categoria     c on c.categoria_key     = h.categoria_key
    """


def distintos(con, a: str, b: str, col: str) -> int:
    """Filas donde la columna difiere, tratando NULL = NULL como iguales."""
    return con.execute(f"""
        select count(*) from {a} x join {b} y using (id_contrato)
        where x.{col} is distinct from y.{col}
    """).fetchone()[0]


def comparar_hecho(con) -> list[str]:
    fallos = []
    con.execute(f"create view h_viejo as {desnormalizar('viejo_')}")
    con.execute(f"create view h_nuevo as {desnormalizar('almacen.main_gold.')}")

    nv = con.execute("select count(*) from h_viejo").fetchone()[0]
    nn = con.execute("select count(*) from h_nuevo").fetchone()[0]
    print(f"hecho_contratos        {nv:>8,} viejo   {nn:>8,} nuevo")
    if nv != nn:
        fallos.append(f"hecho_contratos: {nv:,} filas viejas contra {nn:,} nuevas")

    huerfanas = con.execute("""
        select
            (select count(*) from h_viejo v
              where not exists (select 1 from h_nuevo n where n.id_contrato = v.id_contrato)),
            (select count(*) from h_nuevo n
              where not exists (select 1 from h_viejo v where v.id_contrato = n.id_contrato))
    """).fetchone()
    if any(huerfanas):
        fallos.append(f"hecho_contratos: {huerfanas[0]} id solo en el viejo, "
                      f"{huerfanas[1]} solo en el nuevo")

    for col in HECHO_ATRIBUTOS + HECHO_MEDIDAS:
        d = distintos(con, "h_viejo", "h_nuevo", col)
        marca = "ok " if d == 0 else "DIF"
        print(f"  {marca} {col:24} {d:>8,}")
        if d:
            fallos.append(f"hecho_contratos.{col}: {d:,} filas distintas")
    return fallos


def comparar_dimension(con, tabla: str, clave: list[str], atributos: list[str]) -> list[str]:
    fallos = []
    cols = clave + atributos
    sel = ", ".join(cols)
    v, n = f"viejo_{tabla}", f"almacen.main_gold.{tabla}"

    nv = con.execute(f"select count(*) from {v}").fetchone()[0]
    nn = con.execute(f"select count(*) from {n}").fetchone()[0]
    print(f"{tabla:22} {nv:>8,} viejo   {nn:>8,} nuevo")
    if nv != nn:
        fallos.append(f"{tabla}: {nv:,} filas viejas contra {nn:,} nuevas")

    # Diferencia simetrica sobre el conjunto completo de atributos: si una
    # sola celda cambia, la fila aparece en uno de los dos lados.
    solo_viejo = con.execute(
        f"select count(*) from (select {sel} from {v} except select {sel} from {n})"
    ).fetchone()[0]
    solo_nuevo = con.execute(
        f"select count(*) from (select {sel} from {n} except select {sel} from {v})"
    ).fetchone()[0]

    marca = "ok " if not (solo_viejo or solo_nuevo) else "DIF"
    print(f"  {marca} filas solo en viejo {solo_viejo:>6,}   solo en nuevo {solo_nuevo:>6,}")
    if solo_viejo or solo_nuevo:
        fallos.append(f"{tabla}: {solo_viejo:,} filas solo en el viejo, "
                      f"{solo_nuevo:,} solo en el nuevo")
    return fallos


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--curated", type=Path, default=CURATED)
    p.add_argument("--almacen", type=Path, default=ALMACEN)
    a = p.parse_args()

    if not a.almacen.exists():
        raise SystemExit(f"falta {a.almacen}. Corra primero:\n"
                         "  cd transformaciones && dbt build --profiles-dir .")
    if not any(a.curated.glob("*.parquet")):
        raise SystemExit(f"no hay Parquet en {a.curated} contra los que comparar")

    # En memoria, con el almacen adjunto de solo lectura: las vistas de
    # comparacion no deben escribirse dentro del warehouse de dbt.
    con = duckdb.connect(":memory:")
    con.execute(f"attach '{a.almacen.as_posix()}' as almacen (read_only)")
    registrar_viejo(con, a.curated)

    print("=" * 62)
    print("transformar.py (viejo)  contra  dbt (nuevo)")
    print("=" * 62)

    fallos = comparar_hecho(con)
    print()
    for tabla, (clave, atributos) in DIMENSIONES.items():
        fallos += comparar_dimension(con, tabla, clave, atributos)

    print("=" * 62)
    if fallos:
        print(f"{len(fallos)} DIFERENCIAS:")
        for f in fallos:
            print(f"  - {f}")
        sys.exit(1)
    print("0 diferencias: dbt reproduce exactamente la salida de transformar.py")


if __name__ == "__main__":
    main()
