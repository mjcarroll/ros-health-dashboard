-- Packages whose build is missing/stale in the buildfarm 'building' repo, per platform column.
-- Rows are written on transitions only: resolved IS NULL means still failing.
CREATE TABLE IF NOT EXISTS pkg_failure (
  distro      TEXT    NOT NULL,   -- 'rolling', 'lyrical', ...
  col         TEXT    NOT NULL,   -- platform column short name, e.g. 'R64'
  pkg         TEXT    NOT NULL,
  state       TEXT    NOT NULL,   -- 'missing' (no deb) | 'stale' (only an older version)
  jenkins     TEXT,               -- result of the Jenkins job: FAILURE | ABORTED | UNSTABLE | ...
  version     TEXT,
  url         TEXT    NOT NULL,   -- the Jenkins job
  first_seen  INTEGER NOT NULL,
  resolved    INTEGER,
  PRIMARY KEY (distro, col, pkg, first_seen)
);
CREATE INDEX IF NOT EXISTS pkg_failure_open ON pkg_failure (distro, resolved);
