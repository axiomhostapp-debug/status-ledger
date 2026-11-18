import json
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen, Request
from ledger import Conflict, Ledger
from server import handler


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "test.sqlite3"
        self.store = Ledger(self.path)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.store.close)

    def incident(self):
        return self.store.create("Demo DNS", "Slow lookups", "Investigating synthetic failures")

    def test_empty_status(self):
        self.assertEqual(self.store.status(), {"status": "operational", "incidents": []})

    def test_complete_lifecycle_persists_history(self):
        item = self.incident()
        for version, state in enumerate(("identified", "monitoring", "resolved"), 1):
            item = self.store.transition(item["id"], state, "Synthetic update", version)
        self.assertEqual([e["state"] for e in item["events"]],
                         ["investigating", "identified", "monitoring", "resolved"])
        other = Ledger(self.path)
        try:
            self.assertEqual(other.get(item["id"]), item)
            self.assertEqual(other.status()["status"], "operational")
        finally:
            other.close()

    def test_one_resolved_incident_does_not_hide_another(self):
        first = self.incident()
        self.incident()
        self.store.transition(first["id"], "resolved", "Recovered", 1)
        self.assertEqual(self.store.status()["status"], "degraded")

    def test_stale_writer_rejected_without_extra_event(self):
        item = self.incident()
        other = Ledger(self.path)
        try:
            self.store.transition(item["id"], "identified", "Cause found", 1)
            with self.assertRaises(Conflict):
                other.transition(item["id"], "resolved", "Outdated update", 1)
            self.assertEqual(len(other.get(item["id"])["events"]), 2)
        finally:
            other.close()

    def test_invalid_transition_is_unchanged(self):
        item = self.incident()
        for state in ("monitoring", "invented", "investigating"):
            with self.assertRaises(ValueError):
                self.store.transition(item["id"], state, "Update", 1)
            self.assertEqual(self.store.get(item["id"]), item)

    def test_resolved_incident_is_terminal(self):
        item = self.incident()
        self.store.transition(item["id"], "resolved", "Recovered", 1)
        with self.assertRaises(ValueError):
            self.store.transition(item["id"], "identified", "Reopen", 2)

    def test_event_failure_rolls_back_state(self):
        item = self.incident()
        with patch.object(self.store, "_event", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError):
                self.store.transition(item["id"], "identified", "Update", 1)
        self.assertEqual(self.store.get(item["id"]), item)

    def test_create_event_failure_rolls_back_incident(self):
        with patch.object(self.store, "_event", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError):
                self.incident()
        self.assertEqual(self.store.status()["incidents"], [])

    def test_blank_or_oversized_input_rejected(self):
        for value in ("", "  ", "x" * 81, None):
            with self.assertRaises(ValueError):
                self.store.create(value, "title", "message")
        self.assertEqual(self.store.status()["incidents"], [])

    def test_sql_looking_text_is_stored_as_data(self):
        title = "'); DROP TABLE incidents;--"
        item = self.store.create("demo", title, "Synthetic example")
        self.assertEqual(self.store.get(item["id"])["title"], title)

    def test_read_snapshot_does_not_mix_concurrent_versions(self):
        self.store.db.execute("PRAGMA journal_mode=WAL")
        item = self.incident()
        other = Ledger(self.path)
        fired = False
        def between_reads(sql):
            nonlocal fired
            if sql.startswith("SELECT state,message,at") and not fired:
                fired = True
                other.transition(item['id'], 'identified', 'Concurrent update', 1)
        try:
            self.store.db.set_trace_callback(between_reads)
            observed = self.store.get(item['id'])
            self.assertTrue(fired)
            self.assertEqual(observed, item)
            self.store.db.set_trace_callback(None)
            self.assertEqual(self.store.get(item['id'])['version'], 2)
        finally:
            self.store.db.set_trace_callback(None)
            other.close()

    def test_missing_incident(self):
        with self.assertRaises(KeyError):
            self.store.get("missing")

    def test_invalid_version(self):
        item = self.incident()
        for version in (True, "1", 0):
            with self.assertRaises(ValueError):
                self.store.transition(item["id"], "identified", "Update", version)


class HTTPTests(unittest.TestCase):
    def test_read_only_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "http.sqlite3")
            store = Ledger(path)
            item = store.create("Demo", "Synthetic outage", "Test only")
            store.close()
            server = HTTPServer(("127.0.0.1", 0), handler(path))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/", timeout=3) as response:
                    self.assertIn("text/html", response.headers["Content-Type"])
                    self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
                    self.assertIn("Synthetic outage", response.read().decode())
                with urlopen(base + "/api/status", timeout=3) as response:
                    self.assertEqual(json.load(response)["status"], "degraded")
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                with urlopen(base + "/api/incidents/" + item["id"], timeout=3) as response:
                    self.assertEqual(json.load(response)["id"], item["id"])
                for path in ("/missing", "/api/incidents/missing"):
                    with self.assertRaises(HTTPError) as exc:
                        urlopen(base + path, timeout=3)
                    self.assertEqual(exc.exception.code, 404)
                with self.assertRaises(HTTPError) as exc:
                    urlopen(Request(base + "/api/status", data=b"{}", method="POST"), timeout=3)
                self.assertEqual(exc.exception.code, 501)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


class ConcurrentTests(unittest.TestCase):
    def test_racing_writers_exactly_one_wins(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'race.sqlite3'
            store = Ledger(path)
            item = store.create('Demo', 'Concurrent update', 'Synthetic race')
            gate = threading.Barrier(2)
            def writer():
                connection = Ledger(path)
                try:
                    gate.wait(timeout=5)
                    try:
                        connection.transition(item['id'], 'identified', 'Cause found', 1)
                        return 'won'
                    except Conflict:
                        return 'conflict'
                finally:
                    connection.close()
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: writer(), range(2)))
                self.assertCountEqual(results, ['won', 'conflict'])
                actual = store.get(item['id'])
                self.assertEqual(actual['version'], 2)
                self.assertEqual(len(actual['events']), 2)
            finally:
                store.close()


class DashboardTests(unittest.TestCase):
    def test_escapes_all_untrusted_content(self):
        from dashboard import render
        store = Ledger(':memory:')
        try:
            store.create('<script>service</script>', '<img src=x onerror=alert(1)>', '<iframe>message</iframe>')
            html = render(store)
            self.assertNotIn('<script>', html)
            self.assertNotIn('<img', html)
            self.assertNotIn('<iframe>', html)
            self.assertIn('&lt;script&gt;service&lt;/script&gt;', html)
            self.assertIn('Service disruption reported', html)
        finally:
            store.close()

    def test_empty_board_is_not_a_monitoring_claim(self):
        from dashboard import render
        store = Ledger(':memory:')
        try:
            html = render(store)
            self.assertIn('No incidents reported', html)
            self.assertIn('does not measure uptime', html)
            self.assertIn('No active incidents.', html)
        finally:
            store.close()

    def test_seed_is_synthetic_and_refuses_existing_data(self):
        from seed_demo import seed
        store = Ledger(':memory:')
        try:
            seed(store)
            before = store.status()
            self.assertEqual(len(before['incidents']), 2)
            with self.assertRaises(ValueError):
                seed(store)
            self.assertEqual(store.status(), before)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
