-- Why a FAILURE build failed, when we could tell. Absence means "treat as a real failure".
CREATE TABLE IF NOT EXISTS build_class (
  server  TEXT    NOT NULL,
  job     TEXT    NOT NULL,
  number  INTEGER NOT NULL,
  ts      INTEGER NOT NULL,   -- build start, unix seconds (for retention)
  kind    TEXT    NOT NULL,   -- 'infra' | 'code' (console checked, no infra signature) | 'unknown'
  reason  TEXT,
  PRIMARY KEY (server, job, number)
);
