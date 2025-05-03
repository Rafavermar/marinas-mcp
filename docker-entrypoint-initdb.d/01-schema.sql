CREATE TABLE IF NOT EXISTS marinas (
  id          TEXT         PRIMARY KEY,
  html_bruto  TEXT         NOT NULL,
  updated_at  TIMESTAMPTZ  NOT NULL
);

CREATE TABLE IF NOT EXISTS marinas_history (
  id          TEXT         NOT NULL,
  html_bruto  TEXT         NOT NULL,
  updated_at  TIMESTAMPTZ  NOT NULL
);
