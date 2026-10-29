# Calidad de los datos del universo de obra

Hallazgos sobre los **66.875 contratos** descargados el 2026-10-05. Todas las cifras salen de
correr el código sobre `data/raw/obra.ndjson`.

El proyecto describe gasto público: **no acusa a nadie**. Lo que sigue son problemas de
diligenciamiento de los datos, no denuncias.

---

## 1. Un solo registro corrupto distorsiona todo el dataset

### El síntoma

Sumar `valor_del_contrato` sobre los 66.875 contratos da **$6.542,11 billones COP**. Eso es
imposible: son unas 4 veces el PIB anual de Colombia, para tres años de contratos de obra.

### La causa

Un único contrato:

| Campo | Valor |
|---|---|
| `id_contrato` | `CO1.PCCNTR.5972834` |
| `nombre_entidad` | INSTITUCION EDUCATIVA ELISEO PAYAN |
| `valor_del_contrato` | **$6.453.840.000.000.000** (6,45 cuatrillones COP) |
| `valor_pendiente_de_pago` | $6.453.840.000.000.000 |
| `valor_pagado` | $0 |
| `modalidad_de_contratacion` | **Mínima cuantía** |
| `tipo_de_contrato` | Obra |
| `objeto_del_contrato` | MEJORAMIENTO Y/O ADECUACION DE LA INSFRAESTRUCTURA EDUCATIVA… |
| Duración | 2024-03-01 a 2024-05-22 (menos de 3 meses) |

### Por qué es error de datos y no un contrato real

Tres cosas se contradicen entre sí dentro del propio registro:

1. **La modalidad tiene techo legal.** Es un contrato de *mínima cuantía*, la modalidad para las
   compras más pequeñas del Estado. De los 18.781 contratos de mínima cuantía del universo, la
   **mediana es $33,8 millones** y el **p99 es $169,1 millones**. Este registro es ~38 millones
   de veces el p99 de su propia modalidad.
2. **El plazo no corresponde.** Menos de 3 meses para un mejoramiento de infraestructura
   educativa en un colegio.
3. **La magnitud es imposible.** El p99,99 de todo el universo es $650 mil millones. Este
   registro es ~10 millones de veces esa cifra.

Es un error de magnitud al digitar (ceros de más). **No se interpreta como hallazgo.**

### El impacto

| Medición | Con el registro | Sin el registro |
|---|---|---|
| Valor contratado total | $6.542,11 billones | **$88,27 billones** |
| Ratio pagado / contratado | 0,18 % | **13,4 %** |
| Departamento que concentra más valor | `No Definido` (98,7 %) | Distrito Capital de Bogotá (41,8 %) |
| Valor en departamento `No Definido` | $6.454,81 billones | $0,97 billones (1,1 %) |

**Una fila de 66.875 explicaba el 98,6 % del valor total** y dejaba el informe entero sin
sentido. Los 10 contratos mayores concentran el 98,8 % del valor en crudo.

Con el registro excluido, $88,27 billones para tres años de contratación de obra es una cifra
de orden razonable, y la concentración geográfica (Bogotá 41,8 %, Antioquia 11,1 %) es
coherente con lo que se esperaría.

---

## 2. Otros cuatro contratos de mínima cuantía que hay que revisar

La misma regla (valor contra techo de la modalidad) señala 4 casos más por encima de $1.000
millones. **No se afirma que sean errores**: quedan marcados para revisión.

| Valor | Entidad |
|---|---|
| $155.326.159.750 | SENA Regional Nariño |
| $53.899.979.096 | Contraloría Departamental del Meta |
| $31.725.000.000 | Alcaldía Municipal de Pauna |
| $31.200.000.023 | Alcaldía Municipal de Turbaná |

También hay un contrato de **$998.049.859.557 por la adecuación de una cancha de fútbol** en
Sitionuevo (Magdalena), que es alto para ese objeto pero no se contradice internamente como el
caso anterior. Queda marcado, no excluido.

---

## 3. Regla de validación que sale de aquí

Esto le da fundamento concreto a la medida de **detección de contratos atípicos** que ya estaba
prevista en el modelo. En lugar de un umbral inventado, la regla es:

> Comparar `valor_del_contrato` contra el percentil 99 de **su propia
> `modalidad_de_contratacion`**, no contra el del universo completo.

Es defendible porque la modalidad de contratación refleja un rango de cuantía definido por ley:
un atípico en mínima cuantía no es lo mismo que un atípico en licitación pública.

### Cómo se trató, al final

