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

## D3 — Umbral de contratos atípicos

**Decidido el 2026-10-05 al validar la descarga.**

El atípico se mide contra el percentil 99 de **su propia `modalidad_de_contratacion`**, no
contra el del universo completo, porque la modalidad refleja un rango de cuantía definido por
ley. La regla salió de un caso real: un contrato de *mínima cuantía* por 6,45 cuatrillones de
pesos, 38 millones de veces el p99 de su modalidad. Ver [`calidad-datos.md`](calidad-datos.md).

---

## D4 — La definición de `% ejecutado`

**Decidido el 2026-10-05 al construir el modelo.** Se acota a contratos donde el pago ya es
exigible (`estado` en `Cerrado` o `Terminado`), y la cobertura del dato se publica como medida
propia.

Lo que decidió: medir las dos y comparar.

| Medida | Resultado |
|---|---|
| Sobre los 66.874 contratos confiables | **13,4 %** |
| Acotada a los 17.814 con `pago_exigible` | **46,8 %** |

El 13,4 % no describe la realidad: mete contratos aprobados y en ejecución que todavía no
tenían por qué haber pagado nada. El 46,8 % es la cifra defendible.

Y como el vacío de reporte es en sí mismo un resultado interesante, se añade una medida
`% sin ejecución reportada`: qué porcentaje de los contratos ya terminados reporta cero pagado.
Son 5.234 de 13.885 contratos `Terminado`. Eso es un hallazgo del informe, no un defecto que
haya que esconder.

El DAX de las dos medidas está en [`modelo.md`](modelo.md).

---

## D5 — Qué hacer con el registro corrupto

**Decidido el 2026-10-05: marcar, no borrar.**

`CO1.PCCNTR.5972834` se queda en el hecho con `valor_confiable = False`. Todas las medidas de
dinero filtran por esa bandera, así que no contamina ninguna suma, pero sigue visible en la
página de atípicos.

Borrarlo habría sido más simple y habría dado el mismo total. Se descartó porque una fila que
desaparece del modelo no deja rastro de que existió: el informe describe cómo se reporta el
gasto público, y un registro con 6,45 cuatrillones de pesos **es** parte de cómo se reporta.
Marcarlo también demuestra que se detectó y se diagnosticó, en lugar de hacerlo desaparecer.

La misma bandera se aplica a `fechas_coherentes` (200 filas) y `pagado_excede` (43).

---

## Pendiente de decidir — cruce con la red vial de INVÍAS

La dimensión `territorial_vial` todavía no está construida. El dataset `ie7y-asdn` (715 filas
por 18 columnas) tiene `Territorial` y `Departamento`, pero hay que definir por dónde se une
con los contratos: el departamento de la entidad contratante no es necesariamente el
departamento donde está la vía. Se decide al construirla.
