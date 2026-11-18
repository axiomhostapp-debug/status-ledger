# Status Ledger

A small incident-tracking service for a fictional hosting provider. It keeps incident
history in SQLite, renders a monochrome status dashboard, and exposes read-only JSON endpoints. It does not monitor
real servers, contact customers, or contain production data.

## Run

Python 3.10+; standard library only. From this directory:

```sh
python -m unittest discover -s tests -v
# Optional: populate an empty database with synthetic examples
python seed_demo.py
# Or record your own synthetic incident:
python cli.py create 'Demo DNS' 'Slow lookups' 'Investigating synthetic failures'
python cli.py status
python server.py --port 8080
# Open http://127.0.0.1:8080/ for the dashboard.
# In another terminal:
curl http://127.0.0.1:8080/api/status
```

Use the ID and version returned by `create` to update an incident:

```sh
python cli.py update INCIDENT_ID identified 'Found a synthetic configuration error' --version 1
python cli.py update INCIDENT_ID monitoring 'Demo fix applied' --version 2
python cli.py update INCIDENT_ID resolved 'Checks are healthy' --version 3
```

`--db PATH` is available on both commands (put it before the CLI subcommand).
The default is `demo.sqlite3`. It is ignored by Git.

## Design

- `ledger.py`: validation, incident transitions, transactional event history.
- `cli.py`: local writes. No public mutation endpoint or authentication claims.
- `dashboard.py`: escaped server-rendered HTML, system fonts, responsive layout,
  newest-first incident timelines and separate active/resolved sections. No scripts,
  tracking, external assets or automatic refresh.
- `seed_demo.py`: synthetic DNS/storage incidents; refuses a nonempty database.
- `server.py`: loopback-only HTTP dashboard at `/` and API. `GET /api/status` and
  `GET /api/incidents/ID`; unknown routes return 404, mutations are unsupported.
- `tests/`: lifecycle, persistence, stale-write conflicts, rollback, input
  boundaries, SQL-looking text, HTML escaping, real simultaneous competing writers,
  safe demo seeding and actual HTTP requests.

State flow: investigating → identified → monitoring → resolved. Investigating and
identified may resolve directly; monitoring may return to identified. Resolved
incidents are terminal: create another incident for a recurrence. Repeating a
transition is an error, not a new event.

Every transition requires the version the caller last saw. SQLite's immediate
transaction serializes writers before reading that version. A stale update fails
without appending an event. State and event writes commit together or roll back
together. Related incident/event reads and a full dashboard render use a shared
read transaction so a concurrent writer cannot mix old state with new history.
The status is degraded while **any** incident is unresolved, so closing
one incident cannot hide another. Times are UTC; integer event order avoids ties.

## Boundaries and next steps

This is a local demonstration, not a production status platform. The standard
library server is deliberately single-threaded and must not be exposed publicly.
It has no authentication, migrations, notifications, uptime calculation, pagination,
severity levels, or service registry. Database files must remain trusted and local.
Event history is append-only through this code, not cryptographically tamper-proof.
Tests inject reported failures; they do not establish power-loss durability.

Next useful changes: a versioned schema migration, paginated incident history,
and sustained concurrent-writer stress tests. The current race test verifies two
competing connections with the same expected version: exactly one commits. A public deployment would need a production
HTTP server, access controls, operational monitoring and an explicit data policy.

## License

Provided for code review. No open-source license is granted.