Se eligió **dejarlo y marcarlo** con `valor_confiable = false` (decisión D5), en vez de
excluirlo del modelo. Excluirlo habría sido más limpio y habría escondido el problema; así el
contrato aparece en la página de atípicos del informe y queda fuera de las sumas de dinero,
porque las medidas DAX de valor filtran por esa bandera.

---

## 4. Otros problemas medidos en el universo

| Problema | Filas | % |
|---|---|---|
| `valor_pagado = 0` | 41.362 | **61,8 %** |
| `fecha_de_inicio_del_contrato` nula | 2.583 | 3,9 % |
| `departamento = 'No Definido'` | 1.672 | 2,5 % |
| `valor_del_contrato = 0` | 630 | 0,94 % |
| `valor_pagado > valor_del_contrato` | 43 | 0,06 % |
| `valor_del_contrato < 0` | 0 | 0 % |

- **`valor_pagado = 0` en el 61,8 %** es el problema de fondo, ya documentado en la sección 7 de
  [`estructura.md`](estructura.md) y pendiente de decisión en
  [`decisiones.md`](decisiones.md). Se confirma sobre el universo real.
- **630 contratos con valor 0** hay que decidir si se excluyen: un contrato de obra por $0 no
  describe gasto.
- **43 contratos con más pagado que contratado** son poco (0,06 %) pero rompen la lógica de
  `% ejecutado`, que quedaría por encima del 100 %. La medida DAX tiene que preverlo.
- Las columnas de texto siguen con la **capitalización inconsistente** ya detectada:
  `estado_contrato` trae `terminado` y `cedido` en minúscula, y `modalidad_de_contratacion`
  tiene `Contratación directa` junto a `Contratación Directa (con ofertas)`.

---

## 5. Fechas incoherentes, y una que rompia la tabla de fechas

Detectado al construir el modelo (`etl/transformar.py`), no en la exploracion inicial.

| Problema | Filas |
|---|---|
| El contrato termina **antes de firmarse** | 200 |
| Duracion negativa (fin antes del inicio) | 36 |
| Fecha de inicio anterior a la firma | 20 |
| Fecha de fin en el **anio 0206** | 1 |

### El anio 0206

`CO1.PCCNTR.8725754` (Municipio de Puerto Gaitan, firmado el 2025-12-23) trae la fecha de fin
en el **anio 0206**. Casi seguro se quiso digitar 2026.

Esa sola fila estiraba la tabla de fechas del modelo a **675.699 filas**, unos 1.850 anios,
dejandola inservible y engordando el modelo sin motivo.

**No se adivino la fecha ni se borro el contrato.** Las fechas fuera de una ventana plausible
(2015-2060) no entran a `dim_fecha`, la clave del hecho queda en nulo y la fila queda marcada
con `fechas_coherentes = False`. `dim_fecha` quedo en 13.879 filas.

La ventana llega hasta 2060 a proposito: **94 contratos terminan despues de 2035** y son
concesiones de obra a 20 y 30 anios, no errores. Recortar por "parece muy lejano" habria
borrado contratos legitimos.

### Las 200 que terminan antes de firmarse

No se corrigen, se marcan. Un contrato que termina antes de su firma puede ser un error de
digitacion o una formalizacion retroactiva; el dato no alcanza para distinguirlo, y afirmar
cual es seria inventar. La duracion se deja nula cuando saldria negativa: un numero negativo
de dias no es una duracion corta, es un dato malo, y promediarlo contaminaria la medida.

---

## 6. La cifra del universo se mueve: el dataset se actualiza a diario

El universo se midió en **66.831** contratos y, unos minutos después, la descarga trajo
**66.875**. Los dos componentes del filtro crecieron (A: 36.276 → 36.317; B: 43.163 → 43.176),
o sea que fue la actualización diaria de SECOP II, no un filtro distinto.

Consecuencias:

- El límite inferior de fecha está **fijo en el código** (`DESDE = '2023-10-05'`) y no es "hoy
  menos 3 años", justamente para que la cifra sea comparable entre corridas.
- Aun así el total crece, porque entran contratos nuevos. **Cualquier cifra del README tiene que
  ir con la fecha de la descarga.**
- `data/raw/obra.ndjson.estado.json` guarda la consulta y el conteo de esa corrida.

---

## 7. Los controles, ya ejecutables

Todo lo anterior era prosa: un diagnóstico escrito que nadie comprobaba en cada corrida. Ahora
son **67 tests de dbt** que corren con `dbt build`, y la exportación a `data/curated/` va
**después**, así que un modelo que no los pasa nunca llega a Power BI.

Estado medido el **2026-10-29**: 63 pasan, 4 avisan, 0 rompen.

### Lo que rompe la corrida (`severity: error`)

