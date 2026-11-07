from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify

from db import get_db
from utils import admin_required, notify, log_action, get_verification_questions

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/")
@admin_required
def dashboard():
    db = get_db()
    stats = {
        "total_lost": db.execute("SELECT COUNT(*) c FROM lost_items").fetchone()["c"],
        "total_found": db.execute("SELECT COUNT(*) c FROM found_items").fetchone()["c"],
        "potential_matches": db.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"],
        "pending_claims": db.execute(
            "SELECT COUNT(*) c FROM claims WHERE status IN ('PENDING','UNDER_REVIEW','MORE_EVIDENCE')"
        ).fetchone()["c"],
        "approved_claims": db.execute("SELECT COUNT(*) c FROM claims WHERE status = 'APPROVED'").fetchone()["c"],
        "rejected_claims": db.execute("SELECT COUNT(*) c FROM claims WHERE status = 'REJECTED'").fetchone()["c"],
        "returned": db.execute("SELECT COUNT(*) c FROM lost_items WHERE status = 'RETURNED'").fetchone()["c"],
        "flagged": db.execute(
            "SELECT (SELECT COUNT(*) FROM lost_items WHERE is_flagged=1) + "
            "(SELECT COUNT(*) FROM found_items WHERE is_flagged=1) AS c"
        ).fetchone()["c"],
    }
    recent_claims = db.execute(
        """SELECT c.*, fi.item_name AS found_item_name FROM claims c
           JOIN found_items fi ON fi.id = c.found_item_id
           ORDER BY c.created_at DESC LIMIT 6"""
    ).fetchall()
    return render_template("admin/dashboard.html", stats=stats, recent_claims=recent_claims)


@bp.route("/analytics-data")
@admin_required
def analytics_data():
    db = get_db()
    by_category = db.execute(
        "SELECT category, COUNT(*) c FROM (SELECT category FROM lost_items UNION ALL "
        "SELECT category FROM found_items) GROUP BY category ORDER BY c DESC"
    ).fetchall()
    by_state = db.execute(
        "SELECT state, COUNT(*) c FROM (SELECT state FROM lost_items UNION ALL "
        "SELECT state FROM found_items) WHERE state IS NOT NULL GROUP BY state ORDER BY c DESC LIMIT 10"
    ).fetchall()
    by_confidence = db.execute(
        "SELECT confidence, COUNT(*) c FROM matches GROUP BY confidence"
    ).fetchall()
    funnel = {
        "lost": db.execute("SELECT COUNT(*) c FROM lost_items").fetchone()["c"],
        "found": db.execute("SELECT COUNT(*) c FROM found_items").fetchone()["c"],
        "returned": db.execute("SELECT COUNT(*) c FROM lost_items WHERE status='RETURNED'").fetchone()["c"],
    }
    return jsonify({
        "by_category": [dict(r) for r in by_category],
        "by_state": [dict(r) for r in by_state],
        "by_confidence": [dict(r) for r in by_confidence],
        "funnel": funnel,
    })


@bp.route("/analytics")
@admin_required
def analytics():
    return render_template("admin/analytics.html")


@bp.route("/reports")
@admin_required
def reports():
    db = get_db()
    lost = db.execute(
        "SELECT li.*, u.name AS owner_name, u.email AS owner_email FROM lost_items li "
        "JOIN users u ON u.id = li.user_id ORDER BY li.created_at DESC"
    ).fetchall()
    found = db.execute(
        "SELECT fi.*, u.name AS finder_name, u.email AS finder_email FROM found_items fi "
        "JOIN users u ON u.id = fi.finder_id ORDER BY fi.created_at DESC"
    ).fetchall()
    return render_template("admin/reports.html", lost=lost, found=found)


