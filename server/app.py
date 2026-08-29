import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import firebase_admin
from firebase_admin import auth, credentials, firestore

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")
PORT = int(os.environ.get("PORT", 8070))

CUSTOMER_EMAIL_DOMAIN = "mehulelectro.local"


def _init_firebase():
    candidates = [
        os.path.join(os.path.dirname(__file__), "secrets", "firebase-adminsdk.json"),
        "/etc/secrets/firebase-adminsdk.json",
        os.path.join(BASE_DIR, "firebase-adminsdk.json"),
    ]
    key_path = next((p for p in candidates if os.path.isfile(p)), None)
    if not key_path:
        raise RuntimeError("firebase-adminsdk.json not found in any known location")
    cred = credentials.Certificate(key_path)
    firebase_admin.initialize_app(cred)


_init_firebase()
db = firestore.client()


class Handler(BaseHTTPRequestHandler):
    server_version = "MehulOrdersAdmin/2.0"

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _require_admin(self):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            self._send_json(401, {"error": "Missing bearer token"})
            return None
        token = header[len("Bearer "):]
        try:
            decoded = auth.verify_id_token(token)
        except Exception:
            self._send_json(401, {"error": "Invalid or expired token"})
            return None
        if decoded.get("role") != "admin":
            self._send_json(403, {"error": "Admin only"})
            return None
        return decoded

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self._send_json(200, {"ok": True})
        self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/admin/customers":
            return self.handle_create_customer()
        self._send_json(404, {"error": "Not found"})

    def do_PATCH(self):
        path = urlparse(self.path).path
        if path.startswith("/api/admin/customers/"):
            uid = path.rsplit("/", 1)[-1]
            return self.handle_update_customer(uid)
        self._send_json(404, {"error": "Not found"})

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/admin/customers/"):
            uid = path.rsplit("/", 1)[-1]
            return self.handle_delete_customer(uid)
        self._send_json(404, {"error": "Not found"})

    # ---------- handlers ----------

    def handle_create_customer(self):
        if not self._require_admin():
            return
        body = self._read_json_body()
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        company_name = (body.get("company_name") or "").strip()
        contact_name = (body.get("contact_name") or "").strip()
        phone = (body.get("phone") or "").strip()

        if not username or not password or not company_name:
            return self._send_json(400, {"error": "username, password, and company_name are required"})
        if len(password) < 6:
            return self._send_json(400, {"error": "Password must be at least 6 characters"})

        email = f"{username}@{CUSTOMER_EMAIL_DOMAIN}"
        try:
            user = auth.create_user(email=email, password=password, display_name=username)
        except auth.EmailAlreadyExistsError:
            return self._send_json(409, {"error": "Username already exists"})

        auth.set_custom_user_claims(user.uid, {"role": "customer"})
        db.collection("customers").document(user.uid).set({
            "username": username,
            "companyName": company_name,
            "contactName": contact_name,
            "phone": phone,
            "role": "customer",
            "active": True,
        })
        self._send_json(201, {"uid": user.uid, "username": username})

    def handle_update_customer(self, uid):
        if not self._require_admin():
            return
        body = self._read_json_body()
        new_password = body.get("password")
        if new_password:
            if len(new_password) < 6:
                return self._send_json(400, {"error": "Password must be at least 6 characters"})
            try:
                auth.update_user(uid, password=new_password)
            except auth.UserNotFoundError:
                return self._send_json(404, {"error": "Customer not found"})

        updates = {}
        for key, field in (("company_name", "companyName"), ("contact_name", "contactName"), ("phone", "phone")):
            if key in body:
                updates[field] = (body.get(key) or "").strip()
        if updates:
            db.collection("customers").document(uid).update(updates)
        self._send_json(200, {"ok": True})

    def handle_delete_customer(self, uid):
        if not self._require_admin():
            return
        try:
            auth.delete_user(uid)
        except auth.UserNotFoundError:
            pass
        db.collection("customers").document(uid).delete()
        requests_ref = db.collection("requests").where("customerId", "==", uid)
        for doc in requests_ref.stream():
            doc.reference.delete()
        self._send_json(200, {"ok": True})


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Mehul Orders admin API listening on :{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
