"""
AI Matching Engine for the Lost and Found Application.

Design notes (see README for the full architecture diagram):
    TEXT  -> TF-IDF embedding + cosine similarity   (Sentence-Transformers is a
             drop-in upgrade: replace `text_similarity()` internals only)
    IMAGE -> perceptual average-hash + cosine-style similarity on colour
             histograms (CLIP/SigLIP is a drop-in upgrade: replace
             `image_similarity()` internals only, everything else is unchanged)
    Final score = weighted combination of text, image, category, location, date.

AI suggests potential matches; it does NOT decide ownership. Ownership is
always confirmed by a human admin after a verification-question claim flow.
"""
import os
import math
from datetime import datetime

from PIL import Image
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from flask import current_app
from db import get_db
from utils import notify


# ---------------------------------------------------------------------------
# TEXT SIMILARITY
# ---------------------------------------------------------------------------
def _combined_text(row):
    parts = [
        row["item_name"] or "",
        row["description"] or "",
        row["brand"] or "",
        row["model"] or "",
        row["colour"] or "",
        row["category"] or "",
    ]
    return " ".join(p for p in parts if p).strip()


def text_similarity(text_a, text_b, corpus=None):
    """Cosine similarity between two texts using TF-IDF.

    A small extra `corpus` of other reports' text is used to fit a more
    meaningful IDF weighting, the same way a production system would fit
    embeddings over a larger reference corpus.
    """
    text_a, text_b = (text_a or "").strip(), (text_b or "").strip()
    if not text_a or not text_b:
        return 0.0

    documents = list(corpus or [])
    documents.extend([text_a, text_b])
    documents = [d for d in documents if d.strip()]
    if len(documents) < 2:
        return 0.0

    try:
        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        matrix = vectorizer.fit_transform(documents)
    except ValueError:
        # Corpus had no usable vocabulary (e.g. all stop-words) -> fallback
        return _word_overlap(text_a, text_b)

    vec_a, vec_b = matrix[-2], matrix[-1]
    sim = cosine_similarity(vec_a, vec_b)[0][0]
    if sim == 0.0:
        # TF-IDF found zero overlap in weighted terms; fall back to a raw
        # word-overlap score so near-identical short phrases aren't scored 0.
        return _word_overlap(text_a, text_b)
    return float(max(0.0, min(1.0, sim)))


def _word_overlap(a, b):
    words_a, words_b = set(a.lower().split()), set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def build_text_corpus(db):
    """Grab existing report text to help TF-IDF build a richer vocabulary."""
    corpus = []
    for row in db.execute("SELECT * FROM lost_items ORDER BY id DESC LIMIT 300"):
        corpus.append(_combined_text(row))
    for row in db.execute("SELECT * FROM found_items ORDER BY id DESC LIMIT 300"):
        corpus.append(_combined_text(row))
    return corpus


# ---------------------------------------------------------------------------
# IMAGE SIMILARITY  (lightweight perceptual hash + colour histogram)
# ---------------------------------------------------------------------------
def _average_hash(image_path, hash_size=8):
    with Image.open(image_path) as img:
        img = img.convert("L").resize((hash_size, hash_size), Image.LANCZOS)
        pixels = list(img.getdata())
        avg = sum(pixels) / len(pixels)
        bits = "".join("1" if p >= avg else "0" for p in pixels)
        return bits


def _color_histogram(image_path, bins=16):
    with Image.open(image_path) as img:
        img = img.convert("RGB").resize((64, 64))
        hist = img.histogram()  # 256 bins per channel (R,G,B) = 768 values
        # Downsample into `bins` buckets per channel for speed/robustness
        channel_size = 256
        bucket = channel_size // bins
        reduced = []
        for c in range(3):
            channel = hist[c * channel_size:(c + 1) * channel_size]
            for i in range(0, channel_size, bucket):
                reduced.append(sum(channel[i:i + bucket]))
        total = sum(reduced) or 1
        return [v / total for v in reduced]


def _hamming_similarity(hash_a, hash_b):
    if len(hash_a) != len(hash_b):
        return 0.0
    distance = sum(c1 != c2 for c1, c2 in zip(hash_a, hash_b))
    return 1 - (distance / len(hash_a))


