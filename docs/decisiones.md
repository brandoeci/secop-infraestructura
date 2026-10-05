# Decisiones de modelado

Cada decisión con la medición que la sustenta. Las cifras vienen de
[`estructura.md`](estructura.md) y todas salieron de correr el código contra la API.

---

## D1 — Cómo se identifica un contrato de infraestructura

**Decidido el 2026-10-05: la unión de los dos criterios.**

```sql
fecha_de_firma >= '2023-10-05T00:00:00'
AND (
      tipo_de_contrato IN ('Obra', 'Interventoría', 'Consultoría',
                           'Concesión', 'Asociación Público Privada')
   OR codigo_de_categoria_principal LIKE 'V1.72%'
)
```

**Resultado verificado: 66.831 contratos.**

### Por qué la unión y no uno de los dos

Se midieron los dos criterios por separado sobre la población completa antes de decidir:

| Conjunto | Filas |
|---|---|
| A — por `tipo_de_contrato` | 36.276 |
| B — por UNSPSC `V1.72%` | 43.163 |
| A ∩ B | 12.608 |
| A ∪ B | **66.831** |

**Los dos criterios casi no se solapan**: solo 12.608 contratos cumplen ambos, de 66.831. Es
decir, cada criterio por separado deja fuera entre 23.000 y 30.000 contratos que el otro sí
encuentra. Usar uno solo no es una simplificación, es perder un tercio del universo.

Las dos razones concretas:

1. **Hay obra contratada bajo otro tipo.** De los 30.555 contratos que B encuentra y A pierde,
   15.746 están clasificados como *Prestación de servicios* y 10.614 como *Otro*, pese a tener
   categoría UNSPSC de construcción.
2. **El UNSPSC no siempre se diligencia.** De los 25.203 contratos tipo `Obra`, **7.519 (30 %)
   traen la categoría en `UNSPECIFIED`**.

### Por qué no se filtra por texto del objeto

Se probó y se descartó como criterio principal: `objeto_del_contrato LIKE '%VIA%'` devuelve
90.679 filas, pero sin fronteras de palabra captura también **VIAJE, LLUVIA, PREVIA,
VIABILIDAD**. El texto libre sirve para afinar o para detectar atípicos, no para definir el
universo.

### Limitación asumida

La unión incluye contratos de servicios de mantenimiento de instalaciones que alguien podría no
llamar "obra". Se asume a propósito: el informe responde *en qué se gasta la plata de
infraestructura*, y el mantenimiento de infraestructura es gasto de infraestructura. Queda
documentado para poder defenderlo.

---

## D2 — Qué 20 columnas se conservan de las 95

**Decidido el 2026-10-05.**

### Hecho `contratos` — grano: un contrato

| Columna | Papel |
|---|---|
| `id_contrato` | clave del hecho |
| `valor_del_contrato` | medida |
| `valor_pagado` | medida |
| `valor_facturado` | medida |
| `valor_pendiente_de_pago` | medida |
| `fecha_de_firma` | clave a dim `fecha` |
| `fecha_de_inicio_del_contrato` | clave a dim `fecha` |
| `fecha_de_fin_del_contrato` | clave a dim `fecha` |
| `objeto_del_contrato` | atributo degenerado (detección de atípicos, drillthrough) |

### Dimensiones

| Dimensión | Columnas |
|---|---|
| `entidad` | `nit_entidad` (clave), `nombre_entidad`, `departamento`, `ciudad`, `orden` |
| `proveedor` | `documento_proveedor` (clave), `proveedor_adjudicado` |
| `tipo_contrato` | `tipo_de_contrato` |
| `estado` | `estado_contrato` |
| `categoria` | `codigo_de_categoria_principal` |
| `modalidad` | `modalidad_de_contratacion` |

### Notas de modelado

- **`duraci_n_del_contrato` se descarta aunque exista.** Viene como **texto**. La duración se
  calcula restando `fecha_de_fin` menos `fecha_de_inicio`, que ya son `calendar_date`. Un
  número derivado de fechas limpias es más confiable que un texto de la fuente.
