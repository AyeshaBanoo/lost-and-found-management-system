from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app

from db import get_db
from utils import login_required, get_verification_questions, answer_similarity, notify, log_action
from matching import match_explanation

bp = Blueprint("matches", __name__, url_prefix="")


@bp.route("/matches/<int:lost_item_id>")
@login_required
def view_matches(lost_item_id):
    db = get_db()
    lost_item = db.execute("SELECT * FROM lost_items WHERE id = ?", (lost_item_id,)).fetchone()
    if lost_item is None:
        flash("Lost item report not found.", "warning")
        return redirect(url_for("items.my_reports"))
    if lost_item["user_id"] != g.user["id"] and g.user["role"] != "admin":
        flash("You can only view matches for your own reports.", "danger")
        return redirect(url_for("items.my_reports"))

    rows = db.execute(
        """SELECT m.*, fi.item_name, fi.category, fi.description, fi.colour, fi.brand,
                  fi.city, fi.area, fi.state, fi.image_path, fi.date_found, fi.status AS found_status
           FROM matches m JOIN found_items fi ON fi.id = m.found_item_id
           WHERE m.lost_item_id = ? ORDER BY m.final_score DESC""",
        (lost_item_id,),
    ).fetchall()

    explained = [(row, match_explanation(dict(row))) for row in rows]
    return render_template("matches/matches.html", lost_item=lost_item, matches=explained)


@bp.route("/claim/<int:found_item_id>", methods=("GET", "POST"))
@login_required
def submit_claim(found_item_id):
    db = get_db()
    found_item = db.execute("SELECT * FROM found_items WHERE id = ?", (found_item_id,)).fetchone()
    if found_item is None:
        flash("That found-item report does not exist.", "warning")
        return redirect(url_for("main.home"))

    my_lost_items = db.execute(
        "SELECT * FROM lost_items WHERE user_id = ? AND status IN ('LOST', 'POTENTIAL_MATCH') "
        "ORDER BY created_at DESC",
        (g.user["id"],),
    ).fetchall()

    if not my_lost_items:
        flash("You need an active lost-item report before you can submit a claim. Please report your lost item first.", "warning")
        return redirect(url_for("items.report_lost"))

    lost_item_id = request.values.get("lost_item_id", type=int)
    lost_item = None
    if lost_item_id:
        lost_item = next((li for li in my_lost_items if li["id"] == lost_item_id), None)

    questions = get_verification_questions(lost_item["private_ownership_details"]) if lost_item else []

    if request.method == "POST" and lost_item:
        proof_description = request.form.get("proof_description", "").strip()

        existing = db.execute(
            "SELECT id FROM claims WHERE found_item_id = ? AND lost_item_id = ? AND claimant_id = ?",
            (found_item_id, lost_item_id, g.user["id"]),
        ).fetchone()
        if existing:
            flash("You have already submitted a claim for this item.", "info")
            return redirect(url_for("matches.claim_status", claim_id=existing["id"]))

        cursor = db.execute(
            """INSERT INTO claims (found_item_id, lost_item_id, claimant_id, proof_description, status)
               VALUES (?, ?, ?, ?, 'UNDER_REVIEW')""",
            (found_item_id, lost_item_id, g.user["id"], proof_description),
        )
        claim_id = cursor.lastrowid

        scores = []
        for idx, (question, expected_answer) in enumerate(questions):
            claimant_answer = request.form.get(f"answer_{idx}", "").strip()
            sim = answer_similarity(claimant_answer, expected_answer)
            scores.append(sim)
            db.execute(
                """INSERT INTO verification_questions
                   (claim_id, question, expected_answer, claimant_answer, match_result)
                   VALUES (?, ?, ?, ?, ?)""",
                (claim_id, question, expected_answer, claimant_answer, sim),
            )

        evidence_score = sum(scores) / len(scores) if scores else 0.0
        db.execute("UPDATE claims SET evidence_score = ? WHERE id = ?", (evidence_score, claim_id))
        db.execute("UPDATE found_items SET status = 'CLAIM_PENDING' WHERE id = ?", (found_item_id,))
        db.commit()
        log_action(g.user["id"], "SUBMIT_CLAIM", "claims", claim_id)

        admins = db.execute("SELECT id FROM users WHERE role = 'admin'").fetchall()
        for admin in admins:
            notify(
                admin["id"],
                f"New claim #{claim_id} submitted for found item \"{found_item['item_name']}\" — needs review.",
                ntype="claim",
                link=f"/admin/claims",
            )

        flash("Claim submitted successfully. Your ownership evidence is now under review.", "success")
        return redirect(url_for("matches.claim_status", claim_id=claim_id))

    return render_template(
        "claims/claim_form.html", found_item=found_item, my_lost_items=my_lost_items,
        lost_item=lost_item, questions=questions,
    )