def _histogram_similarity(hist_a, hist_b):
    # Cosine similarity between two histogram vectors
    dot = sum(a * b for a, b in zip(hist_a, hist_b))
    norm_a = math.sqrt(sum(a * a for a in hist_a))
    norm_b = math.sqrt(sum(b * b for b in hist_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def image_similarity(path_a, path_b, upload_folder):
    """Return a 0..1 similarity score, or None if either image is missing.

    NOTE: this is a lightweight stand-in for a CLIP/SigLIP embedding
    comparison (no GPU / large model download needed for a student
    laptop). To upgrade: compute a CLIP embedding per image, store it,
    and replace the body of this function with a cosine similarity of
    the two embeddings — the rest of the pipeline is unchanged.
    """
    if not path_a or not path_b:
        return None
    full_a = os.path.join(upload_folder, os.path.basename(path_a))
    full_b = os.path.join(upload_folder, os.path.basename(path_b))
    if not (os.path.exists(full_a) and os.path.exists(full_b)):
        return None
    try:
        hash_sim = _hamming_similarity(_average_hash(full_a), _average_hash(full_b))
        hist_sim = _histogram_similarity(_color_histogram(full_a), _color_histogram(full_b))
        return float(max(0.0, min(1.0, 0.5 * hash_sim + 0.5 * hist_sim)))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# LOCATION & DATE SIGNALS
# ---------------------------------------------------------------------------
def location_similarity(lost_row, found_row):
    if lost_row["area"] and found_row["area"] and lost_row["area"].strip().lower() == found_row["area"].strip().lower():
        return 1.0
    if lost_row["city"] and found_row["city"] and lost_row["city"].strip().lower() == found_row["city"].strip().lower():
        return 0.85
    if lost_row["district"] and found_row["district"] and lost_row["district"].strip().lower() == found_row["district"].strip().lower():
        return 0.6
    if lost_row["state"] and found_row["state"] and lost_row["state"].strip().lower() == found_row["state"].strip().lower():
        return 0.35
    return 0.0


def _parse_date(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def date_similarity(date_lost, date_found):
    d1, d2 = _parse_date(date_lost), _parse_date(date_found)
    if d1 is None or d2 is None:
        return 0.3  # unknown -> neutral-low, don't fully penalise
    diff_days = abs((d2 - d1).days)
    # Smooth exponential decay: same day/next few days score near 1,
    # a few months later trails off toward 0.
    return float(math.exp(-diff_days / 45.0))


def category_similarity(cat_a, cat_b):
    if not cat_a or not cat_b:
        return 0.0
    return 1.0 if cat_a.strip().lower() == cat_b.strip().lower() else 0.0


# ---------------------------------------------------------------------------
# MULTIMODAL SCORE
# ---------------------------------------------------------------------------
def confidence_label(score):
    weights = current_app.config
    if score >= weights["CONFIDENCE_HIGH"]:
        return "High"
    if score >= weights["CONFIDENCE_MEDIUM"]:
        return "Medium"
    return "Low"


def compute_match(lost_row, found_row, corpus=None):
    weights = dict(current_app.config["MATCH_WEIGHTS"])
    upload_folder = current_app.config["UPLOAD_FOLDER"]

    t_score = text_similarity(_combined_text(lost_row), _combined_text(found_row), corpus)
    i_score = image_similarity(lost_row["image_path"], found_row["image_path"], upload_folder)
    c_score = category_similarity(lost_row["category"], found_row["category"])
    l_score = location_similarity(lost_row, found_row)
    d_score = date_similarity(lost_row["date_lost"], found_row["date_found"])

    if i_score is None:
        # No photo on one/both sides -> redistribute the image weight
        # proportionally across the remaining signals instead of penalising.
        image_weight = weights.pop("image")
        remaining = sum(weights.values()) or 1.0
        weights = {k: v + (v / remaining) * image_weight for k, v in weights.items()}
        i_score_for_total = 0.0
    else:
        i_score_for_total = i_score

    final = (
        weights.get("text", 0) * t_score
        + weights.get("image", 0) * i_score_for_total
        + weights.get("category", 0) * c_score
        + weights.get("location", 0) * l_score
        + weights.get("date", 0) * d_score
    )
    final = float(max(0.0, min(1.0, final)))

    return {
        "text_score": round(t_score, 4),
        "image_score": round(i_score, 4) if i_score is not None else None,
        "category_score": round(c_score, 4),
        "location_score": round(l_score, 4),
        "date_score": round(d_score, 4),
        "final_score": round(final, 4),
        "confidence": confidence_label(final),
    }


# ---------------------------------------------------------------------------
# MATCH GENERATION (called after a new report is created)
# ---------------------------------------------------------------------------
def _upsert_match(db, lost_id, found_id, scores):
    threshold = current_app.config["MATCH_STORE_THRESHOLD"]
    if scores["final_score"] < threshold:
        return None
    db.execute(
        """
        INSERT INTO matches (lost_item_id, found_item_id, text_score, image_score,
            category_score, location_score, date_score, final_score, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(lost_item_id, found_item_id) DO UPDATE SET
            text_score=excluded.text_score,
            image_score=excluded.image_score,
            category_score=excluded.category_score,
            location_score=excluded.location_score,
            date_score=excluded.date_score,
            final_score=excluded.final_score,
            confidence=excluded.confidence,
            created_at=datetime('now')
        """,
        (
            lost_id, found_id, scores["text_score"], scores["image_score"] or 0,
            scores["category_score"], scores["location_score"], scores["date_score"],
            scores["final_score"], scores["confidence"],
        ),
    )
    db.commit()
    return scores


def generate_matches_for_lost_item(lost_id):
    """Compute matches between one lost item and every active found item."""
    db = get_db()
    lost_row = db.execute("SELECT * FROM lost_items WHERE id = ?", (lost_id,)).fetchone()
    if lost_row is None:
        return []
    corpus = build_text_corpus(db)
    found_items = db.execute(
        "SELECT * FROM found_items WHERE status = 'FOUND'"
    ).fetchall()

    results = []
    for found_row in found_items:
        scores = compute_match(lost_row, found_row, corpus)
        stored = _upsert_match(db, lost_id, found_row["id"], scores)
        if stored:
            results.append((found_row, stored))
            notify_threshold = current_app.config["MATCH_NOTIFY_THRESHOLD"]
            if stored["final_score"] >= notify_threshold:
                notify(
                    lost_row["user_id"],
                    f"A potential match has been found for your lost \"{lost_row['item_name']}\" report "
                    f"({round(stored['final_score'] * 100)}% AI match).",
                    ntype="match",
                    link=f"/matches/{lost_id}",
                )
    if lost_row["status"] == "LOST" and results:
        db.execute("UPDATE lost_items SET status = 'POTENTIAL_MATCH' WHERE id = ?", (lost_id,))
        db.commit()
    return results


def generate_matches_for_found_item(found_id):
    """Compute matches between one found item and every active lost item."""
    db = get_db()
    found_row = db.execute("SELECT * FROM found_items WHERE id = ?", (found_id,)).fetchone()
    if found_row is None:
        return []
    corpus = build_text_corpus(db)
    lost_items = db.execute(
        "SELECT * FROM lost_items WHERE status IN ('LOST', 'POTENTIAL_MATCH')"
    ).fetchall()

    results = []
    for lost_row in lost_items:
        scores = compute_match(lost_row, found_row, corpus)
        stored = _upsert_match(db, lost_row["id"], found_id, scores)
        if stored:
            results.append((lost_row, stored))
            notify_threshold = current_app.config["MATCH_NOTIFY_THRESHOLD"]
            if stored["final_score"] >= notify_threshold:
                notify(
                    lost_row["user_id"],
                    f"A potential match has been found for your lost \"{lost_row['item_name']}\" report "
                    f"({round(stored['final_score'] * 100)}% AI match).",
                    ntype="match",
                    link=f"/matches/{lost_row['id']}",
                )
                if lost_row["status"] == "LOST":
                    db.execute("UPDATE lost_items SET status = 'POTENTIAL_MATCH' WHERE id = ?", (lost_row["id"],))
    db.commit()
    return results


def match_explanation(scores):
    """Human-readable checklist for AI explainability (used in templates)."""
    checks = []
    if scores["category_score"] >= 1.0:
        checks.append(("Same category", True))
    if scores["text_score"] >= 0.5:
        checks.append(("Strong text similarity", True))
    elif scores["text_score"] >= 0.25:
        checks.append(("Some text similarity", True))
    if scores["image_score"] is not None and scores["image_score"] >= 0.6:
        checks.append(("Strong image similarity", True))
    if scores["location_score"] >= 0.85:
        checks.append(("Same city/area", True))
    elif scores["location_score"] >= 0.35:
        checks.append(("Same state/district", True))
    if scores["date_score"] >= 0.7:
        checks.append(("Lost/found dates are close", True))
    return checks
