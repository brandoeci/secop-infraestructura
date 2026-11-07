# El proyecto en formato STAR

Para postulaciones escritas y para LinkedIn. Está redactado de modo que **lo entienda alguien
que no es técnico**, con la traducción técnica al lado por si quien lo lee sí lo es.

Todas las cifras salen del repositorio. Si alguien pregunta de dónde sale una, se corre el código.

---

## Situación

El Estado colombiano publica **todos** sus contratos en una plataforma abierta llamada SECOP II:
6.102.286 registros, gratis y al alcance de cualquiera.

Pero *publicado* no es lo mismo que *utilizable*. Nadie puede responder una pregunta tan simple
como **«¿en qué se gasta la plata de infraestructura?»**, porque los datos llegan con 95 columnas,
sin ningún campo que diga «esto es una obra», y con errores de digitación que nadie filtra.

## Tarea

Construir, solo y de punta a punta, el camino completo: desde la API pública hasta un informe que
una persona pueda leer en dos minutos — y que las cifras se puedan verificar, no solo creer.

## Acción

| Lo que hice | Cómo, en términos técnicos |
|---|---|
| **Definir qué cuenta como obra.** Ninguna columna lo dice. Probé dos criterios distintos y descubrí que casi no se solapan: de 67 mil contratos, solo 12 mil cumplen los dos. Me quedé con la unión y dejé escrito por qué. | Filtro por tipo de contrato **unido** a código de categoría UNSPSC, con la decisión documentada y medida |
| **Reducir el problema a su tamaño real**: de 6,1 millones de registros a los 67.299 que son obra de los últimos tres años. Con eso el proceso corre en segundos en un portátil. | Alcance acotado; se descartó Spark a propósito, porque el volumen no lo exige |
| **Poner controles que bloqueen.** 75 verificaciones automáticas. Si una falla, el informe **no** se actualiza: sigue mostrando los últimos datos buenos en vez de refrescarse sobre datos malos. | Tests de dbt como *gate*; la exportación corre solo si el gate pasó |
| **Hacer que funcione solo.** Corre cada semana sin que nadie lo lance, y cada cambio de código vuelve a ejecutarlo todo contra **dos motores de base de datos distintos**. | Airflow + GitHub Actions; el mismo SQL contra DuckDB y BigQuery, con identidad federada y sin llaves guardadas |
| **Construir el informe.** Cinco páginas, una por pregunta, más una restricción de acceso para que un supervisor regional vea solo su departamento. | Modelo en estrella —un hecho, ocho dimensiones— y seguridad a nivel de fila dinámica en Power BI |

## Resultado

**Un informe publicado y un repositorio que cualquiera puede clonar y ejecutar.** 72 commits,
todo en verde.

Y dos cosas que el proyecto encontró y que no estaban en el plan:

**Un solo contrato mal digitado valía el 98,6 % del total.** Al sumar el valor contratado daba
cuatro veces el PIB del país. De ahí salió la regla con la que el modelo detecta contratos
atípicos: comparar cada uno contra el percentil 99 **de su propia modalidad de contratación**, no
contra el universo entero.

**Los controles atraparon un fallo real, y revelaron un hueco en ellos mismos.** Un cambio mal
puesto dejó la tabla principal en cero filas — y los 74 tests pasaron en verde, porque
verificaciones como «este campo no puede estar vacío» se cumplen por vacuidad cuando no hay ni
una fila. Añadí la que faltaba: comparar el conteo entre capas. Hoy son 75.

### Las cifras

| | |
|---|---|
| Universo publicado | 6.102.286 contratos |
| Lo que el proyecto analiza | 67.299 de obra e infraestructura |
| Valor contratado | $93,06 billones |
| Verificaciones automáticas | 75 |
| Concentración | Bogotá, 43,4 % del valor |
| Dato que el informe **no** publica | el porcentaje de pavimentación: el 83,2 % de los kilómetros de red vial no tiene la superficie informada en el origen, y publicarlo diría que el país está sin pavimentar cuando lo que pasa es que no se sabe |

---

Versión hablada para la entrevista: [`pitch.md`](pitch.md).
Informe: [`informe-secop-infraestructura.pdf`](informe-secop-infraestructura.pdf).
