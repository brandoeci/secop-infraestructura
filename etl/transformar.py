"""Transforma el NDJSON crudo de obra en un esquema en estrella en Parquet.

Pandas y no Spark, a proposito: son 66.875 filas. Spark se justifica por los
~26 GB del dataset completo, no por este recorte, y una herramienta puesta sin
motivo se nota. Si algun dia hay que barrer los 6,1 millones de filas crudas,
ese paso si pide Spark.

Entrada : data/raw/obra.ndjson      (etl/descargar.py --universo obra)
Salida  : data/curated/*.parquet    (lo que lee Power BI en modo Import)

Decisiones de modelado, explicadas donde se toman. El resumen esta en
docs/decisiones.md y los problemas de origen en docs/calidad-datos.md.
"""

from __future__ import annotations

import argparse
import unicodedata
from pathlib import Path

import pandas as pd

CRUDO = Path("data/raw/obra.ndjson")
SALIDA = Path("data/curated")

# El registro diagnosticado como error de digitacion en docs/calidad-datos.md.
# No se borra: se marca. Ver la nota en marcar_calidad().
CONTRATO_CORRUPTO = "CO1.PCCNTR.5972834"

FECHAS = ["fecha_de_firma", "fecha_de_inicio_del_contrato", "fecha_de_fin_del_contrato"]
MEDIDAS = ["valor_del_contrato", "valor_pagado", "valor_facturado",
           "valor_pendiente_de_pago"]

# Estados en los que el pago ya deberia estar reportado, asi que un cero en
# valor_pagado es un vacio de reporte y no un contrato sin ejecutar todavia.
ESTADOS_PAGO_EXIGIBLE = ("Cerrado", "Terminado")

# Ventana de anios plausible para una fecha de este dataset.
#
# SECOP II arranca en 2015 y hay concesiones de obra que terminan legitimamente
# en 2055 (94 contratos acaban despues de 2035: son concesiones a 20 y 30 anios,
# no errores). Pero un contrato trae fecha de fin en el anio 0206, y esa sola
# fila estiraba la tabla de fechas a 675.699 dias, unos 1.850 anios, dejandola
# inservible. Las fechas fuera de la ventana no entran a dim_fecha: la fila del
# hecho queda con la clave en nulo y marcada, que es mas honesto que inventar
# una fecha o que borrar el contrato.
ANIO_MIN, ANIO_MAX = 2015, 2060


# --------------------------------------------------------------------------
# limpieza
# --------------------------------------------------------------------------

def normalizar_texto(s: pd.Series) -> pd.Series:
    """Quita espacios sobrantes y saltos de linea dentro del propio campo."""
    return (s.astype("string")
             .str.replace(r"\s+", " ", regex=True)
             .str.strip())


def capitalizar_estado(s: pd.Series) -> pd.Series:
    """Unifica la capitalizacion inconsistente de la fuente.

    SECOP II entrega 'terminado' y 'cedido' en minuscula mientras el resto de
    los estados van capitalizados. Sin esto la dimension muestra valores que
    parecen distintos y no lo son.

    Solo toca la primera letra: no fusiona valores. 'Contratacion directa' y
    'Contratacion Directa (con ofertas)' son modalidades legalmente distintas
    y tienen que seguir separadas.
    """
    s = normalizar_texto(s)
    return s.str.slice(0, 1).str.upper() + s.str.slice(1)


def sin_tildes(s: pd.Series) -> pd.Series:
    """Version comparable de un texto, para agrupar grafias del mismo nombre."""
    return (s.fillna("")
             .map(lambda x: unicodedata.normalize("NFKD", x)
                  .encode("ascii", "ignore").decode())
             .str.upper().str.replace(r"[^A-Z0-9 ]", "", regex=True)
             .str.replace(r"\s+", " ", regex=True).str.strip())


def documento_invalido(s: pd.Series) -> pd.Series:
    """Marca los centinelas que la fuente usa en documento_proveedor.

    El 6,1 % de los contratos trae 'No Definido', '0', '000000000' y similares,
    casi siempre consorcios y uniones temporales sin NIT propio en el campo.
    Son 3.889 proveedores distintos: usar ese campo como clave los colapsaria
    todos en una sola fila de la dimension.
    """
    t = s.astype("string").str.strip()
    no_numerico = ~t.str.fullmatch(r"\d+", na=True)
    casi_cero = t.str.replace(r"^0+", "", regex=True).str.len().fillna(0) < 5
    return (no_numerico | casi_cero).fillna(True)