- **`objeto_del_contrato` se queda en el hecho, no en una dimensión.** Es texto largo y casi
  único por contrato: una dimensión con una fila por hecho no es una dimensión. Va como
  atributo degenerado.
- **`estado_contrato` hay que normalizar al cargarlo.** La fuente trae `terminado`, `cedido` y
  `enviado Proveedor` sin capitalizar mientras el resto sí. Sin normalizar, la dimensión
  muestra valores que parecen distintos y no lo son.
- **`departamento` y `ciudad` van en `entidad`, no en una dimensión geográfica propia.** En este
  dataset describen a la entidad contratante, no el lugar de ejecución de la obra. Llamarla
  "geografía" sería afirmar algo que los datos no dicen. La dirección de ejecución existe en
  `direcci_n_de_ejecuci_n_del_contrato`, pero es texto libre sin normalizar: **2.475 valores
  distintos en 10.000 filas, con saltos de línea dentro del propio campo**. No sirve como
  dimensión sin un trabajo de geocodificación que está fuera del alcance.
- **`modalidad_de_contratacion` también trae inconsistencias de capitalización**: coexisten
  `Contratación directa` (76,0 %) y `Contratación Directa (con ofertas)` (1,3 %). Hay que
  normalizar esta dimensión igual que `estado`.

### Qué se descarta y por qué

| Grupo | Columnas | Razón |
|---|---|---|
| Datos personales | representante legal (6), ordenador del gasto (3), supervisor (3), ordenador de pago (3) | Nombres y documentos de personas naturales. Sin valor analítico y no corresponde publicarlos en un informe de portafolio. |
| Datos bancarios | `nombre_del_banco`, `tipo_de_cuenta`, `n_mero_de_cuenta` | Igual: dato sensible, cero uso analítico. |
| Columnas ambientales | 6 columnas de criterios y obligaciones ambientales | Entre 98,5 % y 99,9 % con el valor `No Definido`. Vacías en la práctica. |
| Fechas vacías | `fecha_inicio/fin_reversi_n`, `fecha_inicio/fin_obligaciones_posconsumo` | 100 % y 99,96 % nulas en la muestra. |
| Postconflicto | `espostconflicto`, `puntos_del_acuerdo`, `pilares_del_acuerdo` | 99,3 % en `No` / `No aplica`. |
| Desgloses de fuente de recursos | PGN, SGP, regalías, crédito, recursos propios | Entre 79 % y 99,7 % en 0. Quedan como candidatas si más adelante hace falta el origen del dinero. |

### Candidatas si se quiere ampliar a 24

`sector` (dim entidad), `es_pyme` (dim proveedor), `dias_adicionados` (medida), `urlproceso`
(drillthrough al proceso real en SECOP).

---

## Pendiente de decidir — `valor_pagado` y la medida `% ejecutado`

**No decidido. Bloquea la definición de la medida principal del informe.**

`valor_pagado` viene en **0 en el 61,9 %** de los 66.831 contratos del universo, incluido el
**37,7 % de los que están `terminado`** (5.224 contratos) y el 19,4 % de los `Cerrado`. El
detalle por estado está en la sección 7 de [`estructura.md`](estructura.md).

Un contrato terminado con 0 pagado no es un contrato gratis: es un vacío de reporte de la
entidad. Por lo tanto `% ejecutado = valor_pagado / valor_del_contrato` calculado sobre todo el
universo daría un número artificialmente bajo que no describe la realidad.

Opciones a evaluar cuando se construya el modelo:

1. Acotar la medida a estados donde el pago ya debería estar reportado (`Cerrado`, `terminado`)
   y mostrar aparte cuántos contratos se excluyen y por qué.
2. Contrastar contra `valor_facturado` y `valor_pendiente_de_pago` (por eso los dos están entre
   las 20 columnas) para ver si alguno está mejor diligenciado.
3. Publicar la cobertura del dato como hallazgo propio del informe: *qué porcentaje del gasto de
   infraestructura no tiene ejecución reportada* es, en sí mismo, un resultado interesante.

La opción 3 es la más honesta y probablemente la más interesante para una entrevista, pero
requiere medir primero. Se decide al construir el modelo, no antes.
