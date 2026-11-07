# Lost and Found Application

An AI-assisted, pan-India Lost & Found platform. People report lost and found
items; the system suggests likely matches using text, image, location,
category and date signals — but a human admin always makes the final
ownership decision.

> **AI finds possible matches. Humans verify ownership. Appropriate
> authorities handle official/legal matters.**

This is **not** a police investigation system and does not claim to prove
ownership, recover stolen property, or replace an FIR / government
lost-property system (e.g. for phones, users are pointed to the Government of
India's Sanchar Saathi / CEIR service).

---

## 1. Quick Start (VS Code / local machine)

```bash
# 1. Create and activate a virtual environment (recommended)
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app (the SQLite database is created automatically on first run,
#    along with a demo admin account)
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

- Any new account you register is a normal user.
- To create a fresh database for local development, back up your existing database first, then remove `instance/lostfound.sqlite` and run `python app.py` again. This permanently deletes existing database records.
No GPU, no large model downloads, no internet connection required to run —
everything (TF-IDF text matching, perceptual-hash image matching) runs on
CPU with lightweight libraries so it works out of the box for a demo/viva.

---

## 2. Project Structure

```
lost_and_found_app/
├── app.py                # Flask app factory + startup
├── config.py             # Configuration, AI match weights, categories
├── db.py                 # SQLite connection helpers (raw sqlite3, no ORM)
├── schema.sql             # Database schema (users, lost/found items, matches, claims...)
├── matching.py            # THE AI MATCHING ENGINE (text/image/location/date scoring)
├── utils.py               # Auth decorators, location data, notifications, helpers
├── seed.py                 # Creates the default admin account on first run
├── requirements.txt
├── blueprints/
│   ├── auth.py            # register / login / logout
│   ├── main.py             # home, profile, notifications
│   ├── items.py             # report-lost, report-found, item details, my-reports
│   ├── search.py             # text / semantic / image search + filters
│   ├── claims.py              # matches view, claim submission + verification Q&A
│   └── admin.py                # dashboard, reports, matches, claims, users, analytics
├── templates/               # Jinja2 templates (see below)
└── static/
    ├── css/style.css          # all styling
    ├── js/main.js               # cascading location dropdowns, image preview, nav toggle
    └── uploads/                  # uploaded photos land here at runtime
```

---

## 3. How the AI Matching Works

For every new lost/found report, the app compares it against all *active*
reports of the opposite type and stores a `matches` row for anything scoring
above a configurable threshold (default 30%).

| Signal    | Technique (as implemented)                                   | Default Weight |
|-----------|----------------------------------------------------------------|---------------|
| Text      | TF-IDF vectorization (name+description+brand+model+colour) + cosine similarity, fit over a growing corpus of recent reports | 35% |
| Image     | Perceptual average-hash (Hamming similarity) + colour-histogram cosine similarity, blended 50/50 | 40% |
| Category  | Exact match (1.0) or no match (0.0)                             | 10% |
| Location  | Area match > City match > District match > State match > none   | 10% |
| Date      | Exponential decay based on days between lost/found dates          | 5%  |

If a report has no photo, the image weight is automatically redistributed
across the other signals rather than penalising the match.

Weights, thresholds and confidence bands all live in `config.py`
(`MATCH_WEIGHTS`, `MATCH_STORE_THRESHOLD`, `MATCH_NOTIFY_THRESHOLD`,
`CONFIDENCE_HIGH`, `CONFIDENCE_MEDIUM`) — they are explicitly **not**
claimed to be scientifically optimal; they're a practical starting point you
can tune after testing, exactly as the project brief asks for.

### Upgrading to Sentence-Transformers / CLIP

The project intentionally uses TF-IDF + perceptual hashing instead of
Sentence-Transformers / CLIP so it installs and runs in seconds on any
laptop with no GPU and no multi-GB model download — ideal for a live demo
or viva. If you want to swap in real embedding models later (e.g. for a
larger dataset or a stronger dissertation claim):

1. **Text:** replace the body of `text_similarity()` in `matching.py` with
   `sentence-transformers` embeddings + `cosine_similarity` (e.g.
   `all-MiniLM-L6-v2`). The function signature and everything that calls it
   stays the same.
2. **Image:** replace the body of `image_similarity()` with a CLIP/SigLIP
   embedding comparison (`transformers` + `torch`). Store the embedding
   alongside the image if you want to avoid recomputing it every time.
3. Optionally add **FAISS** for approximate nearest-neighbour search once
   your dataset is large enough that pairwise comparison becomes slow.

Nothing else in the app needs to change — `compute_match()` and the
match-generation functions just call these two functions.

---

## 4. Ownership Verification & Claims (how privacy is protected)

- When someone reports a **lost** item, they can optionally fill in
  *private ownership details* (a scratch, a sticker, a hidden feature, a
  serial number, distinctive contents, etc.). These are stored as JSON and
  are **never shown on the public listing**.
- When another user thinks a **found** item is theirs, they submit a claim
  and are asked the corresponding questions (without ever seeing the
  expected answers).
- Their answers are compared to the private details using simple text
  similarity (`difflib.SequenceMatcher`) to produce an *evidence score* —
  this is a signal for the admin, not an automatic decision.
- **Admins always make the final call** (`Approve` / `Reject` / `Request
  More Evidence`) from `/admin/claims/<id>`, where they can see the
  side-by-side comparison of expected vs. submitted answers.
- If **multiple people claim the same item**, the admin dashboard flags it
  explicitly ("Multiple claims detected — comparison required") instead of
  auto-selecting the highest scorer.
- After approval, the item is **not** immediately returned — an admin must
  separately click "Mark Handover Completed" once a safe handover (public
  meeting for low-value items, or via police/authority for high-value ones)
  has actually happened.

---

## 5. Status Lifecycle

`LOST` → `POTENTIAL_MATCH` → `CLAIM_PENDING` (found item) / `VERIFICATION`
→ `APPROVED` → `RETURNED`. Admins can also `REJECT` a claim or mark a report
`CLOSED` (spam/fraud removal).

---

## 6. Fraud / Abuse Protections Implemented

- Password hashing (Werkzeug `generate_password_hash` / `check_password_hash`)
- Session-based auth with role checks (`login_required`, `admin_required`)
- Admin can flag/unflag and remove (close) suspicious reports
- Admin can suspend/unsuspend user accounts
- Multiple-claim detection surfaced explicitly to admins
- Full audit log of key actions (`/admin/audit-logs`) — logins, reports,
  claims, admin decisions, flags, blocks
- Max upload size (8 MB) and file-type allow-list for images
- Public listings never expose the reporter's email/phone or private
  ownership details

**Not implemented (left as a clearly-scoped extension point):** live
email/SMS OTP delivery — the demo auto-verifies accounts on registration so
you can test end-to-end without an SMTP/SMS provider. `users.verified` and
the `notify()`/`log_action()` helpers in `utils.py` are already wired up so
you can plug in a real OTP provider later without restructuring anything.

---

## 7. Demo Script (matches the brief's "Final Demonstration Scenario")

1. Register two accounts (or use the seeded admin for step 4 only).
2. As **User A**: Report Lost → "Black JBL wireless earbuds", category
   *Electronics/Earphones*, Mangaluru / Dakshina Kannada / Karnataka, near
   the railway station, upload a photo.
3. As **User B**: Report Found → "Found black JBL Bluetooth earphones",
   same category/area, upload a similar photo.
4. Log back in as **User A** → *My Reports* → *Matches* on the lost report.
   You should see a high-confidence AI match with a text/image/location/date
   breakdown and an explanation checklist.
5. Click **Submit Claim** on the match, answer the private verification
   questions you set when filing the lost report.
6. Log in using the administrator account configured for your deployment.
7. Back in the claim detail page, click **Mark Handover Completed**.
8. As **User A**, the lost report now shows status `RETURNED`. 🎉

---

## 8. Notes for the Viva

- The AI never auto-approves ownership — this is enforced in code
  (`decide_claim()` in `blueprints/admin.py` requires an authenticated
  admin action) as well as in the UI copy throughout.
- Every match card and claim page explicitly states the AI-suggestion vs.
  human-verification distinction, matching the brief's "Most Important
  Project Principle".
- The location dataset (`INDIA_LOCATIONS` in `utils.py`) is a representative
  sample of States → Districts → Cities across India (not just
  Karnataka/Mangaluru) and can be extended with more entries at any time.
