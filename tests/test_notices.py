import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from dashboard import render
from ledger import Ledger
from migrations import MIGRATIONS, migrate


class MigrationTests(unittest.TestCase):
    def test_original_database_upgrade_preserves_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.sqlite3'
            db = sqlite3.connect(path)
            for sql in MIGRATIONS[1]:
                db.execute(sql)
            db.execute("INSERT INTO incidents VALUES ('old','DNS','Outage','investigating',1)")
            db.execute("INSERT INTO events VALUES (1,'old','investigating','Original report','2026-01-01T10:00:00+00:00')")
            db.commit()
            db.close()
            for _ in range(2):
                store = Ledger(path)
                try:
                    self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 2)
                    self.assertEqual(store.get('old')['events'][0]['message'], 'Original report')
                    self.assertEqual(store.status()['status'], 'degraded')
                    self.assertEqual(store.notices(), [])
                finally:
                    store.close()

    def test_two_openers_upgrade_once(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'concurrent.sqlite3'
            gate = threading.Barrier(2)
            def opener(_):
                gate.wait(timeout=5)
                store = Ledger(path)
                try:
                    return store.db.execute('PRAGMA user_version').fetchone()[0]
                finally:
                    store.close()
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(list(pool.map(opener, range(2))), [2, 2])

    def test_version_one_upgrade(self):
        db = sqlite3.connect(':memory:')
        try:
            for sql in MIGRATIONS[1]:
                db.execute(sql)
            db.execute('PRAGMA user_version=1')
            migrate(db)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT * FROM notices').fetchall(), [])
        finally:
            db.close()

    def test_failed_upgrade_is_atomic(self):
        db = sqlite3.connect(':memory:')
        try:
            with patch.dict(MIGRATIONS, {2: ('CREATE TABLE temporary_notice(id TEXT)', 'INVALID SQL')}):
                with self.assertRaises(sqlite3.OperationalError):
                    migrate(db)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])
            migrate(db)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
        finally:
            db.close()

    def test_newer_schema_rejected_without_changes(self):
        db = sqlite3.connect(':memory:')
        try:
            db.execute('PRAGMA user_version=999')
            with self.assertRaisesRegex(ValueError, 'newer'):
                migrate(db)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 999)
        finally:
            db.close()


class NoticeTests(unittest.TestCase):
    def setUp(self):
        self.store = Ledger(':memory:')
        self.addCleanup(self.store.close)

    def test_notice_alone_remains_operational(self):
        notice = self.store.publish_notice('Demo DNS', 'Documentation update', 'New configuration examples')
        self.assertEqual(self.store.status(), {'status': 'operational', 'incidents': []})
        self.assertEqual(self.store.notices(), [notice])
        html = render(self.store)
        self.assertIn('No incidents reported', html)
        self.assertIn('Informational notice', html)
        self.assertIn('Published <time', html)

    def test_same_day_outage_and_notice_keep_independent_timestamps(self):
        with patch('ledger.datetime') as clock:
            clock.now.return_value.isoformat.return_value = '2026-11-18T09:00:00+00:00'
            incident = self.store.create('Demo DNS', 'Resolver outage', 'Investigating')
            clock.now.return_value.isoformat.return_value = '2026-11-18T12:00:00+00:00'
            self.store.publish_notice('Demo DNS', 'Documentation refreshed', 'Information only')
        self.assertEqual(self.store.status()['status'], 'degraded')
        self.assertEqual(self.store.get(incident['id']), incident)
        html = render(self.store)
        self.assertIn('2026-11-18 09:00:00 UTC', html)
        self.assertIn('2026-11-18 12:00:00 UTC', html)
        self.assertIn('Incident update', html)
        self.assertIn('Informational notice', html)
        self.assertIn('Service disruption reported', html)
        self.store.transition(incident['id'], 'resolved', 'Recovered', 1)
        self.assertEqual(self.store.status()['status'], 'operational')
        self.assertEqual(len(self.store.notices()), 1)

    def test_notice_validation_and_escaping(self):
        for args in [('', 'title', 'message'), ('demo', 'x' * 161, 'message'), ('demo', 'title', '')]:
            with self.assertRaises(ValueError):
                self.store.publish_notice(*args)
        self.assertEqual(self.store.notices(), [])
        self.store.publish_notice('<script>x</script>', '<img src=x>', '<iframe>')
        html = render(self.store)
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img', html)
        self.assertNotIn('<iframe>', html)
        self.assertIn('&lt;iframe&gt;', html)
        self.assertIn('class="notice-message"', html)

    def test_notice_persists_across_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite3'
            store = Ledger(path)
            notice = store.publish_notice('Demo', 'Update', 'Information only')
            store.close()
            store = Ledger(path)
            try:
                self.assertEqual(store.notices(), [notice])
                self.assertEqual(store.status()['status'], 'operational')
            finally:
                store.close()


class NoticeCLITests(unittest.TestCase):
    def test_publish_and_list_cli(self):
        import subprocess
        import sys
        import json
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'cli.py'),
                       '--db', str(Path(directory) / 'cli.sqlite3')]
            notice = json.loads(subprocess.check_output(command + ['notice', 'Demo', 'Docs updated', 'Information only'], text=True))
            listed = json.loads(subprocess.check_output(command + ['notices'], text=True))
            status = json.loads(subprocess.check_output(command + ['status'], text=True))
            self.assertEqual(listed, [notice])
            self.assertEqual(status['status'], 'operational')
