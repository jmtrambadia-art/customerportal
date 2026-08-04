import json
import os
import re
import sys
from datetime import datetime
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import mailer

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
PORT = int(os.environ.get("PORT", 8070))

STATUSES = ["received", "quoted", "in_progress", "dispatched", "completed", "cancelled"]

SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name):
    name = os.path.basename(name or "upload")
    name = SAFE_FILENAME_RE.sub("_", name)
    return name[-100:] or "upload"


class Handler(BaseHTTPRequestHandler):
    server_version = "MehulOrders/1.0"

    # ---------- low level helpers ----------

    def _send_json(self, status, payload, extra_headers=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
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

    def _get_cookie(self, name):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        c = cookies.SimpleCookie()
        c.load(raw)
        if name in c:
            return c[name].value
        return None

    def _current_user(self):
        token = self._get_cookie("mei_session")
        return db.get_user_from_session(token)

    def _require_user(self, role=None):
        user = self._current_user()
        if not user:
            self._send_json(401, {"error": "Not authenticated"})
            return None
        if role and user["role"] != role:
            self._send_json(403, {"error": "Forbidden"})
            return None
        return user

    def _set_session_cookie(self, token):
        c = cookies.SimpleCookie()
        c["mei_session"] = token
        c["mei_session"]["path"] = "/"
        c["mei_session"]["httponly"] = True
        c["mei_session"]["samesite"] = "Lax"
        c["mei_session"]["max-age"] = 7 * 24 * 3600
        return [("Set-Cookie", c["mei_session"].OutputString())]

    def _clear_session_cookie(self):
        c = cookies.SimpleCookie()
        c["mei_session"] = ""
        c["mei_session"]["path"] = "/"
        c["mei_session"]["max-age"] = 0
        return [("Set-Cookie", c["mei_session"].OutputString())]

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---------- routing ----------

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            return self._route_api("GET", path, parse_qs(parsed.query))
        return self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            return self._route_api("POST", parsed.path, {})
        self._send_json(404, {"error": "Not found"})

    def do_PATCH(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            return self._route_api("PATCH", parsed.path, {})
        self._send_json(404, {"error": "Not found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            return self._route_api("DELETE", parsed.path, {})
        self._send_json(404, {"error": "Not found"})

    def _route_api(self, method, path, query):
        try:
            if method == "POST" and path == "/api/login":
                return self.handle_login()
            if method == "POST" and path == "/api/logout":
                return self.handle_logout()
            if method == "GET" and path == "/api/me":
                return self.handle_me()
            if method == "GET" and path == "/api/requests":
                return self.handle_list_requests(query)
            if method == "POST" and path == "/api/requests":
                return self.handle_create_request()
            m = re.match(r"^/api/requests/(\d+)$", path)
            if method == "PATCH" and m:
                return self.handle_update_request(int(m.group(1)))
            if method == "GET" and path == "/api/customers":
                return self.handle_list_customers()
            if method == "POST" and path == "/api/customers":
                return self.handle_create_customer()
            m = re.match(r"^/api/customers/(\d+)$", path)
            if method == "GET" and m:
                return self.handle_get_customer(int(m.group(1)))
            if method == "PATCH" and m:
                return self.handle_update_customer(int(m.group(1)))
            if method == "DELETE" and m:
                return self.handle_delete_customer(int(m.group(1)))
            if method == "GET" and path.startswith("/api/uploads/"):
                return self.handle_serve_upload(path)
            if method == "GET" and path == "/api/backup":
                return self.handle_backup()
            return self._send_json(404, {"error": "Not found"})
        except Exception as e:
            self._send_json(500, {"error": f"Server error: {e}"})

    # ---------- static files ----------

    def _serve_static(self, path):
        if path == "/":
            path = "/login.html"
        safe_path = os.path.normpath(path).lstrip("/")
        full_path = os.path.join(STATIC_DIR, safe_path)
        if not full_path.startswith(STATIC_DIR) or not os.path.isfile(full_path):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return
        ctype = "text/html"
        if full_path.endswith(".css"):
            ctype = "text/css"
        elif full_path.endswith(".js"):
            ctype = "application/javascript"
        elif full_path.endswith(".json"):
            ctype = "application/json"
        elif full_path.endswith(".png"):
            ctype = "image/png"
        elif full_path.endswith(".svg"):
            ctype = "image/svg+xml"
        with open(full_path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_serve_upload(self, path):
        user = self._require_user()
        if not user:
            return
        filename = os.path.basename(path[len("/api/uploads/"):])
        full_path = os.path.join(UPLOADS_DIR, filename)
        if not os.path.isfile(full_path):
            return self._send_json(404, {"error": "Not found"})
        with open(full_path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---------- auth ----------

    def handle_login(self):
        body = self._read_json_body()
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        conn = db.get_conn()
        row = conn.execute("SELECT * FROM users WHERE username = ? AND active = 1", (username,)).fetchone()
        conn.close()
        if not row or not db.verify_password(password, row["password_hash"], row["salt"]):
            return self._send_json(401, {"error": "Invalid username or password"})
        token = db.create_session(row["id"])
        headers = self._set_session_cookie(token)
        self._send_json(
            200,
            {
                "id": row["id"],
                "username": row["username"],
                "role": row["role"],
                "company_name": row["company_name"],
            },
            extra_headers=headers,
        )

    def handle_logout(self):
        token = self._get_cookie("mei_session")
        if token:
            db.delete_session(token)
        self._send_json(200, {"ok": True}, extra_headers=self._clear_session_cookie())

    def handle_me(self):
        user = self._current_user()
        if not user:
            return self._send_json(401, {"error": "Not authenticated"})
        self._send_json(
            200,
            {
                "id": user["id"],
                "username": user["username"],
                "role": user["role"],
                "company_name": user["company_name"],
            },
        )

    # ---------- requests ----------

    def handle_list_requests(self, query):
        user = self._require_user()
        if not user:
            return
        conn = db.get_conn()
        if user["role"] == "admin":
            status = query.get("status", [None])[0]
            if status:
                rows = conn.execute(
                    "SELECT r.*, u.company_name, u.username AS customer_username "
                    "FROM requests r JOIN users u ON u.id = r.customer_id "
                    "WHERE r.status = ? ORDER BY r.created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT r.*, u.company_name, u.username AS customer_username "
                    "FROM requests r JOIN users u ON u.id = r.customer_id "
                    "ORDER BY r.created_at DESC"
                ).fetchall()
        else:
            rows = conn.execute(
                "SELECT r.*, u.company_name, u.username AS customer_username "
                "FROM requests r JOIN users u ON u.id = r.customer_id "
                "WHERE r.customer_id = ? ORDER BY r.created_at DESC",
                (user["id"],),
            ).fetchall()
        conn.close()
        self._send_json(200, [dict(r) for r in rows])

    def handle_create_request(self):
        user = self._require_user(role="customer")
        if not user:
            return

        file_path = None
        file_name = None

        body = self._read_json_body()
        material = (body.get("material") or "").strip()
        specs = body.get("specs") or ""
        quantity = body.get("quantity") or ""
        unit = body.get("unit") or ""
        notes = body.get("notes") or ""

        if not material:
            return self._send_json(400, {"error": "Material / product is required"})

        now = datetime.utcnow().isoformat()
        conn = db.get_conn()
        cur = conn.execute(
            "INSERT INTO requests (customer_id, material, specs, quantity, unit, notes, file_path, file_name, "
            "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'received', ?, ?)",
            (user["id"], material, specs, quantity, unit, notes, file_path, file_name, now, now),
        )
        conn.commit()
        req_id = cur.lastrowid
        conn.close()

        mailer.notify_new_request(user["company_name"] or user["username"], material, quantity, unit, req_id)

        self._send_json(201, {"id": req_id, "status": "received"})

    def handle_update_request(self, req_id):
        user = self._require_user(role="admin")
        if not user:
            return
        body = self._read_json_body()
        status = body.get("status")
        admin_notes = body.get("admin_notes")
        transport_name = body.get("transport_name")
        lr_number = body.get("lr_number")
        expected_dispatch_date = body.get("expected_dispatch_date")
        if status is not None and status not in STATUSES:
            return self._send_json(400, {"error": f"Invalid status. Must be one of {STATUSES}"})
        conn = db.get_conn()
        existing = conn.execute(
            "SELECT transport_name, expected_dispatch_date FROM requests WHERE id = ?", (req_id,)
        ).fetchone()
        if not existing:
            conn.close()
            return self._send_json(404, {"error": "Request not found"})

        prev_transport = (existing["transport_name"] or "").strip()
        prev_dispatch_date = (existing["expected_dispatch_date"] or "").strip()

        # Auto-advance status the first time transport or an expected dispatch date is filled in.
        # Transport being filled implies the goods have actually left, so it wins over the date rule.
        if transport_name is not None and transport_name.strip() and not prev_transport:
            status = "dispatched"
        elif expected_dispatch_date is not None and expected_dispatch_date.strip() and not prev_dispatch_date:
            status = "in_progress"

        fields = []
        values = []
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if admin_notes is not None:
            fields.append("admin_notes = ?")
            values.append(admin_notes)
        if transport_name is not None:
            fields.append("transport_name = ?")
            values.append(transport_name)
        if lr_number is not None:
            fields.append("lr_number = ?")
            values.append(lr_number)
        if expected_dispatch_date is not None:
            fields.append("expected_dispatch_date = ?")
            values.append(expected_dispatch_date)
        fields.append("updated_at = ?")
        values.append(datetime.utcnow().isoformat())
        values.append(req_id)
        conn.execute(f"UPDATE requests SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
        conn.close()
        self._send_json(200, {"ok": True})

    # ---------- customers (admin managed) ----------

    def handle_list_customers(self):
        user = self._require_user(role="admin")
        if not user:
            return
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT id, username, company_name, contact_name, phone, active, created_at "
            "FROM users WHERE role = 'customer' ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        self._send_json(200, [dict(r) for r in rows])

    def handle_create_customer(self):
        user = self._require_user(role="admin")
        if not user:
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

        conn = db.get_conn()
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            conn.close()
            return self._send_json(409, {"error": "Username already exists"})
        pw_hash, salt = db.hash_password(password)
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, salt, role, company_name, contact_name, phone, active, created_at) "
            "VALUES (?, ?, ?, 'customer', ?, ?, ?, 1, ?)",
            (username, pw_hash, salt, company_name, contact_name, phone, datetime.utcnow().isoformat()),
        )
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        self._send_json(201, {"id": new_id, "username": username})

    def handle_get_customer(self, customer_id):
        user = self._require_user(role="admin")
        if not user:
            return
        conn = db.get_conn()
        row = conn.execute(
            "SELECT id, username, company_name, contact_name, phone, active, created_at "
            "FROM users WHERE id = ? AND role = 'customer'",
            (customer_id,),
        ).fetchone()
        conn.close()
        if not row:
            return self._send_json(404, {"error": "Customer not found"})
        self._send_json(200, dict(row))

    def handle_update_customer(self, customer_id):
        user = self._require_user(role="admin")
        if not user:
            return
        body = self._read_json_body()
        conn = db.get_conn()
        existing = conn.execute(
            "SELECT id FROM users WHERE id = ? AND role = 'customer'", (customer_id,)
        ).fetchone()
        if not existing:
            conn.close()
            return self._send_json(404, {"error": "Customer not found"})

        fields = []
        values = []

        if "company_name" in body:
            company_name = (body.get("company_name") or "").strip()
            if not company_name:
                conn.close()
                return self._send_json(400, {"error": "Company name is required"})
            fields.append("company_name = ?")
            values.append(company_name)
        if "contact_name" in body:
            fields.append("contact_name = ?")
            values.append((body.get("contact_name") or "").strip())
        if "phone" in body:
            fields.append("phone = ?")
            values.append((body.get("phone") or "").strip())
        if "username" in body:
            username = (body.get("username") or "").strip()
            if not username:
                conn.close()
                return self._send_json(400, {"error": "Username is required"})
            dup = conn.execute(
                "SELECT id FROM users WHERE username = ? AND id != ?", (username, customer_id)
            ).fetchone()
            if dup:
                conn.close()
                return self._send_json(409, {"error": "Username already exists"})
            fields.append("username = ?")
            values.append(username)
        if body.get("password"):
            password = body["password"]
            if len(password) < 6:
                conn.close()
                return self._send_json(400, {"error": "Password must be at least 6 characters"})
            pw_hash, salt = db.hash_password(password)
            fields.append("password_hash = ?")
            values.append(pw_hash)
            fields.append("salt = ?")
            values.append(salt)

        if not fields:
            conn.close()
            return self._send_json(400, {"error": "Nothing to update"})

        values.append(customer_id)
        conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
        conn.close()
        self._send_json(200, {"ok": True})

    def handle_delete_customer(self, customer_id):
        user = self._require_user(role="admin")
        if not user:
            return
        conn = db.get_conn()
        existing = conn.execute(
            "SELECT id FROM users WHERE id = ? AND role = 'customer'", (customer_id,)
        ).fetchone()
        if not existing:
            conn.close()
            return self._send_json(404, {"error": "Customer not found"})
        conn.execute("DELETE FROM requests WHERE customer_id = ?", (customer_id,))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (customer_id,))
        conn.execute("DELETE FROM users WHERE id = ? AND role = 'customer'", (customer_id,))
        conn.commit()
        conn.close()
        self._send_json(200, {"ok": True})

    def handle_backup(self):
        user = self._require_user(role="admin")
        if not user:
            return
        if not os.path.isfile(db.DB_PATH):
            return self._send_json(404, {"error": "No data yet"})
        with open(db.DB_PATH, "rb") as f:
            data = f.read()
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="mehul_orders_backup_{stamp}.db"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    db.init_db()
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Mehul Orders server running at http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
