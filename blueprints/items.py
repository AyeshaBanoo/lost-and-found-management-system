from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app

from db import get_db
from utils import (
    login_required, get_states, get_districts, get_cities,
    save_uploaded_image, parse_private_details, log_action,
    PRIVATE_DETAIL_FIELDS,
)
from matching import generate_matches_for_lost_item, generate_matches_for_found_item

bp = Blueprint("items", __name__, url_prefix="")


def _parse_coord(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


@bp.route("/report-lost", methods=("GET", "POST"))
@login_required
def report_lost():
    categories = current_app.config["ITEM_CATEGORIES"]

    if request.method == "POST":
        form = request.form
        required = ["item_name", "category", "state", "district", "city", "date_lost"]
        missing = [f for f in required if not form.get(f)]
        if missing:
            flash("Please fill in all required fields, and pick a location from the suggestions list.", "danger")
            return render_template("items/report_lost.html", categories=categories,
                                    states=get_states(), form=form, detail_fields=PRIVATE_DETAIL_FIELDS)

        image_file = request.files.get("image")
        image_path = save_uploaded_image(image_file, "lost")
        private_json = parse_private_details(form)
        lat = _parse_coord(form.get("latitude"))
        lon = _parse_coord(form.get("longitude"))

        db = get_db()
        cursor = db.execute(
            """INSERT INTO lost_items
               (user_id, item_name, category, description, brand, model, colour,
                state, district, city, area, latitude, longitude, date_lost, time_lost, image_path,
                private_ownership_details, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'LOST')""",
            (
                g.user["id"], form["item_name"], form["category"], form.get("description"),
                form.get("brand"), form.get("model"), form.get("colour"),
                form["state"], form["district"], form["city"], form.get("area"), lat, lon,
                form["date_lost"], form.get("time_lost"), image_path, private_json,
            ),
        )
        db.commit()
        lost_id = cursor.lastrowid
        log_action(g.user["id"], "REPORT_LOST", "lost_items", lost_id)

        generate_matches_for_lost_item(lost_id)

        restricted = current_app.config["RESTRICTED_CATEGORIES"].get(form["category"])
        if restricted:
            flash(restricted, "info")
        flash("Lost item report submitted. We're checking it against found reports now.", "success")
        return redirect(url_for("matches.view_matches", lost_item_id=lost_id))

    return render_template("items/report_lost.html", categories=categories,
                            states=get_states(), form={}, detail_fields=PRIVATE_DETAIL_FIELDS)


@bp.route("/report-found", methods=("GET", "POST"))
@login_required
def report_found():
    categories = current_app.config["ITEM_CATEGORIES"]

    if request.method == "POST":
        form = request.form
        required = ["item_name", "category", "state", "district", "city", "date_found"]
        missing = [f for f in required if not form.get(f)]
        if missing:
            flash("Please fill in all required fields, and pick a location from the suggestions list.", "danger")
            return render_template("items/report_found.html", categories=categories,
                                    states=get_states(), form=form)

        image_file = request.files.get("image")
        image_path = save_uploaded_image(image_file, "found")
        lat = _parse_coord(form.get("latitude"))
        lon = _parse_coord(form.get("longitude"))

        db = get_db()
        cursor = db.execute(
            """INSERT INTO found_items
               (finder_id, item_name, category, description, brand, model, colour,
                state, district, city, area, latitude, longitude, date_found, time_found, image_path, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'FOUND')""",
            (
                g.user["id"], form["item_name"], form["category"], form.get("description"),
                form.get("brand"), form.get("model"), form.get("colour"),
                form["state"], form["district"], form["city"], form.get("area"), lat, lon,
                form["date_found"], form.get("time_found"), image_path,
            ),
        )
        db.commit()
        found_id = cursor.lastrowid
        log_action(g.user["id"], "REPORT_FOUND", "found_items", found_id)

        generate_matches_for_found_item(found_id)

        flash(
            "Found item report submitted — thank you! If it's valuable, please also consider "
            "handing it to a nearby authority (police / transport desk / establishment).",
            "success",
        )
        return redirect(url_for("items.item_detail", item_type="found", item_id=found_id))

    return render_template("items/report_found.html", categories=categories,
                            states=get_states(), form={})


@bp.route("/api/districts/<state>")
def api_districts(state):
    return {"districts": get_districts(state)}


@bp.route("/api/cities/<state>/<district>")
def api_cities(state, district):
    return {"cities": get_cities(state, district)}


@bp.route("/item/<item_type>/<int:item_id>")
def item_detail(item_type, item_id):
    db = get_db()
    if item_type == "lost":
        item = db.execute(
            "SELECT li.*, u.name AS owner_name FROM lost_items li "
            "JOIN users u ON u.id = li.user_id WHERE li.id = ?", (item_id,)
        ).fetchone()
    elif item_type == "found":
        item = db.execute(
            "SELECT fi.*, u.name AS finder_name FROM found_items fi "
            "JOIN users u ON u.id = fi.finder_id WHERE fi.id = ?", (item_id,)
        ).fetchone()
    else:
        return redirect(url_for("main.home"))

    if item is None:
        flash("That report could not be found.", "warning")
        return redirect(url_for("main.home"))

    is_owner = g.user and (
        (item_type == "lost" and g.user["id"] == item["user_id"])
        or (item_type == "found" and g.user["id"] == item["finder_id"])
    )

    # Once a claim on this found item is approved, the finder (and only the
    # finder) can see the claimant's contact so they can arrange the handover.
    approved_claim = None
    if item_type == "found" and is_owner and item["status"] in ("APPROVED", "RETURNED"):
        approved_claim = db.execute(
            """SELECT c.*, u.name AS claimant_name, u.phone AS claimant_phone,
                      u.email AS claimant_email
               FROM claims c JOIN users u ON u.id = c.claimant_id
               WHERE c.found_item_id = ? AND c.status = 'APPROVED'""",
            (item_id,),
        ).fetchone()

    is_high_value = item["category"] in current_app.config["HIGH_VALUE_CATEGORIES"]

    return render_template(
        "items/item_detail.html", item=item, item_type=item_type, is_owner=is_owner,
        approved_claim=approved_claim, is_high_value=is_high_value,
    )


@bp.route("/my-reports")
@login_required
def my_reports():
    db = get_db()
    my_lost = db.execute(
        "SELECT * FROM lost_items WHERE user_id = ? ORDER BY created_at DESC", (g.user["id"],)
    ).fetchall()
    my_found = db.execute(
        "SELECT * FROM found_items WHERE finder_id = ? ORDER BY created_at DESC", (g.user["id"],)
    ).fetchall()
    return render_template("items/my_reports.html", my_lost=my_lost, my_found=my_found)


@bp.route("/item/lost/<int:item_id>/mark-returned", methods=("POST",))
@login_required
def mark_returned(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM lost_items WHERE id = ?", (item_id,)).fetchone()
    if item is None or item["user_id"] != g.user["id"]:
        flash("You can only update your own reports.", "danger")
        return redirect(url_for("items.my_reports"))
    db.execute("UPDATE lost_items SET status = 'RETURNED' WHERE id = ?", (item_id,))
    db.commit()
    log_action(g.user["id"], "MARK_RETURNED", "lost_items", item_id)
    flash("Great news — marked as recovered!", "success")
    return redirect(url_for("items.my_reports"))