| Control | Por qué bloquea |
|---|---|
| `id_contrato` único y no nulo | Si se duplica, el grano "un contrato" deja de sostenerse y toda suma queda mal |
| Integridad referencial del hecho a las 7 dimensiones | Una huérfana deja filas invisibles en el informe sin avisar |
| `entidad_key` y `proveedor_key` no nulos | Son las dos dimensiones por las que el informe pregunta "quién contrata" |
| [`anio_fuera_de_ventana`](../transformaciones/tests/anio_fuera_de_ventana.sql) | Una fecha fuera de 2015–2060 no es un dato feo, es una tabla de fechas inservible (ver sección 5) |
| [`valor_fuera_de_escala`](../transformaciones/tests/valor_fuera_de_escala.sql) | Ningún contrato debe superar 100.000× la mediana de su modalidad |

### Lo que avisa y deja pasar (`severity: warn`)

Son los defectos del origen diagnosticados arriba. No son sorpresas: son el estado conocido del
dato público, y el informe los describe en vez de ocultarlos. El umbral de `error_if` sale de
medir el estado actual y dejar holgura, así que si el origen se degrada mucho más allá de eso
la corrida sí se detiene.

| Control | Hoy | Rompe si |
|---|---|---|
| [`valor_contratado_no_positivo`](../transformaciones/tests/valor_contratado_no_positivo.sql) | 630 | > 1.000 |
| [`atipicos_sobre_p99`](../transformaciones/tests/atipicos_sobre_p99.sql) | 27 | > 100 |
| [`fechas_incoherentes`](../transformaciones/tests/fechas_incoherentes.sql) | 200 | > 500 |
| [`pagado_excede_contratado`](../transformaciones/tests/pagado_excede_contratado.sql) | 43 | > 200 |
| `estado` dentro de los 8 valores conocidos | 8 | nunca, solo avisa |

### El control que habría ahorrado el trabajo de la sección 1

`valor_fuera_de_escala` es la regla que **habría atrapado sola** el contrato de 6,45
cuatrillones. Se tardaron horas en encontrarlo a mano; con este test la corrida se habría
detenido en la primera.

Sus dos primeras versiones estaban mal, y las dos las descubrió el fixture de 280 filas del CI:

1. **Medirlo como fracción del valor total depende del tamaño del dataset.** El contrato más
   grande pesa 1,55 % sobre el universo completo y 12,54 % sobre 280 filas: el test saltaba por
   el tamaño de la muestra, no por un error.
2. **Medirlo contra el p99 de la modalidad tampoco funciona**, aunque sea la referencia de la
   sección 3. En una modalidad con pocos contratos, el registro corrupto **entra en el cálculo
   de su propio p99 y lo infla**: la razón vuelve a ser cerca de 1 y el test no dispara.

La versión que funciona mide contra la **mediana** de la modalidad, que es robusta: una sola
fila extrema, por grande que sea, la mueve una posición.

| | Veces la mediana de su modalidad |
|---|---|
| Contrato legítimo más extremo | 14.884× |
| Contratos por encima de 100.000× | **0** |
| `CO1.PCCNTR.5972834` | **190.693.033×** |

Entre lo legítimo y lo imposible hay cuatro órdenes de magnitud, y el umbral de 100.000× cae
justo en ese hueco: siete veces de holgura sobre el peor caso real y mil novecientas por debajo
del error que tiene que cazar.

### Que el control bloquea de verdad, probado

```bash
python etl/probar_gate.py
```

Inyecta en bronze un contrato con ese mismo perfil y comprueba que `dbt build` falla con código
distinto de 0, que lo caza `valor_fuera_de_escala`, y sobre todo que **`data/curated/` queda
byte a byte idéntico**. El registro malo sí entra al gold de DuckDB —es ahí donde el test puede
verlo— pero no llega a los Parquet del informe.

Verificado a las dos escalas: bloquea con 66.875 filas y con las 280 del fixture.

### La bitácora

Cada corrida deja una fila en `data/curated/auditoria_corridas.parquet` con su resultado
(PASS / WARNING / FAIL), los tests por estado y las filas en cada capa. Corre **pase o falle**,
porque una corrida que falló es la que más interesa tener registrada.
---

## Cómo reproducir todo esto

```bash
python etl/descargar.py --universo obra        # 66.875 filas, 20 columnas, 66,9 MB
python etl/explorar.py --muestra data/raw/obra.ndjson
```

Validación de la descarga, verificada: 66.875 filas, **0 `id_contrato` duplicados** (el grano
"un contrato" se sostiene), exactamente las 20 columnas pedidas, 0 filas con firma anterior al
2023-10-05.
