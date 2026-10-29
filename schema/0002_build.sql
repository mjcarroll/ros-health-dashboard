-- One row per Jenkins build: enough to draw the nightly matrix and link back.
-- Only recent builds are kept by the collector; this is not a build archive.
CREATE TABLE IF NOT EXISTS build (
  server      TEXT    NOT NULL,   -- e.g. 'ci.ros2.org'
  grp         TEXT    NOT NULL,   -- matrix section, e.g. 'nightly' or 'Rci'
  job         TEXT    NOT NULL,
  number      INTEGER NOT NULL,
  ts          INTEGER NOT NULL,   -- build start, unix seconds
  result      TEXT    NOT NULL,   -- SUCCESS | UNSTABLE | FAILURE | ABORTED | NOT_BUILT | RUNNING
  duration_s  INTEGER NOT NULL,
  fail        INTEGER,            -- failed tests, NULL when the build has no test report
  skip        INTEGER,
  total       INTEGER,
  url         TEXT    NOT NULL,
  PRIMARY KEY (server, job, number)
);
CREATE INDEX IF NOT EXISTS build_ts ON build (ts);
