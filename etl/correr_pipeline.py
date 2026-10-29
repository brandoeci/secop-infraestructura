"""Corre el pipeline completo, de la API a los Parquet que lee Power BI.

    python etl/correr_pipeline.py                 usa el crudo que ya hay
    python etl/correr_pipeline.py --descargar     baja primero de la API
    python etl/correr_pipeline.py --full-refresh  reconstruye gold de cero

El orden de los pasos no es una preferencia de estilo: **es el control de
calidad**.

    1. descargar      API -> data/raw/obra.ndjson          (opcional)
    2. aterrizar      -> data/bronze/contratos.parquet      bronze
    3. dbt build      silver y gold, y 67 tests             el gate
    4. registrar      -> auditoria_corridas.parquet         siempre, pase o falle
    5. exportar       gold -> data/curated/*.parquet        solo si 3 fue bien

Si el paso 3 falla, el 5 no corre y data/curated/ se queda como estaba: Power
BI sigue leyendo el ultimo modelo bueno en lugar de refrescar sobre datos
malos. El paso 4 corre igual, porque una corrida que fallo es la que mas
interesa tener registrada.

Que esto se cumple no se afirma, se prueba:
    python etl/probar_gate.py            el gate bloquea de verdad
    python etl/probar_idempotencia.py    correrlo dos veces no cambia nada
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PROYECTO = RAIZ / "transformaciones"


def paso(numero: int, titulo: str) -> None:
    # flush antes de cada subproceso: si no, lo que imprime el hijo sale antes
    # que el encabezado del padre y el log queda ilegible.
    print(f"\n{'=' * 66}\n{numero}. {titulo}\n{'=' * 66}", flush=True)


def correr(cmd: list[str], cwd: Path) -> int:
    nombre = " ".join(Path(c).name if c.endswith((".exe", ".py")) else c
                      for c in cmd)
    print(f"$ {nombre}", flush=True)
    r = subprocess.run(cmd, cwd=cwd)
    sys.stdout.flush()
    return r.returncode


def python(script: str, *args: str) -> int:
    return correr([sys.executable, str(RAIZ / "etl" / script), *args], RAIZ)


def dbt(*args: str) -> int:
    exe = Path(sys.executable).parent / "dbt.exe"
    if not exe.exists():
        exe = Path(sys.executable).parent / "dbt"
    return correr([str(exe), "build", "--profiles-dir", ".", *args], PROYECTO)


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--descargar", action="store_true",
                   help="baja el universo de la API antes de transformar")
    p.add_argument("--desde", metavar="AAAA-MM-DD",
                   help="con --descargar, solo los contratos firmados desde esa fecha")
    p.add_argument("--full-refresh", action="store_true",
                   help="reconstruye gold de cero en vez de hacer MERGE")
    a = p.parse_args()

    inicio = time.time()
    n = 0

    if a.descargar:
        n += 1
        paso(n, "Descarga desde la API de Socrata")
        args = ["--universo", "obra"]
        if a.desde:
            args += ["--desde", a.desde]
        if python("descargar.py", *args):
            raise SystemExit("la descarga fallo")

    n += 1
    paso(n, "Aterrizaje en bronze")
    if python("aterrizar.py"):
        raise SystemExit("el aterrizaje fallo")

    n += 1
    paso(n, "Transformacion y control de calidad (dbt)")
    codigo_gate = dbt(*(["--full-refresh"] if a.full_refresh else []))

    n += 1
    paso(n, "Registro de la corrida en la bitacora")
    # Corre pase o falle: una corrida que fallo es la que mas interesa.
    python("registrar_corrida.py")

    if codigo_gate != 0:
        print(f"\n{'=' * 66}")
        print("EL CONTROL DE CALIDAD FALLO")
        print("=" * 66)
        print("No se exporta nada. data/curated/ se queda como estaba y Power BI")
        print("sigue leyendo el ultimo modelo bueno.")
        print("\nQue revisar:")
        print("  transformaciones/target/run_results.json   que test fallo y con que")
        print("  docs/calidad-datos.md                     los umbrales y su por que")
        sys.exit(codigo_gate)

    n += 1
    paso(n, "Exportacion a data/curated/ para Power BI")
    if python("exportar.py"):
        raise SystemExit("la exportacion fallo")

    print(f"\n{'=' * 66}")
    print(f"PIPELINE COMPLETO en {time.time() - inicio:.1f} s")
    print("=" * 66)
    print("data/curated/ actualizado. En Power BI: Inicio -> Actualizar.")


if __name__ == "__main__":
    main()