@bp.route("/reports/<item_type>/<int:item_id>/flag", methods=("POST",))
@admin_required
def flag_report(item_type, item_id):
    db = get_db()
    table = "lost_items" if item_type == "lost" else "found_items"
    row = db.execute(f"SELECT is_flagged FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if row is not None:
        new_val = 0 if row["is_flagged"] else 1
        db.execute(f"UPDATE {table} SET is_flagged = ? WHERE id = ?", (new_val, item_id))
        db.commit()
        log_action(g.user["id"], "FLAG_TOGGLE", table, item_id)
        flash("Report flag updated.", "success")
    return redirect(url_for("admin.reports"))


@bp.route("/reports/<item_type>/<int:item_id>/remove", methods=("POST",))
@admin_required
def remove_report(item_type, item_id):
    db = get_db()
    table = "lost_items" if item_type == "lost" else "found_items"
    db.execute(f"UPDATE {table} SET status = 'CLOSED' WHERE id = ?", (item_id,))
    db.commit()
    log_action(g.user["id"], "REMOVE_REPORT", table, item_id, details="Removed as fraudulent/spam")
    flash("Report removed from public listings.", "success")
    return redirect(url_for("admin.reports"))


@bp.route("/matches")
@admin_required
def matches():
    db = get_db()
    rows = db.execute(
        """SELECT m.*, li.item_name AS lost_name, fi.item_name AS found_name
           FROM matches m
           JOIN lost_items li ON li.id = m.lost_item_id
           JOIN found_items fi ON fi.id = m.found_item_id
           ORDER BY m.final_score DESC LIMIT 200"""
    ).fetchall()
    return render_template("admin/matches.html", matches=rows)


@bp.route("/claims")
@admin_required
def claims():
    db = get_db()
    rows = db.execute(
        """SELECT c.*, fi.item_name AS found_item_name, li.item_name AS lost_item_name,
                  u.name AS claimant_name, u.email AS claimant_email
           FROM claims c
           JOIN found_items fi ON fi.id = c.found_item_id
           JOIN lost_items li ON li.id = c.lost_item_id
           JOIN users u ON u.id = c.claimant_id
           ORDER BY c.found_item_id, c.evidence_score DESC"""
    ).fetchall()

    # Group by found_item_id so admin can see multiple-claimant situations
    grouped = {}
    for row in rows:
        grouped.setdefault(row["found_item_id"], {"item_name": row["found_item_name"], "claims": []})
        grouped[row["found_item_id"]]["claims"].append(row)

    return render_template("admin/claims.html", grouped=grouped)


@bp.route("/claims/<int:claim_id>")
@admin_required
def claim_detail(claim_id):
    db = get_db()
    claim = db.execute(
        """SELECT c.*, fi.item_name AS found_item_name, fi.image_path AS found_image,
                  li.item_name AS lost_item_name, li.image_path AS lost_image,
                  u.name AS claimant_name, u.email AS claimant_email
           FROM claims c
           JOIN found_items fi ON fi.id = c.found_item_id
           JOIN lost_items li ON li.id = c.lost_item_id
           JOIN users u ON u.id = c.claimant_id
           WHERE c.id = ?""",
        (claim_id,),
    ).fetchone()
    if claim is None:
        flash("Claim not found.", "warning")
        return redirect(url_for("admin.claims"))

    questions = db.execute(
        "SELECT * FROM verification_questions WHERE claim_id = ?", (claim_id,)
    ).fetchall()

    match = db.execute(
        "SELECT * FROM matches WHERE lost_item_id = ? AND found_item_id = ?",
        (claim["lost_item_id"], claim["found_item_id"]),
    ).fetchone()

    other_claims = db.execute(
        """SELECT c.*, u.name AS claimant_name FROM claims c
           JOIN users u ON u.id = c.claimant_id
           WHERE c.found_item_id = ? AND c.id != ?""",
        (claim["found_item_id"], claim_id),
    ).fetchall()

    return render_template(
        "admin/claim_detail.html", claim=claim, questions=questions, match=match,
        other_claims=other_claims,
    )


@bp.route("/claims/<int:claim_id>/decide", methods=("POST",))
@admin_required
def decide_claim(claim_id):
    decision = request.form.get("decision")
    remarks = request.form.get("remarks", "").strip()
    db = get_db()
    claim = db.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
    if claim is None:
        flash("Claim not found.", "warning")
        return redirect(url_for("admin.claims"))

    if decision == "approve":
        db.execute(
            "UPDATE claims SET status='APPROVED', admin_remarks=?, reviewed_by=?, reviewed_at=datetime('now') WHERE id=?",
            (remarks, g.user["id"], claim_id),
        )
        db.execute("UPDATE found_items SET status='APPROVED' WHERE id=?", (claim["found_item_id"],))
        db.execute("UPDATE lost_items SET status='APPROVED' WHERE id=?", (claim["lost_item_id"],))
        # Auto-reject any other pending claims on the same found item
        others = db.execute(
            "SELECT id, claimant_id FROM claims WHERE found_item_id=? AND id != ? AND status NOT IN ('REJECTED','APPROVED')",
            (claim["found_item_id"], claim_id),
        ).fetchall()
        for other in others:
            db.execute(
                "UPDATE claims SET status='REJECTED', admin_remarks='Another claim was approved for this item.' WHERE id=?",
                (other["id"],),
            )
            notify(other["claimant_id"], "Your claim was not approved — another claimant's evidence was verified for this item.", "claim", f"/claim/status/{other['id']}")
        notify(claim["claimant_id"], "Your claim has been approved! Please proceed to arrange a safe handover.", "claim", f"/claim/status/{claim_id}")
        flash("Claim approved.", "success")

    elif decision == "reject":
        db.execute(
            "UPDATE claims SET status='REJECTED', admin_remarks=?, reviewed_by=?, reviewed_at=datetime('now') WHERE id=?",
            (remarks, g.user["id"], claim_id),
        )
        # If no other pending claims remain, reopen the found item
        remaining = db.execute(
            "SELECT COUNT(*) c FROM claims WHERE found_item_id=? AND status IN ('PENDING','UNDER_REVIEW','MORE_EVIDENCE')",
            (claim["found_item_id"],),
        ).fetchone()["c"]
        if remaining == 0:
            db.execute("UPDATE found_items SET status='FOUND' WHERE id=?", (claim["found_item_id"],))
        notify(claim["claimant_id"], f"Your claim was rejected. Admin remarks: {remarks or 'Evidence did not match.'}", "claim", f"/claim/status/{claim_id}")
        flash("Claim rejected.", "success")

    elif decision == "more_evidence":
        db.execute(
            "UPDATE claims SET status='MORE_EVIDENCE', admin_remarks=?, reviewed_by=?, reviewed_at=datetime('now') WHERE id=?",
            (remarks, g.user["id"], claim_id),
        )
        notify(claim["claimant_id"], f"Please provide more evidence for your claim: {remarks or 'additional details needed.'}", "claim", f"/claim/status/{claim_id}")
        flash("Requested more evidence from the claimant.", "success")

    db.commit()
    log_action(g.user["id"], f"CLAIM_{decision.upper()}", "claims", claim_id, details=remarks)
    return redirect(url_for("admin.claim_detail", claim_id=claim_id))


@bp.route("/claims/<int:claim_id>/handover-complete", methods=("POST",))
@admin_required
def complete_handover(claim_id):
    db = get_db()
    claim = db.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
    if claim is None or claim["status"] != "APPROVED":
        flash("Only approved claims can be marked as handed over.", "warning")
        return redirect(url_for("admin.claims"))
    db.execute("UPDATE found_items SET status='RETURNED' WHERE id=?", (claim["found_item_id"],))
    db.execute("UPDATE lost_items SET status='RETURNED' WHERE id=?", (claim["lost_item_id"],))
    db.commit()
    log_action(g.user["id"], "HANDOVER_COMPLETE", "claims", claim_id)
    notify(claim["claimant_id"], "Handover completed. Glad you got your item back!", "claim", f"/claim/status/{claim_id}")
    flash("Marked as returned. 🎉", "success")
    return redirect(url_for("admin.claim_detail", claim_id=claim_id))


@bp.route("/users")
@admin_required
def users():
    db = get_db()
    rows = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    return render_template("admin/users.html", users=rows)


@bp.route("/users/<int:user_id>/toggle-block", methods=("POST",))
@admin_required
def toggle_block(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        flash("User not found.", "warning")
        return redirect(url_for("admin.users"))
    if user["role"] == "admin":
        flash("Cannot block an admin account.", "danger")
        return redirect(url_for("admin.users"))
    new_val = 0 if user["is_blocked"] else 1
    db.execute("UPDATE users SET is_blocked = ? WHERE id = ?", (new_val, user_id))
    db.commit()
    log_action(g.user["id"], "TOGGLE_BLOCK", "users", user_id)
    flash("User status updated.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/audit-logs")
@admin_required
def audit_logs():
    db = get_db()
    rows = db.execute(
        """SELECT a.*, u.name AS user_name FROM audit_logs a
           LEFT JOIN users u ON u.id = a.user_id
           ORDER BY a.timestamp DESC LIMIT 300"""
    ).fetchall()
    return render_template("admin/audit_logs.html", logs=rows)
