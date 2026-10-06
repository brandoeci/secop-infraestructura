# El modelo en Power BI

Esta carpeta es un **PBIP** (Power BI Project), no un `.pbix`. El PBIP guarda el modelo
semántico en **TMDL**, que es texto: se versiona en git, se revisa en un diff y se puede leer
directamente en GitHub. Un `.pbix` es un binario opaco que no deja ver nada de esto.

```
secop-infraestructura.pbip                    <- abra este archivo
secop-infraestructura.SemanticModel/
  definition/
    model.tmdl              configuración del modelo
    database.tmdl           nivel de compatibilidad
    expressions.tmdl        el parámetro RutaCurated
    relationships.tmdl      las 9 relaciones
    roles.tmdl              el rol de RLS
    tables/*.tmdl           las 8 tablas + la tabla puente del RLS
secop-infraestructura.Report/
  report.json               una página en blanco, a propósito
```

---

## Antes de abrirlo

El modelo lee los Parquet que produce el ETL, así que primero hay que generarlos:

```bash
pip install -r requirements.txt
python etl/descargar.py --universo obra
python etl/transformar.py
```

Eso deja ocho archivos en `data/curated/`. **Si no existen, el modelo no carga.**

### Si clonó el repositorio en otra ruta

El parámetro `RutaCurated` viene con la ruta absoluta de la máquina donde se generó. Power BI
no tiene concepto de «raíz del repositorio», así que hay que ajustarlo:

> **Inicio → Transformar datos → Administrar parámetros → `RutaCurated`**

Apúntelo a su propia carpeta `data/curated`.

---

## Abrirlo

Doble clic en `secop-infraestructura.pbip`. Power BI Desktop lo convierte y carga las ocho
tablas.

Si Desktop se queja del formato de proyecto, active la opción en
**Archivo → Opciones → Características de vista previa → «Power BI Project (.pbip)»** y
reinicie. En versiones recientes ya viene activado.

### Verificación de la carga

Ponga estas medidas en tarjetas. Si los números coinciden, el modelo cargó bien:

| Medida | Valor esperado |
|---|---|
| `Contratos` | 66.875 |
| `Valor contratado` | 88.273.777.947.266 |
| `Valor pagado` | 11.865.954.850.752 |
| `% ejecutado` | 46,8 % |
| `% sin ejecucion reportada` | 33,7 % |
| `Contratos atipicos` | 27 |
| `Duracion promedio dias` | 188 |

Las cifras corresponden a la descarga del 2026-10-05. **El dataset se actualiza a diario**, así
que si vuelve a correr el ETL los totales serán algo mayores. El número de filas de la descarga
queda registrado en `data/raw/obra.ndjson.estado.json`.

---

## Qué ya está hecho en el modelo

- **Las 8 tablas** con tipos, `formatString` y las columnas de clave ocultas.
- **9 relaciones.** Las tres fechas del hecho apuntan a la misma `dim_fecha`:
  `fecha_firma_key` es la **activa** (la pregunta del informe es cuándo se comprometió el
  dinero) y las de inicio y fin quedan **inactivas**, para activarlas con `USERELATIONSHIP`
  cuando una medida necesite otro eje.
- **`dim_fecha` marcada como tabla de fechas** (`dataCategory: Time` y la columna `fecha` como
  clave). Sin eso la inteligencia de tiempo se comporta de forma impredecible.
- **`nombre_mes` ordenado por `mes`**, para que los meses no salgan alfabéticos.
- **10 medidas DAX** con descripción, incluidas `% ejecutado` acotada y
  `% sin ejecucion reportada`.
- **El rol de RLS** «Supervisor regional», dinámico por `USERPRINCIPALNAME()`.
- **`discourageImplicitMeasures`**: obliga a usar las medidas explícitas en lugar de arrastrar
  una columna numérica y que Power BI invente una suma.

### Probar el RLS

**Modelado → Ver como → «Supervisor regional» + «Otro usuario»**, y escriba
`supervisor.antioquia@ejemplo.gov.co`. Debería ver solo los contratos de entidades de
Antioquia.

Las filas de `mapa_usuarios` son **de ejemplo**, escritas en el propio modelo con `#table`. En
producción esa tabla vendría de un origen real. Está oculta del panel de campos porque no es
una dimensión del informe.

El RLS filtra por el departamento **de la entidad contratante**, no por dónde se ejecuta la
obra. En este dataset el departamento describe a la entidad; la dirección de ejecución existe
pero es texto libre sin normalizar.

---

## Qué falta, y es suyo

**Los visuales.** No están hechos a propósito: el informe es la parte que se practica y la que
se defiende en una entrevista. La página viene en blanco.

La pregunta que debe responder el informe es *en qué se gasta la plata de infraestructura*:
quién contrata, cuánto se ejecuta de verdad, qué departamentos concentran el dinero y qué
contratos se salen del patrón.

Una estructura que funciona para eso, sin pasar de 4 páginas:

1. **Panorama** — tarjetas con `Valor contratado`, `Contratos` y `% ejecutado`; valor por
   departamento; evolución por `anio_mes`.
2. **Quién contrata** — tabla de entidades con `Ranking entidad`, segmentada por `orden`
   (Nacional / Territorial) y `tipo_contrato`.
3. **Ejecución** — `% ejecutado` por estado, y `% sin ejecucion reportada` destacado. Esta es
   la página con el hallazgo propio: hay que decir claramente que mide **cobertura del dato**,
   no corrupción.
4. **Atípicos** — tabla filtrada por `veces_p99_modalidad`, con `objeto_del_contrato` para
   poder leer de qué se trata cada contrato.

Dos cosas que conviene dejar visibles en el informe, porque un revisor técnico las va a buscar:

- Que `% ejecutado` está **acotado a contratos terminados**, y por qué. Sin esa nota, el 46,8 %
  parece una cifra sin criterio.
- Que hay **un contrato excluido de las sumas** por valor no confiable (`valor_confiable`), con
  el enlace a [`../docs/calidad-datos.md`](../docs/calidad-datos.md).

---

## Si el PBIP no abre

No pude probar la apertura: el archivo se generó sin ejecutar Power BI Desktop. Si da un error,
el modelo se arma a mano en unos minutos y el resultado es idéntico.

1. Power BI Desktop → **Obtener datos → Parquet** → `data/curated/hecho_contratos.parquet`.
2. Repetir para las otras siete tablas.
3. Crear las relaciones de la tabla de arriba; dejar inactivas las de `fecha_inicio_key` y
   `fecha_fin_key`.
4. Marcar `dim_fecha` como tabla de fechas con la columna `fecha`.
5. Copiar las medidas desde [`../docs/modelo.md`](../docs/modelo.md), que las tiene todas en
   DAX.
6. Ordenar `nombre_mes` por `mes`, y ocultar las columnas `*_key`.

El paso 1 depende de un detalle que ya está resuelto en el ETL: pandas 3 escribe los textos
como `large_string`, un tipo que el conector Parquet de Power Query **no lee**, y la carga
falla. `etl/transformar.py` fuerza un esquema explícito con tipos que el conector sí soporta.
Si algún día cambia el ETL, ese es el primer sitio donde mirar.
