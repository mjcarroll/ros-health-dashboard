-- Failing tests only (never passes), for recent builds on servers that expose test reports.
CREATE TABLE IF NOT EXISTS test_failure (
  server  TEXT    NOT NULL,
  job     TEXT    NOT NULL,
  number  INTEGER NOT NULL,   -- build number
  ts      INTEGER NOT NULL,   -- build start, unix seconds
  class   TEXT    NOT NULL,
  name    TEXT    NOT NULL,
  age     INTEGER,            -- consecutive builds this test has been failing, as of this build
  since   INTEGER,            -- build number it started failing in
  PRIMARY KEY (server, job, number, class, name)
);
CREATE INDEX IF NOT EXISTS test_failure_ts ON test_failure (ts);

-- Builds whose test report has been fetched, including ones with no failing tests.
CREATE TABLE IF NOT EXISTS test_fetch (
  server  TEXT    NOT NULL,
  job     TEXT    NOT NULL,
  number  INTEGER NOT NULL,
  ts      INTEGER NOT NULL,
  PRIMARY KEY (server, job, number)
);
