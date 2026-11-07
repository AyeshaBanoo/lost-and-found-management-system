-- Lost and Found Application — Database Schema (SQLite)

DROP TABLE IF EXISTS audit_logs;
DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS verification_questions;
DROP TABLE IF EXISTS claims;
DROP TABLE IF EXISTS matches;
DROP TABLE IF EXISTS found_items;
DROP TABLE IF EXISTS lost_items;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    phone           TEXT,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'user',   -- 'user' or 'admin'
    verified        INTEGER NOT NULL DEFAULT 1,     -- email/OTP verified flag (demo defaults to 1)
    is_blocked      INTEGER NOT NULL DEFAULT 0,
    flagged         INTEGER NOT NULL DEFAULT 0,     -- flagged for suspicious activity
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE lost_items (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id                     INTEGER NOT NULL,
    item_name                   TEXT NOT NULL,
    category                    TEXT NOT NULL,
    description                 TEXT,
    brand                       TEXT,
    model                       TEXT,
    colour                      TEXT,
    state                       TEXT,
    district                    TEXT,
    city                        TEXT,
    area                        TEXT,
    latitude                    REAL,
    longitude                   REAL,
    date_lost                   TEXT,
    time_lost                   TEXT,
    image_path                  TEXT,
    private_ownership_details   TEXT,     -- JSON blob, never shown publicly
    status                      TEXT NOT NULL DEFAULT 'LOST',
    is_flagged                  INTEGER NOT NULL DEFAULT 0,
    created_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE found_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    finder_id       INTEGER NOT NULL,
    item_name       TEXT NOT NULL,
    category        TEXT NOT NULL,
    description     TEXT,
    brand           TEXT,
    model           TEXT,
    colour          TEXT,
    state           TEXT,
    district        TEXT,
    city            TEXT,
    area            TEXT,
    latitude        REAL,
    longitude       REAL,
    date_found      TEXT,
    time_found      TEXT,
    image_path      TEXT,
    status          TEXT NOT NULL DEFAULT 'FOUND',
    is_flagged      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (finder_id) REFERENCES users (id)
);

CREATE TABLE matches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lost_item_id    INTEGER NOT NULL,
    found_item_id   INTEGER NOT NULL,
    text_score      REAL NOT NULL DEFAULT 0,
    image_score     REAL NOT NULL DEFAULT 0,
    category_score  REAL NOT NULL DEFAULT 0,
    location_score  REAL NOT NULL DEFAULT 0,
    date_score      REAL NOT NULL DEFAULT 0,
    final_score     REAL NOT NULL DEFAULT 0,
    confidence      TEXT NOT NULL DEFAULT 'Low',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (lost_item_id) REFERENCES lost_items (id),
    FOREIGN KEY (found_item_id) REFERENCES found_items (id),
    UNIQUE (lost_item_id, found_item_id)
);

CREATE TABLE claims (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    found_item_id       INTEGER NOT NULL,
    lost_item_id        INTEGER NOT NULL,
    claimant_id         INTEGER NOT NULL,
    proof_description   TEXT,
    evidence_score      REAL NOT NULL DEFAULT 0,   -- computed match of verification answers
    status              TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING, UNDER_REVIEW, MORE_EVIDENCE, APPROVED, REJECTED
    admin_remarks       TEXT,
    reviewed_by         INTEGER,
    reviewed_at         TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (found_item_id) REFERENCES found_items (id),
    FOREIGN KEY (lost_item_id) REFERENCES lost_items (id),
    FOREIGN KEY (claimant_id) REFERENCES users (id),
    FOREIGN KEY (reviewed_by) REFERENCES users (id)
);

CREATE TABLE verification_questions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id            INTEGER NOT NULL,
    question            TEXT NOT NULL,
    expected_answer     TEXT NOT NULL,
    claimant_answer     TEXT,
    match_result        REAL,   -- 0..1 similarity of claimant answer to expected answer
    FOREIGN KEY (claim_id) REFERENCES claims (id)
);

CREATE TABLE notifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    message         TEXT NOT NULL,
    type            TEXT NOT NULL DEFAULT 'match',   -- match, claim, admin, system
    link            TEXT,
    is_read         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE audit_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER,
    action          TEXT NOT NULL,
    target_type     TEXT,
    target_id       INTEGER,
    details         TEXT,
    timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE INDEX idx_lost_status ON lost_items(status);
CREATE INDEX idx_found_status ON found_items(status);
CREATE INDEX idx_matches_lost ON matches(lost_item_id);
CREATE INDEX idx_matches_found ON matches(found_item_id);
CREATE INDEX idx_claims_found ON claims(found_item_id);
