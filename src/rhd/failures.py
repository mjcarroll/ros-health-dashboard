from .models import FailureSnapshot


def reconcile(store, ts: int, snap: FailureSnapshot) -> list[tuple[str, list]]:
    """Statements that bring the open failures for snap.scope in line with the snapshot:
    insert new ones, update changed ones, close ones that disappeared."""
    open_rows = {
        (r["distro"], r["col"], r["pkg"]): r
        for r in store.query(
            "SELECT distro, col, pkg, state, jenkins, version, url, first_seen "
            "FROM pkg_failure WHERE distro = ? AND resolved IS NULL", [snap.scope])
    }
    stmts: list[tuple[str, list]] = []
    current = {f.key: f for f in snap.failures}
    for key, f in current.items():
        old = open_rows.get(key)
        if old is None:
            stmts.append((
                "INSERT INTO pkg_failure (distro, col, pkg, state, jenkins, version, url, first_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [f.distro, f.col, f.pkg, f.state, f.jenkins, f.version, f.url, ts]))
        elif (old["state"], old["jenkins"], old["version"], old["url"]) != f.detail:
            stmts.append((
                "UPDATE pkg_failure SET state = ?, jenkins = ?, version = ?, url = ? "
                "WHERE distro = ? AND col = ? AND pkg = ? AND first_seen = ?",
                [f.state, f.jenkins, f.version, f.url, f.distro, f.col, f.pkg, old["first_seen"]]))
    for key, old in open_rows.items():
        if key not in current:
            stmts.append((
                "UPDATE pkg_failure SET resolved = ? "
                "WHERE distro = ? AND col = ? AND pkg = ? AND first_seen = ?",
                [ts, *key, old["first_seen"]]))
    return stmts
