"""Aviso por correo cuando una tarea del DAG falla.

El correo no es el destino final: lo recoge un flujo de Power Automate que
notifica al movil y escribe una fila en el historico de incidentes. Por eso el
ASUNTO es un contrato y no decoracion. El flujo filtra por

    SECOP pipeline FALLO

asi que ese prefijo no se cambia sin cambiar tambien el filtro del flujo.

Por que correo y no una llamada HTTP directa al flujo, que seria instantanea:
el disparador "Cuando se recibe una solicitud HTTP" de Power Automate es un
conector PREMIUM, y la licencia de Microsoft 365 solo cubre los estandar. El
correo es un disparador estandar. El precio es la latencia: el flujo consulta
el buzon cada pocos minutos en vez de enterarse al instante.

Configuracion, via variables de entorno (ver orquestacion/.env.ejemplo):

    ALERTA_SMTP_HOST      smtp.gmail.com
    ALERTA_SMTP_PUERTO    587
    ALERTA_SMTP_USUARIO   remitente
    ALERTA_SMTP_CLAVE     contrasena de aplicacion, no la del correo
    ALERTA_DESTINO        el buzon que vigila el flujo

Si falta cualquiera, no se manda nada y se deja constancia en el log. Un
pipeline sin alertas configuradas tiene que seguir corriendo.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)

ASUNTO_BASE = "SECOP pipeline FALLO"

# El enlace al log de la tarea. En local apunta al Airflow del compose.
BASE_UI = os.environ.get("ALERTA_BASE_UI", "http://localhost:8080")

VARIABLES = ("ALERTA_SMTP_HOST", "ALERTA_SMTP_USUARIO",
             "ALERTA_SMTP_CLAVE", "ALERTA_DESTINO")


def _cuerpo(context: dict) -> str:
    """Arma el cuerpo. Mismo formato que se uso para probar el flujo."""
    ti = context.get("task_instance")
    dag_id = getattr(ti, "dag_id", "secop_pipeline")
    task_id = getattr(ti, "task_id", "desconocida")
    run_id = context.get("run_id") or getattr(ti, "run_id", "desconocida")
    intento = getattr(ti, "try_number", "?")
    error = context.get("exception")

    enlace = f"{BASE_UI}/dags/{dag_id}/runs/{run_id}/tasks/{task_id}"
    return (
        f"DAG: {dag_id}\n"
        f"Tarea: {task_id}\n"
        f"Estado: failed\n"
        f"Intento: {intento}\n"
        f"Corrida: {run_id}\n"
        f"Error: {error}\n"
        f"Log: {enlace}\n"
    )


def avisar_fallo(context: dict) -> None:
    """on_failure_callback: corre cuando la tarea agoto sus reintentos.

    Airflow distingue `on_retry_callback` de `on_failure_callback`. Este es el
    segundo, asi que `descargar` fallando su primer intento NO avisa: solo
    avisa si se queda sin reintentos. De otro modo el canal se llenaria de
    falsas alarmas y dejarias de mirarlo, que es como mueren las alertas.

    Nunca lanza. Si el aviso falla, la tarea ya fallo por su propia razon y
    enmascararla con un error de SMTP seria mucho peor que no avisar.
    """
    try:
        faltan = [v for v in VARIABLES if not os.environ.get(v)]
        if faltan:
            log.warning("No se manda el aviso: falta configurar %s",
                        ", ".join(faltan))
            return

        ti = context.get("task_instance")
        task_id = getattr(ti, "task_id", "desconocida")

        msg = EmailMessage()
        msg["Subject"] = f"{ASUNTO_BASE} - {task_id}"
        msg["From"] = os.environ["ALERTA_SMTP_USUARIO"]
        msg["To"] = os.environ["ALERTA_DESTINO"]
        msg.set_content(_cuerpo(context))

        puerto = int(os.environ.get("ALERTA_SMTP_PUERTO", "587"))
        with smtplib.SMTP(os.environ["ALERTA_SMTP_HOST"], puerto,
                          timeout=30) as s:
            s.starttls()
            s.login(os.environ["ALERTA_SMTP_USUARIO"],
                    os.environ["ALERTA_SMTP_CLAVE"])
            s.send_message(msg)

        log.info("Aviso de fallo enviado a %s", os.environ["ALERTA_DESTINO"])

    except Exception:  # noqa: BLE001 - a proposito: avisar nunca puede romper
        log.exception("No se pudo enviar el aviso de fallo")
