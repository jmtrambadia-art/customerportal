"""One-off script: creates the initial admin account in Firebase Auth + Firestore.
Run once after setting up the Firebase project. Safe to re-run (idempotent)."""
import os
import sys

import firebase_admin
from firebase_admin import auth, credentials, firestore

SECRETS_PATH = os.path.join(os.path.dirname(__file__), "secrets", "firebase-adminsdk.json")

ADMIN_EMAIL = "admin@mehulelectro.local"
ADMIN_PASSWORD = "admin123"
ADMIN_USERNAME = "admin"
ADMIN_COMPANY = "Mehul Electro Insulating Industries"


def main():
    cred = credentials.Certificate(SECRETS_PATH)
    firebase_admin.initialize_app(cred)
    db = firestore.client()

    try:
        user = auth.get_user_by_email(ADMIN_EMAIL)
        print(f"Admin user already exists: {user.uid}")
    except auth.UserNotFoundError:
        user = auth.create_user(email=ADMIN_EMAIL, password=ADMIN_PASSWORD, display_name=ADMIN_USERNAME)
        print(f"Created admin user: {user.uid}")

    auth.set_custom_user_claims(user.uid, {"role": "admin"})
    print("Set custom claim role=admin")

    db.collection("customers").document(user.uid).set({
        "username": ADMIN_USERNAME,
        "companyName": ADMIN_COMPANY,
        "contactName": "",
        "phone": "",
        "role": "admin",
        "active": True,
    }, merge=True)
    print("Wrote admin profile doc to Firestore")
    print(f"\nLogin with email: {ADMIN_EMAIL} / password: {ADMIN_PASSWORD}")


if __name__ == "__main__":
    sys.exit(main())