@bp.route("/claim/status/<int:claim_id>")
@login_required
def claim_status(claim_id):
    db = get_db()
    claim = db.execute(
        """SELECT c.*, fi.item_name AS found_item_name, fi.category, fi.image_path AS found_image,
                  li.item_name AS lost_item_name,
                  u.name AS finder_name, u.phone AS finder_phone, u.email AS finder_email
           FROM claims c
           JOIN found_items fi ON fi.id = c.found_item_id
           JOIN lost_items li ON li.id = c.lost_item_id
           JOIN users u ON u.id = fi.finder_id
           WHERE c.id = ?""",
        (claim_id,),
    ).fetchone()
    if claim is None:
        flash("Claim not found.", "warning")
        return redirect(url_for("main.home"))
    if claim["claimant_id"] != g.user["id"] and g.user["role"] != "admin":
        flash("You can only view your own claims.", "danger")
        return redirect(url_for("main.home"))

    questions = db.execute(
        "SELECT id, question, claimant_answer FROM verification_questions WHERE claim_id = ?",
        (claim_id,),
    ).fetchall()

    is_high_value = claim["category"] in current_app.config["HIGH_VALUE_CATEGORIES"]

    return render_template(
        "claims/claim_status.html", claim=claim, questions=questions, is_high_value=is_high_value
    )


@bp.route("/claim/<int:claim_id>/more-evidence", methods=("POST",))
@login_required
def add_more_evidence(claim_id):
    db = get_db()
    claim = db.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
    if claim is None or claim["claimant_id"] != g.user["id"]:
        flash("You can only update your own claims.", "danger")
        return redirect(url_for("main.home"))
    if claim["status"] != "MORE_EVIDENCE":
        flash("This claim is not currently awaiting more evidence.", "info")
        return redirect(url_for("matches.claim_status", claim_id=claim_id))

    additional_text = request.form.get("additional_evidence", "").strip()
    questions = db.execute(
        "SELECT * FROM verification_questions WHERE claim_id = ?", (claim_id,)
    ).fetchall()

    scores = []
    for q in questions:
        new_answer = request.form.get(f"answer_{q['id']}", "").strip()
        if new_answer:
            sim = answer_similarity(new_answer, q["expected_answer"])
            db.execute(
                "UPDATE verification_questions SET claimant_answer = ?, match_result = ? WHERE id = ?",
                (new_answer, sim, q["id"]),
            )
            scores.append(sim)
        elif q["match_result"] is not None:
            scores.append(q["match_result"])

    evidence_score = sum(scores) / len(scores) if scores else claim["evidence_score"]
    combined_proof = claim["proof_description"] or ""
    if additional_text:
        combined_proof = (combined_proof + "\n\n[Additional evidence] " + additional_text).strip()

    db.execute(
        "UPDATE claims SET proof_description = ?, evidence_score = ?, status = 'UNDER_REVIEW', "
        "admin_remarks = NULL WHERE id = ?",
        (combined_proof, evidence_score, claim_id),
    )
    db.commit()
    log_action(g.user["id"], "SUBMIT_MORE_EVIDENCE", "claims", claim_id)

    admins = db.execute("SELECT id FROM users WHERE role = 'admin'").fetchall()
    for admin in admins:
        notify(
            admin["id"],
            f"Claimant submitted more evidence for claim #{claim_id} — needs re-review.",
            ntype="claim",
            link="/admin/claims",
        )

    flash("Your additional evidence has been submitted for re-review.", "success")
    return redirect(url_for("matches.claim_status", claim_id=claim_id))


@bp.route("/my-claims")
@login_required
def my_claims():
    db = get_db()
    claims = db.execute(
        """SELECT c.*, fi.item_name AS found_item_name, li.item_name AS lost_item_name
           FROM claims c
           JOIN found_items fi ON fi.id = c.found_item_id
           JOIN lost_items li ON li.id = c.lost_item_id
           WHERE c.claimant_id = ? ORDER BY c.created_at DESC""",
        (g.user["id"],),
    ).fetchall()
    return render_template("claims/my_claims.html", claims=claims)