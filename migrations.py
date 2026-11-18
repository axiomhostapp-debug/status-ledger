"""Transactional schema upgrades. Version zero includes the original unversioned DB."""
SCHEMA_VERSION = 2
MIGRATIONS = {
    1: (
        'CREATE TABLE IF NOT EXISTS incidents ('
        'id TEXT PRIMARY KEY, service TEXT NOT NULL, title TEXT NOT NULL, '
        'state TEXT NOT NULL, version INTEGER NOT NULL)',
        'CREATE TABLE IF NOT EXISTS events ('
        'sequence INTEGER PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id), '
        'state TEXT NOT NULL, message TEXT NOT NULL, at TEXT NOT NULL)',
    ),
    2: (
        'CREATE TABLE notices ('
        'id TEXT PRIMARY KEY, service TEXT NOT NULL, title TEXT NOT NULL, '
        'message TEXT NOT NULL, published_at TEXT NOT NULL)',
    ),
}


def migrate(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version > SCHEMA_VERSION:
        raise ValueError('Database schema is newer than this application supports')
    if version == SCHEMA_VERSION:
        return
    with db:
        db.execute('BEGIN IMMEDIATE')
        # Another process may have completed the upgrade while we waited.
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise ValueError('Database schema is newer than this application supports')
        for target in range(version + 1, SCHEMA_VERSION + 1):
            for statement in MIGRATIONS[target]:
                db.execute(statement)
            db.execute(f'PRAGMA user_version={target}')
