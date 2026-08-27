-- Schema interno do «Quem É Este Leão?»
-- A resposta correcta vive APENAS em quiz_answers — nunca em artefactos públicos.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS rotation_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cycle_id INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO rotation_state (id, cycle_id, updated_at)
VALUES (1, 1, datetime('now'));

CREATE TABLE IF NOT EXISTS players_used (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    cycle_id INTEGER NOT NULL,
    used_at TEXT NOT NULL,
    UNIQUE (player_id, cycle_id)
);

CREATE INDEX IF NOT EXISTS idx_players_used_cycle ON players_used (cycle_id);

CREATE TABLE IF NOT EXISTS quizzes (
    id TEXT PRIMARY KEY,
    format_id TEXT NOT NULL DEFAULT 'quem_e_este_leao',
    player_id TEXT NOT NULL,
    original_image_path TEXT,
    processed_image_path TEXT NOT NULL,
    clue TEXT NOT NULL,
    caption TEXT NOT NULL,
    reveal_caption TEXT NOT NULL,
    publication_dt TEXT,
    reveal_dt TEXT,
    status TEXT NOT NULL CHECK (status IN ('draft', 'published', 'revealed')),
    difficulty TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
    image_attribution TEXT,
    created_at TEXT NOT NULL,
    image_source TEXT,
    image_kind TEXT NOT NULL DEFAULT 'REAL',
    published_at TEXT,
    reveal_at TEXT,
    revealed_at TEXT,
    x_quiz_post_id TEXT,
    x_reveal_post_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_quizzes_status_reveal ON quizzes (status, reveal_dt);

-- NUNCA copiar esta tabela para legendas, nomes de ficheiro ou posts.
CREATE TABLE IF NOT EXISTS quiz_answers (
    quiz_id TEXT PRIMARY KEY,
    correct_answer TEXT NOT NULL,
    interesting_fact TEXT,
    player_name TEXT,
    FOREIGN KEY (quiz_id) REFERENCES quizzes (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    remote_id TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('quiz', 'reveal')),
    published_at TEXT NOT NULL,
    FOREIGN KEY (quiz_id) REFERENCES quizzes (id) ON DELETE CASCADE
);

-- Impede double-post em retries.
CREATE UNIQUE INDEX IF NOT EXISTS idx_publications_quiz_kind
    ON publications (quiz_id, kind);

CREATE TABLE IF NOT EXISTS scheduler_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_daily_post_date TEXT,
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO scheduler_state (id, last_daily_post_date, updated_at)
VALUES (1, NULL, datetime('now'));
