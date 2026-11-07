import os
from datetime import datetime

from flask import Blueprint, render_template, request, current_app

from db import get_db
from utils import get_states, save_uploaded_image
from matching import text_similarity, image_similarity, build_text_corpus, _combined_text

bp = Blueprint("search", __name__, url_prefix="")


def _apply_filters(rows, filters):
    def keep(row):
        if filters.get("category") and row["category"] != filters["category"]:
            return False
        if filters.get("state") and row["state"] != filters["state"]:
            return False
        if filters.get("city") and row["city"] != filters["city"]:
            return False
        if filters.get("brand") and (row["brand"] or "").lower() != filters["brand"].lower():
            return False
        if filters.get("colour") and (row["colour"] or "").lower() != filters["colour"].lower():
            return False
        return True
    return [r for r in rows if keep(r)]


@bp.route("/search", methods=("GET", "POST"))
def search():
    db = get_db()
    query = request.values.get("q", "").strip()
    scope = request.values.get("scope", "both")  # lost, found, both
    filters = {
        "category": request.values.get("category", ""),
        "state": request.values.get("state", ""),
        "city": request.values.get("city", ""),
        "brand": request.values.get("brand", ""),
        "colour": request.values.get("colour", ""),
    }

    image_file = request.files.get("image") if request.method == "POST" else None
    image_results = []
    text_results = []

    lost_rows = db.execute("SELECT * FROM lost_items WHERE status != 'CLOSED'").fetchall()
    found_rows = db.execute("SELECT * FROM found_items WHERE status != 'CLOSED'").fetchall()

    if scope in ("both", "lost"):
        lost_rows = _apply_filters(lost_rows, filters)
    else:
        lost_rows = []
    if scope in ("both", "found"):
        found_rows = _apply_filters(found_rows, filters)
    else:
        found_rows = []

    if image_file and image_file.filename:
        # Semantic image search: rank existing reports by visual similarity
        upload_folder = current_app.config["UPLOAD_FOLDER"]
        tmp_path = save_uploaded_image(image_file, "searchtmp")
        if tmp_path:
            for row in list(lost_rows) + list(found_rows):
                score = image_similarity(tmp_path, row["image_path"], upload_folder)
                if score and score > 0.35:
                    image_results.append((row, round(score * 100)))
            image_results.sort(key=lambda x: x[1], reverse=True)
            try:
                os.remove(os.path.join(upload_folder, os.path.basename(tmp_path)))
            except OSError:
                pass
    elif query:
        corpus = build_text_corpus(db)
        for row in list(lost_rows) + list(found_rows):
            score = text_similarity(query, _combined_text(row), corpus)
            if score > 0.08:
                text_results.append((row, round(score * 100)))
        text_results.sort(key=lambda x: x[1], reverse=True)
    else:
        # No query -> just show everything matching the filters, newest first
        combined = sorted(list(lost_rows) + list(found_rows), key=lambda r: r["created_at"], reverse=True)
        text_results = [(row, None) for row in combined]

    categories = current_app.config["ITEM_CATEGORIES"]
    return render_template(
        "search/search.html", query=query, scope=scope, filters=filters,
        categories=categories, states=get_states(),
        text_results=text_results, image_results=image_results,
        used_image_search=bool(image_file and image_file.filename),
    )


@bp.route("/lost-items")
def lost_items():
    db = get_db()
    filters = {
        "category": request.args.get("category", ""),
        "state": request.args.get("state", ""),
        "city": request.args.get("city", ""),
    }
    rows = db.execute("SELECT * FROM lost_items WHERE status != 'CLOSED' ORDER BY created_at DESC").fetchall()
    rows = _apply_filters(rows, filters)
    return render_template("search/lost_items.html", items=rows, filters=filters,
                            categories=current_app.config["ITEM_CATEGORIES"], states=get_states())


@bp.route("/found-items")
def found_items():
    db = get_db()
    filters = {
        "category": request.args.get("category", ""),
        "state": request.args.get("state", ""),
        "city": request.args.get("city", ""),
    }
    rows = db.execute("SELECT * FROM found_items WHERE status != 'CLOSED' ORDER BY created_at DESC").fetchall()
    rows = _apply_filters(rows, filters)
    return render_template("search/found_items.html", items=rows, filters=filters,
                            categories=current_app.config["ITEM_CATEGORIES"], states=get_states())
