"""Seed an admin account on first run. Credentials come from environment variables."""
import os
import secrets
from werkzeug.security import generate_password_hash
from db import get_db

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@lostfound.local").lower()


def seed_admin():
    db = get_db()
    if db.execute("SELECT id FROM users WHERE email = ?", (ADMIN_EMAIL,)).fetchone():
        return
    password = os.environ.get("ADMIN_PASSWORD")
    generated = password is None
    if generated:
        password = secrets.token_urlsafe(10)
    db.execute(
        "INSERT INTO users (name, email, phone, password_hash, role, verified) "
        "VALUES (?, ?, ?, ?, 'admin', 1)",
        ("Platform Admin", ADMIN_EMAIL, "0000000000", generate_password_hash(password)),
    )
    db.commit()
    if generated:
        print(f"[seed] Admin created: {ADMIN_EMAIL} / {password}  (shown once, save it now)")
    else:
        print("[seed] Admin created from ADMIN_EMAIL / ADMIN_PASSWORD.")