def cargar(ruta: Path) -> pd.DataFrame:
    df = pd.read_json(ruta, lines=True, dtype=False)

    for c in FECHAS:
        df[c] = pd.to_datetime(df[c], errors="coerce").dt.normalize()
    for c in MEDIDAS:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    for c in ["nombre_entidad", "departamento", "ciudad", "orden",
              "proveedor_adjudicado", "objeto_del_contrato",
              "codigo_de_categoria_principal", "id_contrato",
              "nit_entidad", "documento_proveedor"]:
        df[c] = normalizar_texto(df[c])
    for c in ["estado_contrato", "tipo_de_contrato", "modalidad_de_contratacion"]:
        df[c] = capitalizar_estado(df[c])

    return df


# --------------------------------------------------------------------------
# dimensiones
# --------------------------------------------------------------------------

def moda(s: pd.Series):
    """El valor mas frecuente del grupo; el primero si hay empate."""
    m = s.mode()
    return m.iloc[0] if len(m) else pd.NA


def dim_entidad(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Grano: la unidad que contrata, no la entidad juridica.

    Un mismo NIT agrupa varias unidades: el NIT 899999034 es el SENA y trae 81
    nombres distintos (SENA Regional Atlantico, Regional Caldas...). El informe
    pregunta *quien contrata*, y esas regionales contratan por separado, asi
    que el grano es (nit, nombre): 3.057 unidades sobre 2.692 NIT.

    Se conserva nit_entidad como atributo para poder agregar a entidad
    juridica cuando haga falta.

    departamento y ciudad varian dentro de la unidad en 6 y 5 casos de 3.057.
    Se resuelve con el valor mas frecuente de la unidad: una dimension no puede
    tener dos filas para la misma unidad solo porque un contrato trae la ciudad
    mal diligenciada.
    """
    g = (df.groupby(["nit_entidad", "nombre_entidad"], dropna=False)
           .agg(departamento=("departamento", moda),
                ciudad=("ciudad", moda),
                orden=("orden", moda),
                contratos=("id_contrato", "size"))
           .reset_index())
    g.insert(0, "entidad_key", range(1, len(g) + 1))

    llave = df.set_index(["nit_entidad", "nombre_entidad"]).index
    mapa = g.set_index(["nit_entidad", "nombre_entidad"])["entidad_key"]
    return g, pd.Series(mapa.reindex(llave).to_numpy(), index=df.index)


def dim_proveedor(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Grano: el proveedor. La clave depende de si el documento sirve.

    - Documento valido (93,9 %): la clave es el documento. 206 proveedores
      traen el nombre con varias grafias; se toma la mas frecuente como
      nombre canonico en lugar de partirlos en varias filas.
    - Documento centinela (6,1 %): el nombre es la unica identidad disponible,
      asi que la clave se construye sobre el nombre normalizado y la fila
      queda marcada con tiene_documento = False.

    Partir por (documento, nombre) habria sido mas simple pero duplicaria al
    proveedor que aparece escrito de dos maneras, que es justo lo que una
    dimension debe evitar.
    """
    d = df[["documento_proveedor", "proveedor_adjudicado"]].copy()
    d["malo"] = documento_invalido(d.documento_proveedor)
    d["ident"] = d.documento_proveedor.where(
        ~d.malo, "NOMBRE:" + sin_tildes(d.proveedor_adjudicado))

    g = (d.groupby("ident", dropna=False)
          .agg(proveedor=("proveedor_adjudicado", moda),
               tiene_documento=("malo", lambda s: not s.all()),
               contratos=("ident", "size"))
          .reset_index())
    g["documento"] = g.ident.where(g.tiene_documento, pd.NA)
    g.insert(0, "proveedor_key", range(1, len(g) + 1))
    g = g[["proveedor_key", "documento", "proveedor", "tiene_documento",
           "contratos", "ident"]]

    mapa = g.set_index("ident")["proveedor_key"]
    return g.drop(columns="ident"), d.ident.map(mapa)


def dim_simple(df: pd.DataFrame, col: str, nombre: str) -> tuple[pd.DataFrame, pd.Series]:
    """Dimension de un solo atributo: tipo, estado, modalidad, categoria."""
    vals = sorted(df[col].dropna().unique())
    g = pd.DataFrame({f"{nombre}_key": range(1, len(vals) + 1), nombre: vals})
    return g, df[col].map(g.set_index(nombre)[f"{nombre}_key"])


def dim_fecha(df: pd.DataFrame) -> pd.DataFrame:
    """Tabla de fechas comun y continua, para marcarla como tabla de fechas.

    Tiene que cubrir sin huecos el rango de las tres fechas del hecho, y
    empezar en un 1 de enero y terminar en un 31 de diciembre: si no, la
    inteligencia de tiempo (SAMEPERIODLASTYEAR y compania) da resultados
    parciales en los anios de los extremos.
    """
    todas = pd.concat([df[c] for c in FECHAS]).dropna()
    todas = todas[todas.dt.year.between(ANIO_MIN, ANIO_MAX)]
    ini = pd.Timestamp(year=todas.min().year, month=1, day=1)
    fin = pd.Timestamp(year=todas.max().year, month=12, day=31)
    f = pd.DataFrame({"fecha": pd.date_range(ini, fin, freq="D")})

    MES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
           "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    f["fecha_key"] = f.fecha.dt.strftime("%Y%m%d").astype("int32")
    f["anio"] = f.fecha.dt.year.astype("int16")
    f["trimestre"] = f.fecha.dt.quarter.astype("int8")
    f["mes"] = f.fecha.dt.month.astype("int8")
    f["dia"] = f.fecha.dt.day.astype("int8")
    f["nombre_mes"] = f.mes.map(lambda m: MES[m - 1])
    f["anio_mes"] = f.fecha.dt.strftime("%Y-%m")
    f["anio_trimestre"] = f.anio.astype(str) + "-T" + f.trimestre.astype(str)
    return f[["fecha_key", "fecha", "anio", "trimestre", "mes", "dia",
              "nombre_mes", "anio_mes", "anio_trimestre"]]


def fecha_key(s: pd.Series) -> pd.Series:
    """Clave yyyymmdd; nula si la fecha cae fuera de la ventana plausible."""
    dentro = s.dt.year.between(ANIO_MIN, ANIO_MAX)
    return pd.to_numeric(s.where(dentro).dt.strftime("%Y%m%d"),
                         errors="coerce").astype("Int32")


# --------------------------------------------------------------------------
# calidad en el hecho
# --------------------------------------------------------------------------

def marcar_calidad(h: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """Anade banderas de calidad en vez de borrar filas.

    Marcar y no borrar es deliberado: una fila que desaparece del modelo no
    deja rastro de que existio, y el vacio de reporte es parte de lo que el
    informe describe.

    - valor_confiable: False en el registro ya diagnosticado como error de
      digitacion. Las medidas de dinero deben filtrar por esta bandera.
    - veces_p99_modalidad: cuantas veces el valor supera el p99 de su propia
      modalidad de contratacion (decision D3). Se compara contra la modalidad
      y no contra el universo porque la modalidad refleja un rango de cuantia
      definido por ley: un atipico en minima cuantia no es lo mismo que uno
      en licitacion publica.
    - pago_exigible: True solo donde el contrato ya termino, asi que el
      % ejecutado se puede medir sin que los contratos aun sin pagar lo
      hundan artificialmente.
    - pagado_excede: el pagado supera lo contratado, que dejaria el
      % ejecutado por encima del 100 %.
    """
    h["valor_confiable"] = df.id_contrato != CONTRATO_CORRUPTO

    p99 = (df.loc[h.valor_confiable]
             .groupby("modalidad_de_contratacion")["valor_del_contrato"]
             .quantile(0.99))
    ref = df.modalidad_de_contratacion.map(p99)
    h["veces_p99_modalidad"] = (df.valor_del_contrato / ref).where(ref > 0).round(2)

    h["pago_exigible"] = df.estado_contrato.isin(ESTADOS_PAGO_EXIGIBLE)
    h["pagado_excede"] = df.valor_pagado > df.valor_del_contrato

    # Un contrato no puede terminar antes de firmarse. Son 200 casos, mas uno
    # con la fecha de fin en el anio 0206. La duracion se deja nula cuando
    # saldria negativa: un numero negativo de dias no es una duracion corta,
    # es un dato malo, y promediarlo contaminaria la medida.
    h["fechas_coherentes"] = (
        (df.fecha_de_fin_del_contrato >= df.fecha_de_firma)
        & df.fecha_de_fin_del_contrato.dt.year.between(ANIO_MIN, ANIO_MAX)
    ).fillna(False)

    dias = (df.fecha_de_fin_del_contrato - df.fecha_de_inicio_del_contrato).dt.days
    h["duracion_dias"] = dias.where(dias >= 0).astype("Int32")
    return h


# --------------------------------------------------------------------------
# orquestacion
# --------------------------------------------------------------------------

def construir(crudo: Path, salida: Path) -> None:
    df = cargar(crudo)
    print(f"crudo: {len(df):,} contratos\n")

    ent, ent_k = dim_entidad(df)
    pro, pro_k = dim_proveedor(df)
    tip, tip_k = dim_simple(df, "tipo_de_contrato", "tipo_contrato")
    est, est_k = dim_simple(df, "estado_contrato", "estado")
    mod, mod_k = dim_simple(df, "modalidad_de_contratacion", "modalidad")
    cat, cat_k = dim_simple(df, "codigo_de_categoria_principal", "categoria")
    fec = dim_fecha(df)

    h = pd.DataFrame({
        "id_contrato": df.id_contrato,
        "entidad_key": ent_k.astype("int32"),
        "proveedor_key": pro_k.astype("int32"),
        "tipo_contrato_key": tip_k.astype("int16"),
        "estado_key": est_k.astype("int16"),
        "modalidad_key": mod_k.astype("int16"),
        "categoria_key": cat_k.astype("int32"),
        "fecha_firma_key": fecha_key(df.fecha_de_firma),
        "fecha_inicio_key": fecha_key(df.fecha_de_inicio_del_contrato),
        "fecha_fin_key": fecha_key(df.fecha_de_fin_del_contrato),
        "valor_contratado": df.valor_del_contrato,
        "valor_pagado": df.valor_pagado,
        "valor_facturado": df.valor_facturado,
        "valor_pendiente": df.valor_pendiente_de_pago,
        # Texto largo y casi unico por contrato: atributo degenerado en el
        # hecho, no una dimension con una fila por hecho.
        "objeto_del_contrato": df.objeto_del_contrato,
    })
    h = marcar_calidad(h, df)

    tablas = {"hecho_contratos": h, "dim_entidad": ent, "dim_proveedor": pro,
              "dim_fecha": fec, "dim_tipo_contrato": tip, "dim_estado": est,
              "dim_modalidad": mod, "dim_categoria": cat}

    validar(h, tablas, fec)

    salida.mkdir(parents=True, exist_ok=True)
    print(f"{'tabla':22} {'filas':>9} {'MB':>7}")
    print("-" * 42)
    for nombre, t in tablas.items():
        ruta = salida / f"{nombre}.parquet"
        t.to_parquet(ruta, index=False, compression="snappy")
        print(f"{nombre:22} {len(t):>9,} {ruta.stat().st_size/1e6:>7.2f}")
    print(f"\nescrito en {salida}/")


def validar(h: pd.DataFrame, tablas: dict, fec: pd.DataFrame) -> None:
    """Falla si el modelo no es cargable. Mejor romper aqui que en Power BI."""
    problemas = []

    if h.id_contrato.duplicated().any():
        problemas.append(f"{h.id_contrato.duplicated().sum()} id_contrato duplicados")

    for col, dim, key in [("entidad_key", "dim_entidad", "entidad_key"),
                          ("proveedor_key", "dim_proveedor", "proveedor_key"),
                          ("tipo_contrato_key", "dim_tipo_contrato", "tipo_contrato_key"),
                          ("estado_key", "dim_estado", "estado_key"),
                          ("modalidad_key", "dim_modalidad", "modalidad_key"),
                          ("categoria_key", "dim_categoria", "categoria_key")]:
        if h[col].isna().any():
            problemas.append(f"{h[col].isna().sum()} filas sin {col}")
        huerfanas = ~h[col].dropna().isin(tablas[dim][key])
        if huerfanas.any():
            problemas.append(f"{huerfanas.sum()} {col} sin fila en {dim}")

    validas = set(fec.fecha_key)
    for col in ["fecha_firma_key", "fecha_inicio_key", "fecha_fin_key"]:
        fuera = ~h[col].dropna().isin(validas)
        if fuera.any():
            problemas.append(f"{fuera.sum()} {col} fuera de dim_fecha")

    for d in ["dim_entidad", "dim_proveedor"]:
        k = f"{d.removeprefix('dim_')}_key"
        if tablas[d][k].duplicated().any():
            problemas.append(f"{d} tiene {k} duplicada")

    if problemas:
        raise SystemExit("el modelo no es valido:\n  - " + "\n  - ".join(problemas))
    print("validacion: integridad referencial correcta, sin huerfanas ni claves "
          "duplicadas\n")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--crudo", type=Path, default=CRUDO)
    p.add_argument("--salida", type=Path, default=SALIDA)
    a = p.parse_args()
    if not a.crudo.exists():
        raise SystemExit(f"falta {a.crudo}. Corra primero:\n"
                         "  python etl/descargar.py --universo obra")
    construir(a.crudo, a.salida)


if __name__ == "__main__":
    main()
