import os
import json
import functools
from datetime import datetime
from difflib import SequenceMatcher

from flask import session, g, redirect, url_for, request, flash, current_app
from werkzeug.utils import secure_filename

from db import get_db

# ---------------------------------------------------------------------------
# India-wide location structure: State -> District -> [Cities]
# This is a representative sample (not exhaustive) so the app is not
# hard-coded to only Karnataka/Mangaluru, per the project brief.
# ---------------------------------------------------------------------------
INDIA_LOCATIONS = {
    "Karnataka": {
        "Dakshina Kannada": ["Mangaluru", "Ullal", "Bantwal"],
        "Bengaluru Urban": ["Bengaluru"],
        "Udupi": ["Udupi", "Manipal"],
        "Mysuru": ["Mysuru"],
    },
    "Maharashtra": {
        "Mumbai City": ["Mumbai"],
        "Pune": ["Pune"],
        "Nagpur": ["Nagpur"],
    },
    "Delhi": {
        "New Delhi": ["New Delhi", "Connaught Place", "Dwarka"],
    },
    "Tamil Nadu": {
        "Chennai": ["Chennai"],
        "Coimbatore": ["Coimbatore"],
    },
    "Kerala": {
        "Ernakulam": ["Kochi"],
        "Thiruvananthapuram": ["Thiruvananthapuram"],
    },
    "Telangana": {
        "Hyderabad": ["Hyderabad", "Secunderabad"],
    },
    "West Bengal": {
        "Kolkata": ["Kolkata"],
    },
    "Uttar Pradesh": {
        "Lucknow": ["Lucknow"],
        "Gautam Buddh Nagar": ["Noida"],
    },
    "Gujarat": {
        "Ahmedabad": ["Ahmedabad"],
        "Surat": ["Surat"],
    },
    "Rajasthan": {
        "Jaipur": ["Jaipur"],
    },
}


def get_states():
    return sorted(INDIA_LOCATIONS.keys())


def get_districts(state):
    return sorted(INDIA_LOCATIONS.get(state, {}).keys())


def get_cities(state, district):
    return sorted(INDIA_LOCATIONS.get(state, {}).get(district, []))


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        if g.user["is_blocked"]:
            flash("Your account has been suspended. Contact support.", "danger")
            return redirect(url_for("auth.logout"))
        return view(**kwargs)
    return wrapped


def admin_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        if g.user["role"] != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("main.home"))
        return view(**kwargs)
    return wrapped


def load_logged_in_user():
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        g.user = get_db().execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


# ---------------------------------------------------------------------------
# File upload helpers
# ---------------------------------------------------------------------------
def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in current_app.config["ALLOWED_EXTENSIONS"]
    )


def save_uploaded_image(file_storage, prefix):
    """Save an uploaded image and return its relative static path, or None."""
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        flash("Unsupported image type. Please upload PNG, JPG or WEBP.", "warning")
        return None
    filename = secure_filename(file_storage.filename)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    final_name = f"{prefix}_{timestamp}_{filename}"
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_dir, exist_ok=True)
    file_storage.save(os.path.join(upload_dir, final_name))
    return f"uploads/{final_name}"


# ---------------------------------------------------------------------------
# Private ownership details (JSON blob helpers)
# ---------------------------------------------------------------------------
PRIVATE_DETAIL_FIELDS = [
    ("unique_mark", "Describe a unique scratch, mark, or damage on the item."),
    ("sticker_or_design", "Was there a sticker, cover, or special design on it?"),
    ("hidden_feature", "Is there a hidden feature, lock code, or internal detail only the owner would know?"),
    ("case_or_cover_details", "Describe the case, cover, or pouch it was in, if any."),
    ("unique_accessory", "Was there a unique accessory attached (charm, strap, tag, etc.)?"),
    ("serial_number", "Do you know the serial number / IMEI / unique ID (if applicable)?"),
    ("distinctive_contents", "If it's a bag/wallet, what distinctive contents were inside?"),
]


def parse_private_details(form):
    """Build the private-details JSON blob from a submitted report-lost form."""
    details = {}
    for field, _ in PRIVATE_DETAIL_FIELDS:
        value = (form.get(field) or "").strip()
        if value:
            details[field] = value
    return json.dumps(details)


def get_verification_questions(private_details_json):
    """Turn stored private details into (question, expected_answer) pairs."""
    try:
        details = json.loads(private_details_json or "{}")
    except (json.JSONDecodeError, TypeError):
        details = {}
    field_to_question = dict(PRIVATE_DETAIL_FIELDS)
    pairs = []
    for field, expected_answer in details.items():
        question = field_to_question.get(field, f"Describe: {field}")
        pairs.append((question, expected_answer))
    return pairs


def answer_similarity(a, b):
    """Simple, dependency-free text similarity for comparing claimant answers."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


# ---------------------------------------------------------------------------
# Notifications & audit log
# ---------------------------------------------------------------------------
def notify(user_id, message, ntype="system", link=None):
    db = get_db()
    db.execute(
        "INSERT INTO notifications (user_id, message, type, link) VALUES (?, ?, ?, ?)",
        (user_id, message, ntype, link),
    )
    db.commit()


def log_action(user_id, action, target_type=None, target_id=None, details=None):
    db = get_db()
    db.execute(
        "INSERT INTO audit_logs (user_id, action, target_type, target_id, details) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, action, target_type, target_id, details),
    )
    db.commit()


def unread_notification_count(user_id):
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0",
        (user_id,),
    ).fetchone()
    return row["c"] if row else 0
