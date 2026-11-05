"""Prueba que la descarga no se reanuda cuando el origen se movio.

El 2026-11-02 la corrida programada fallo: el test de unicidad encontro 414
`id_contrato` repetidos en bronze. La causa no estaba en dbt.

`descargar.py` pagina con `$offset` y reanuda usando el numero de lineas ya
escritas como proximo offset. Eso es correcto solo si el conjunto de
resultados no cambia entre corridas, y el de SECOP II cambia: se insertan y
se borran filas. Cuando entran filas antes del final del orden `:id`, todas
las que venian despues suben de posicion, y pedir "desde la fila N" devuelve
filas que ya estaban en disco.

La huella no podia detectarlo porque identifica la CONSULTA (select, where,
orden), no el conjunto de resultados. El arreglo guarda tambien el conteo del
origen con el que se calcularon los offset.

Esta prueba no toca la red: sustituye `pedir` por un universo en memoria.

  1. Control negativo    el origen no se movio -> reanuda y completa bien.
  2. Control POSITIVO    se falsea el conteo guardado para que la deteccion
                         no dispare, y se comprueba que entonces SI aparecen
                         duplicados. Sin este paso la prueba no demuestra
                         nada: si el escenario no reprodujera el fallo, el
                         paso 3 pasaria por la razon equivocada.
  3. El arreglo          mismo escenario con el conteo real -> detecta el
                         movimiento, baja de cero y queda sin duplicados.

Uso:
  python etl/probar_reanudacion.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import descargar as D  # noqa: E402

FALLOS: list[str] = []


def fila(n: int) -> dict:
    return {"id_contrato": f"C{n:05d}", "valor_del_contrato": str(n * 1000)}


# El universo inicial son los pares: deja huecos donde luego entran filas
# nuevas EN MEDIO del orden, que es lo que rompe la paginacion por posicion.
V1 = [fila(n) for n in range(0, 200, 2)]                      # 100 filas
# Nueve filas nuevas que ordenan al principio, no al final.
V2 = sorted(V1 + [fila(n) for n in range(1, 18, 2)],          # 109 filas
            key=lambda f: f["id_contrato"])


class Api:
    """Sirve un universo en memoria con la semantica de $offset/$limit."""

    def __init__(self, filas: list[dict]) -> None:
        self.filas = filas

    def pedir(self, _s, params: dict) -> list[dict]:
        if str(params.get("$select", "")).startswith("count("):
            return [{"total": str(len(self.filas))}]
        ini = int(params["$offset"])
        return self.filas[ini:ini + int(params["$limit"])]


def montar(universo: list[dict]) -> Api:
    api = Api(universo)
    D.pedir = api.pedir
    D.sesion = lambda: None
    return api


def bajar(ruta: Path, objetivo: int = 0) -> None:
    D.descargar(objetivo, 10, "id_contrato", "universo de prueba", ruta, False)


def leer(ruta: Path) -> list[str]:
    return [json.loads(x)["id_contrato"]
            for x in ruta.read_text().splitlines()]


def comprobar(nombre: str, ok: bool, detalle: str) -> None:
    print(f"  {'OK  ' if ok else 'FALLA'} {nombre}: {detalle}")
    if not ok:
        FALLOS.append(nombre)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)

        print("\n1. el origen no se movio: la reanudacion sigue funcionando")
        ruta = base / "a.ndjson"
        montar(V1)
        bajar(ruta, objetivo=50)          # se corta a la mitad
        parcial = len(leer(ruta))
        bajar(ruta)                        # reanuda
        ids = leer(ruta)
        comprobar("reanuda desde donde quedo",
                  parcial == 50 and len(ids) == 100 and len(set(ids)) == 100,
                  f"{parcial} -> {len(ids)} filas, {len(set(ids))} distintas")

        print("\n2. control positivo: sin la deteccion aparecen duplicados")
        ruta = base / "b.ndjson"
        montar(V1)
        bajar(ruta)                        # 100 filas del universo viejo
        montar(V2)                         # entran 9 filas en medio del orden
        estado = ruta.with_suffix(ruta.suffix + ".estado.json")
        guardado = json.loads(estado.read_text())
        guardado["disponibles"] = len(V2)  # se miente: "nada se movio"
        estado.write_text(json.dumps(guardado))
        bajar(ruta)
        ids = leer(ruta)
        repetidos = len(ids) - len(set(ids))
        comprobar("el escenario reproduce el fallo", repetidos > 0,
                  f"{len(ids)} filas, {repetidos} id_contrato repetidos")

        print("\n3. con el conteo real: detecta el movimiento y baja de cero")
        ruta = base / "c.ndjson"
        montar(V1)
        bajar(ruta)
        montar(V2)
        bajar(ruta)
        ids = leer(ruta)
        esperado = [f["id_contrato"] for f in V2]
        comprobar("queda el universo nuevo, sin duplicados",
                  ids == esperado and len(set(ids)) == len(V2),
                  f"{len(ids)} filas, {len(ids) - len(set(ids))} repetidos")

        print("\n4. un estado sin 'disponibles' tampoco se reanuda")
        ruta = base / "d.ndjson"
        montar(V1)
        bajar(ruta, objetivo=50)
        estado = ruta.with_suffix(ruta.suffix + ".estado.json")
        guardado = json.loads(estado.read_text())
        del guardado["disponibles"]        # el estado de antes del arreglo
        estado.write_text(json.dumps(guardado))
        bajar(ruta)
        ids = leer(ruta)
        comprobar("no puede probar que sea seguro, asi que reinicia",
                  len(ids) == 100 and len(set(ids)) == 100,
                  f"{len(ids)} filas, {len(set(ids))} distintas")

    if FALLOS:
        print(f"\nFALLA la prueba de reanudacion: {', '.join(FALLOS)}")
        raise SystemExit(1)
    print("\nla descarga no reanuda sobre un origen que se movio.")


if __name__ == "__main__":
    main()
