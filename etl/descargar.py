"""Descarga paginada del dataset SECOP II - Contratos Electronicos (Socrata).

Solo requests: para una muestra de miles de filas Spark es sobreingenieria.
Spark entra cuando el volumen lo exija, no de adorno.

La salida es NDJSON (un objeto JSON por linea) en data/raw/. Ese formato es el
que permite reanudar: cada linea equivale a una fila de la API, asi que el
numero de lineas ya escritas es el proximo $offset.

Uso tipico:
    # muestra de 10.000 filas con las 95 columnas
    python etl/descargar.py --filas 10000 --salida data/raw/muestra_10k.ndjson

    # se corto la descarga? el mismo comando continua donde quedo
    python etl/descargar.py --filas 10000 --salida data/raw/muestra_10k.ndjson

    # contar filas que cumplen un filtro, sin descargar nada
    python etl/descargar.py --contar --where "fecha_de_firma >= '2023-10-05'"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests

URL = "https://www.datos.gov.co/resource/jbjy-vk9h.json"

# Socrata no garantiza un orden estable entre peticiones. Sin $order, paginar
# con $offset puede repetir o saltarse filas. :id es el identificador interno
# de fila, unico y estable, asi que ordenar por el hace la paginacion
# determinista y la descarga reanudable.
ORDEN = ":id"

PAGINA_POR_DEFECTO = 1000
MAX_INTENTOS = 5
TIEMPO_ESPERA = 120


def sesion() -> requests.Session:
    """Sesion HTTP reutilizada: una sola conexion TCP para todas las paginas."""
    s = requests.Session()
    s.headers["User-Agent"] = "secop-infraestructura/0.1 (proyecto de portafolio)"
    # El app token es opcional: solo sube el limite de peticiones por hora.
    token = os.environ.get("SOCRATA_APP_TOKEN")
    if token:
        s.headers["X-App-Token"] = token
    return s


def pedir(s: requests.Session, params: dict) -> list[dict]:
    """GET con reintentos y espera exponencial ante fallos transitorios."""
    for intento in range(1, MAX_INTENTOS + 1):
        try:
            r = s.get(URL, params=params, timeout=TIEMPO_ESPERA)
            if r.status_code == 200:
                return r.json()
            # 429 = demasiadas peticiones, 5xx = problema del servidor: se
            # reintentan. Un 400 es error de la consulta y repetirlo no sirve.
            if r.status_code not in (429, 500, 502, 503, 504):
                raise SystemExit(f"La API respondio {r.status_code}: {r.text[:300]}")
            motivo = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            motivo = type(e).__name__

        if intento == MAX_INTENTOS:
            raise SystemExit(
                f"Fallaron {MAX_INTENTOS} intentos ({motivo}). "
                "Vuelva a correr el comando: la descarga se reanuda."
            )
        espera = 2**intento
        print(f"  {motivo}; reintento {intento}/{MAX_INTENTOS - 1} en {espera}s",
              file=sys.stderr)
        time.sleep(espera)
    raise AssertionError("inalcanzable")


def contar(s: requests.Session, where: str | None) -> int:
    """Cuenta filas en el servidor. No descarga datos."""
    params = {"$select": "count(1) as total"}
    if where:
        params["$where"] = where
    return int(pedir(s, params)[0]["total"])


def huella(select: str | None, where: str | None) -> str:
    """Identifica la consulta. Si cambia, reanudar seria mezclar dos descargas."""
    crudo = json.dumps({"select": select, "where": where, "orden": ORDEN},
                       sort_keys=True)
    return hashlib.sha256(crudo.encode()).hexdigest()[:12]


def lineas_validas(ruta: Path) -> int:
    """Cuenta las lineas JSON completas y recorta una ultima linea truncada.

    Si el proceso murio a mitad de escritura, la ultima linea puede quedar
    partida. Se recorta el archivo hasta la ultima linea valida para que
    reanudar no deje datos corruptos.
    """
    if not ruta.exists():
        return 0
    completas = 0
    bytes_validos = 0
    with ruta.open("rb") as f:
        for linea in f:
            if not linea.endswith(b"\n"):
                break  # linea truncada: no se cuenta ni se conserva
            try:
                json.loads(linea)
            except json.JSONDecodeError:
                break
            completas += 1
            bytes_validos += len(linea)
    if bytes_validos != ruta.stat().st_size:
        print(f"  se recorta una linea incompleta al final de {ruta.name}",
              file=sys.stderr)
        with ruta.open("r+b") as f:
            f.truncate(bytes_validos)
    return completas


def descargar(objetivo: int, pagina: int, select: str | None, where: str | None,
              salida: Path, reiniciar: bool) -> None:
    salida.parent.mkdir(parents=True, exist_ok=True)
    estado_ruta = salida.with_suffix(salida.suffix + ".estado.json")
    actual = huella(select, where)

    if reiniciar:
        salida.unlink(missing_ok=True)
        estado_ruta.unlink(missing_ok=True)

    if estado_ruta.exists():
        estado = json.loads(estado_ruta.read_text(encoding="utf-8"))
        if estado.get("huella") != actual:
            raise SystemExit(
                f"{salida.name} se descargo con otra consulta (select/where "
                "distintos). Use otro --salida, o --reiniciar para empezar de cero."
            )

    # El archivo manda, no el estado: si el estado se perdio o quedo desfasado,
    # el numero de lineas ya descargadas es la verdad.
    ya = lineas_validas(salida)
    s = sesion()

    disponibles = contar(s, where)
    total = min(objetivo, disponibles) if objetivo else disponibles
    print(f"filas que cumplen el filtro en la API: {disponibles:,}")
    print(f"a descargar: {total:,} | ya en disco: {ya:,}")

    if ya >= total:
        print("nada que hacer: la descarga ya esta completa.")
        return

    with salida.open("a", encoding="utf-8") as f:
        while ya < total:
            limite = min(pagina, total - ya)
            params = {"$limit": limite, "$offset": ya, "$order": ORDEN}
            if select:
                params["$select"] = select
            if where:
                params["$where"] = where

            filas = pedir(s, params)
            if not filas:
                print("la API no devolvio mas filas; se detiene aqui.")
                break

            for fila in filas:
                f.write(json.dumps(fila, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())  # el progreso debe sobrevivir a un corte
            ya += len(filas)

            estado_ruta.write_text(json.dumps({
                "huella": actual, "filas": ya, "objetivo": total,
                "select": select, "where": where, "orden": ORDEN,
                "url": URL, "pagina": pagina,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  {ya:,}/{total:,}")

    print(f"listo: {ya:,} filas en {salida}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--filas", type=int, default=10000,
                   help="cuantas filas descargar; 0 = todas las que cumplan el filtro")
    p.add_argument("--pagina", type=int, default=PAGINA_POR_DEFECTO,
                   help=f"filas por peticion (por defecto {PAGINA_POR_DEFECTO})")
    p.add_argument("--select", default=None,
                   help="$select de Socrata; omitirlo trae las 95 columnas")
    p.add_argument("--where", default=None, help="$where de Socrata")
    p.add_argument("--salida", type=Path,
                   default=Path("data/raw/muestra_10k.ndjson"))
    p.add_argument("--reiniciar", action="store_true",
                   help="borra lo descargado y empieza de cero")
    p.add_argument("--contar", action="store_true",
                   help="solo cuenta filas en el servidor y sale")
    a = p.parse_args()

    if a.contar:
        print(f"{contar(sesion(), a.where):,}")
        return
    descargar(a.filas, a.pagina, a.select, a.where, a.salida, a.reiniciar)


if __name__ == "__main__":
    main()
