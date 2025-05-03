CREATE TABLE IF NOT EXISTS marinas (
  id          TEXT         PRIMARY KEY,
  html_bruto  TEXT,
  pdf_text     TEXT,
  updated_at  TIMESTAMPTZ  NOT NULL,
  CHECK (html_bruto IS NOT NULL OR pdf_text IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS marinas_history (
  id          TEXT         NOT NULL,
  html_bruto  TEXT,
  pdf_text    TEXT,
  updated_at  TIMESTAMPTZ  NOT NULL,
  CHECK (html_bruto IS NOT NULL OR pdf_text IS NOT NULL)
);
