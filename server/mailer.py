import json
import os
import smtplib
import ssl
from email.message import EmailMessage

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def _load_config():
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    smtp = cfg.get("smtp")
    if not smtp or not smtp.get("host") or not smtp.get("user") or not smtp.get("password"):
        return None
    return smtp


def notify_new_request(company_name, material, quantity, unit, req_id):
    smtp = _load_config()
    if not smtp:
        return  # notifications not configured; skip silently
    to_addr = smtp.get("notify_to") or smtp.get("user")
    msg = EmailMessage()
    msg["Subject"] = f"New order request #{req_id} from {company_name}"
    msg["From"] = smtp["user"]
    msg["To"] = to_addr
    msg.set_content(
        f"New customer requirement submitted.\n\n"
        f"Customer: {company_name}\n"
        f"Material: {material}\n"
        f"Quantity: {quantity} {unit or ''}\n\n"
        f"Open the admin dashboard to view full details and respond."
    )
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp["host"], smtp.get("port", 587)) as server:
            server.starttls(context=context)
            server.login(smtp["user"], smtp["password"])
            server.send_message(msg)
    except Exception as e:
        print(f"[mailer] failed to send notification: {e}")
