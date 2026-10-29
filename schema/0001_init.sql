-- Generic top-line time series. New collectors add metrics, never columns.
CREATE TABLE IF NOT EXISTS observation (
  ts      INTEGER NOT NULL,           -- unix seconds, collection time
  source  TEXT    NOT NULL,           -- collector name, e.g. 'rosdistro'
  metric  TEXT    NOT NULL,           -- e.g. 'open_prs'
  labels  TEXT    NOT NULL DEFAULT '{}', -- canonical JSON (sorted keys)
  value   REAL    NOT NULL,
  PRIMARY KEY (ts, source, metric, labels)
);
CREATE INDEX IF NOT EXISTS observation_series
  ON observation (source, metric, labels, ts);
