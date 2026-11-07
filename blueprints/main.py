from flask import Blueprint, render_template, g, redirect, url_for, flash

from db import get_db
from utils import login_required, get_states

bp = Blueprint("main", __name__, url_prefix="")


@bp.route("/")
def home():
    db = get_db()
    stats = {
        "lost": db.execute("SELECT COUNT(*) c FROM lost_items").fetchone()["c"],
        "found": db.execute("SELECT COUNT(*) c FROM found_items").fetchone()["c"],
        "returned": db.execute("SELECT COUNT(*) c FROM lost_items WHERE status = 'RETURNED'").fetchone()["c"],
        "matches": db.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"],
    }
    recent_lost = db.execute(
        "SELECT * FROM lost_items ORDER BY created_at DESC LIMIT 4"
    ).fetchall()
    recent_found = db.execute(
        "SELECT * FROM found_items ORDER BY created_at DESC LIMIT 4"
    ).fetchall()
    return render_template(
        "home.html", stats=stats, recent_lost=recent_lost, recent_found=recent_found,
        states=get_states(),
    )


@bp.route("/profile")
@login_required
def profile():
    db = get_db()
    my_lost = db.execute(
        "SELECT * FROM lost_items WHERE user_id = ? ORDER BY created_at DESC", (g.user["id"],)
    ).fetchall()
    my_found = db.execute(
        "SELECT * FROM found_items WHERE finder_id = ? ORDER BY created_at DESC", (g.user["id"],)
    ).fetchall()
    return render_template("profile.html", my_lost=my_lost, my_found=my_found)


@bp.route("/notifications")
@login_required
def notifications():
    db = get_db()
    notifs = db.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 100",
        (g.user["id"],),
    ).fetchall()
    db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (g.user["id"],))
    db.commit()
    return render_template("notifications.html", notifications=notifs)
