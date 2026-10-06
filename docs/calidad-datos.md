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

### Decisión pendiente

Cómo tratar `CO1.PCCNTR.5972834` en el informe. Opciones:

1. **Excluirlo del modelo** y documentar la exclusión en el informe. Limpio, pero esconde el
   problema.
2. **Dejarlo y marcarlo** con una bandera de "valor no confiable", excluyéndolo de las sumas
   pero mostrándolo en la página de atípicos. Más trabajo, más honesto.

La 2 es mejor para una entrevista: demuestra que se detectó, se diagnosticó y se trató el dato
sucio en lugar de borrarlo sin dejar rastro. Se decide al construir el modelo.

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

## 5. La cifra del universo se mueve: el dataset se actualiza a diario

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

## Cómo reproducir todo esto

```bash
python etl/descargar.py --universo obra        # 66.875 filas, 20 columnas, 66,9 MB
python etl/explorar.py --muestra data/raw/obra.ndjson
```

Validación de la descarga, verificada: 66.875 filas, **0 `id_contrato` duplicados** (el grano
"un contrato" se sostiene), exactamente las 20 columnas pedidas, 0 filas con firma anterior al
2023-10-05.
