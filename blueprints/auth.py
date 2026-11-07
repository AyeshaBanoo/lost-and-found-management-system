import re
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_db
from utils import log_action

bp = Blueprint("auth", __name__, url_prefix="")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.route("/register", methods=("GET", "POST"))
def register():
    if g.user:
        return redirect(url_for("main.home"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        error = None
        if not name or not email or not password:
            error = "Name, email and password are required."
        elif not EMAIL_RE.match(email):
            error = "Please enter a valid email address."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm:
            error = "Passwords do not match."

        db = get_db()
        if error is None:
            existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                error = "An account with that email already exists."

        if error:
            flash(error, "danger")
            return render_template("auth/register.html", form=request.form)

        db.execute(
            "INSERT INTO users (name, email, phone, password_hash, role, verified) "
            "VALUES (?, ?, ?, ?, 'user', 1)",
            (name, email, phone, generate_password_hash(password)),
        )
        db.commit()
        flash("Account created successfully! You can now log in. (Demo: email/OTP verification is auto-approved.)", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form={})


@bp.route("/login", methods=("GET", "POST"))
def login():
    if g.user:
        return redirect(url_for("main.home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        error = None
        if user is None or not check_password_hash(user["password_hash"], password):
            error = "Incorrect email or password."
        elif user["is_blocked"]:
            error = "This account has been suspended. Please contact support."

        if error:
            flash(error, "danger")
            return render_template("auth/login.html")

        session.clear()
        session["user_id"] = user["id"]
        log_action(user["id"], "LOGIN")
        flash(f"Welcome back, {user['name']}!", "success")
        next_url = request.args.get("next")
        return redirect(next_url or url_for("main.home"))

    return render_template("auth/login.html")


@bp.route("/logout")
def logout():
    if g.user:
        log_action(g.user["id"], "LOGOUT")
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.home"))
