import sqlite3
import os
import secrets
import hashlib
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "mehul_orders.db")


def get_conn():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000)
    return digest.hex(), salt


def verify_password(password, password_hash, salt):
    digest, _ = hash_password(password, salt)
    return secrets.compare_digest(digest, password_hash)


def init_db():
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','customer')),
            company_name TEXT,
            contact_name TEXT,
            phone TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            expires_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL REFERENCES users(id),
            material TEXT NOT NULL,
            specs TEXT,
            quantity TEXT,
            unit TEXT,
            notes TEXT,
            file_path TEXT,
            file_name TEXT,
            status TEXT NOT NULL DEFAULT 'received',
            admin_notes TEXT,
            transport_name TEXT,
            lr_number TEXT,
            expected_dispatch_date TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.commit()

    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(requests)").fetchall()}
    if "transport_name" not in existing_cols:
        conn.execute("ALTER TABLE requests ADD COLUMN transport_name TEXT")
    if "lr_number" not in existing_cols:
        conn.execute("ALTER TABLE requests ADD COLUMN lr_number TEXT")
    if "expected_dispatch_date" not in existing_cols:
        conn.execute("ALTER TABLE requests ADD COLUMN expected_dispatch_date TEXT")
    conn.commit()

    admin = conn.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
    if not admin:
        pw_hash, salt = hash_password("admin123")
        conn.execute(
            "INSERT INTO users (username, password_hash, salt, role, company_name, active, created_at) "
            "VALUES (?, ?, ?, 'admin', 'Mehul Electro Insulating Industries', 1, ?)",
            ("admin", pw_hash, salt, datetime.utcnow().isoformat()),
        )
        conn.commit()
        print("=" * 60)
        print("Created default admin account:")
        print("  username: admin")
        print("  password: admin123")
        print("Please log in and consider this a first-run credential.")
        print("=" * 60)
    conn.close()


def create_session(user_id, days=7):
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat()
    conn = get_conn()
    conn.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)", (token, user_id, expires_at))
    conn.commit()
    conn.close()
    return token


def get_user_from_session(token):
    if not token:
        return None
    conn = get_conn()
    row = conn.execute(
        "SELECT s.expires_at, u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
        (token,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
        return None
    return dict(row)


def delete_session(token):
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()
