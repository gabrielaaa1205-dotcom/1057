"""
Envio de correos automaticos via SMTP (libreria estandar de Python, sin
dependencias nuevas). Funciona con Gmail, Outlook, o cualquier proveedor de
correo transaccional que de credenciales SMTP (SendGrid, Resend, Mailgun,
etc. todos las ofrecen).

Se configura por variables de entorno (en Render: Settings -> Environment):
  SMTP_HOST          ej. smtp.gmail.com
  SMTP_PORT          ej. 587
  SMTP_USER          usuario/correo con el que se autentica
  SMTP_PASSWORD      contraseña o "app password"
  SMTP_FROM          correo que aparece como remitente (puede ser igual a SMTP_USER)
  NOTIFY_EMAILS      correos que reciben los avisos, separados por coma

Si estas variables no estan configuradas, send_email() simplemente no hace
nada (no rompe el flujo de despacho/recepcion por no tener el correo listo
todavia) -- solo deja un aviso en los logs del servidor.
"""
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def _config():
    host = os.environ.get("SMTP_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER"),
        "password": os.environ.get("SMTP_PASSWORD"),
        "from_addr": os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER"),
        "recipients": [e.strip() for e in os.environ.get("NOTIFY_EMAILS", "").split(",") if e.strip()],
    }


def send_email(subject, html_body, to=None):
    """Envia un correo. Si no hay configuracion SMTP o no hay destinatarios,
    no hace nada (retorna False) en vez de fallar la operacion que lo llamo."""
    cfg = _config()
    if not cfg:
        print(f"[email] SMTP no configurado, se omite el envio: {subject}")
        return False
    recipients = to or cfg["recipients"]
    if not recipients:
        print(f"[email] No hay destinatarios configurados (NOTIFY_EMAILS), se omite: {subject}")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["from_addr"]
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as server:
            server.starttls(context=context)
            if cfg["user"] and cfg["password"]:
                server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["from_addr"], recipients, msg.as_string())
        print(f"[email] Enviado a {recipients}: {subject}")
        return True
    except Exception as e:
        # Un correo que falla NUNCA debe tumbar un despacho/recepcion real --
        # se registra el error y se sigue.
        print(f"[email] ERROR enviando '{subject}': {e}")
        return False
