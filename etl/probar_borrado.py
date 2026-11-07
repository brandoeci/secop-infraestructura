"""Prueba que el hecho borra lo que desaparece del origen. Decision D8.

El MERGE de la carga incremental sabe insertar lo nuevo y actualizar lo que
cambio, pero no sabe que hacer con una fila que estaba en el almacen y ya no
esta en SECOP: un contrato anulado o corregido. La decision D8 es que el hecho
refleja el PRESENTE, asi que esa fila tiene que irse, y de eso se encarga el
post_hook del modelo.

POR QUE NO ESTA DENTRO DEL MERGE
--------------------------------
Primero se intento con 'WHEN NOT MATCHED BY SOURCE THEN DELETE' dentro del
MERGE y dejo la tabla en CERO filas. El origen del MERGE no es el universo: el
modelo lo filtra con is_incremental() para que solo lleguen las filas nuevas o
cambiadas. Contra un delta de 0 filas, 'not matched by source' significa
"ninguna del destino coincide" y borra todo. Esa clausula solo sirve si el
origen del MERGE es el estado completo del presente.

Y POR QUE EL BORRADO TIENE UNA GUARDA
-------------------------------------
Por la misma razon, un paso mas arriba. aterrizar.py SOBRESCRIBE bronze con lo
que le den, y descargar.py --desde baja solo los contratos firmados despues de
una fecha -pipeline.yml lo usa en las corridas programadas-. Con bronze parcial,
"borrar lo que no esta en el origen" se lleva el resto del universo. Por eso el
borrado esta detras de la variable origen_completo, que por defecto es false.

Lo que hace esta prueba:

  1. `dbt build --full-refresh`  estado limpio y conocido.
  2. Se quita un contrato de bronze, simulando que SECOP lo retiro.
  3. Corrida SIN declarar el origen completo. La GUARDA tiene que frenar el
     borrado y la fila tiene que seguir ahi. Esta es la mitad importante de la
     prueba: que el borrado NO corra cuando nadie lo autorizo.
  4. Corrida DECLARANDO el origen completo. Ahora si tiene que borrar, y el
     hecho queda con una fila menos: exactamente esa.
  5. CONTROL NEGATIVO: se mete a mano en el hecho una fila que no esta en el
     origen y se corre solo hecho_completo. Tiene que FALLAR. Sin este paso el
     4 no prueba nada: un test que no sabe fallar siempre esta verde.
  6. Se restaura bronze y se vuelve al estado inicial.

Uso:
  python etl/probar_borrado.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import duckdb

PROYECTO = Path("transformaciones")
ALMACEN = Path("data/warehouse.duckdb")
BRONCE = Path("data/bronze/contratos.parquet")

FANTASMA = "CO1.PCCNTR.NO-ESTA-EN-EL-ORIGEN"


def _exe() -> Path:
    exe = Path(sys.executable).parent / "dbt.exe"
    return exe if exe.exists() else Path(sys.executable).parent / "dbt"


def dbt(*args: str, completo: bool, espera_fallo: bool = False) -> str:
    """Corre dbt declarando -o no- que bronze es el universo completo.

    Ese es el interruptor de la guarda de D8, y la prueba lo ejercita en las
    dos posiciones.
    """
    valor = "true" if completo else "false"
    cmd = [str(_exe()), *args,
           "--vars", f'{{"origen_completo": {valor}}}',
           "--profiles-dir", "."]
    print(f"     $ dbt {' '.join(args)}   [origen_completo={valor}]")
    r = subprocess.run(cmd, cwd=PROYECTO, capture_output=True, text=True)
    fallo = r.returncode != 0
    if fallo != espera_fallo:
        print(r.stdout[-3000:])
        print(r.stderr[-2000:])
        esperado = "que fallara" if espera_fallo else "que pasara"
        raise SystemExit(f"se esperaba {esperado}: dbt {' '.join(args)} -> {r.returncode}")
    return r.stdout


def _consultar(sql: str, params: list | None = None):
    con = duckdb.connect(str(ALMACEN), read_only=True)
    try:
        return con.execute(sql, params or []).fetchone()[0]
    finally:
        con.close()


def conteo_hecho() -> int:
    return _consultar("select count(*) from main_gold.hecho_contratos")


def existe(id_contrato: str) -> bool:
    return _consultar(
        "select count(*) from main_gold.hecho_contratos where id_contrato = ?",
        [id_contrato]) > 0


def un_id_cualquiera() -> str:
    return _consultar("select min(id_contrato) from main_gold.hecho_contratos")


def reescribir_bronce_sin(id_contrato: str) -> None:
    """Deja bronze sin ese contrato, simulando que SECOP lo retiro."""
    tmp = BRONCE.with_suffix(".sin_uno.parquet")
    con = duckdb.connect()
    try:
        con.execute(
            f"copy (select * from '{BRONCE.as_posix()}' where id_contrato <> ?) "
            f"to '{tmp.as_posix()}' (format parquet)",
            [id_contrato],
        )
    finally:
        con.close()
    tmp.replace(BRONCE)


def fila_fantasma(poner: bool) -> None:
    con = duckdb.connect(str(ALMACEN))
    try:
        if poner:
            con.execute(
                "insert into main_gold.hecho_contratos "
                "select * replace (? as id_contrato) "
                "from main_gold.hecho_contratos limit 1", [FANTASMA])
        else:
            con.execute(
                "delete from main_gold.hecho_contratos where id_contrato = ?",
                [FANTASMA])
    finally:
        con.close()


def main() -> int:
    respaldo = BRONCE.read_bytes()

    try:
        print("1. estado limpio")
        dbt("build", "--full-refresh", completo=True)
        n0 = conteo_hecho()
        print(f"   hecho: {n0:,} filas")

        objetivo = un_id_cualquiera()
        print(f"\n2. se retira {objetivo} de bronze")
        reescribir_bronce_sin(objetivo)

        print("\n3. corrida SIN declarar el origen completo")
        # El gate TIENE que ponerse rojo, y no por hecho_completo: las
        # dimensiones son 'table' y se reconstruyen sin el proveedor de ese
        # contrato, mientras el hecho conserva la fila. Eso deja una clave
        # huerfana y la integridad referencial lo detecta. Es el incidente del
        # 2026-11-03 de docs/calidad-datos.md seccion 6, reproducido a voluntad.
        salida = dbt('build', completo=False, espera_fallo=True)
        n_guardado = conteo_hecho()
        assert n_guardado == n0, f"la guarda no freno: {n0} -> {n_guardado}"
        assert existe(objetivo), f"{objetivo} se borro sin que nadie lo autorizara"
        assert "relationships_hecho_contratos" in salida, (
            "el gate fallo por otra razon, no por la clave huerfana:" + salida[-2000:])
        print(f"   la guarda freno el borrado: {objetivo} sigue en el hecho")
        print("   y el gate se puso ROJO por clave huerfana, no publico nada.")
        print("   Las dos salidas son seguras: una repara, la otra se niega.")

        print("\n4. corrida DECLARANDO el origen completo: ahora si debe borrar")
        dbt("build", completo=True)
        n1 = conteo_hecho()
        print(f"   hecho: {n1:,} filas   (esperado {n0 - 1:,})")
        assert n1 == n0 - 1, f"el hecho tiene {n1}, se esperaba {n0 - 1}"
        assert not existe(objetivo), f"{objetivo} sigue en el hecho"
        print(f"   {objetivo} ya no esta en el hecho")
        dbt("test", "--select", "hecho_completo", completo=True)
        print("   hecho_completo en verde")

        print("\n5. control negativo: se mete una fila que no esta en el origen")
        fila_fantasma(poner=True)
        dbt("test", "--select", "hecho_completo", completo=True, espera_fallo=True)
        print("   hecho_completo FALLO, como debia")
        fila_fantasma(poner=False)

    finally:
        BRONCE.write_bytes(respaldo)
        print("\n6. bronze restaurado, se reconstruye")
        dbt("build", "--full-refresh", completo=True)
        print(f"   hecho: {conteo_hecho():,} filas")

    print("\nOK: D8 se cumple cuando el origen esta declarado completo, la guarda")
    print("    lo impide cuando no, y el gate vigila las dos cosas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
