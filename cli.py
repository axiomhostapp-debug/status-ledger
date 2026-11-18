"""Local administration: python cli.py --help."""
import argparse
import json
from ledger import Ledger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="demo.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    create = commands.add_parser("create")
    create.add_argument("service")
    create.add_argument("title")
    create.add_argument("message")
    update = commands.add_parser("update")
    update.add_argument("id")
    update.add_argument("state")
    update.add_argument("message")
    update.add_argument("--version", type=int, required=True)
    args = parser.parse_args()
    store = Ledger(args.db)
    try:
        if args.command == "create":
            result = store.create(args.service, args.title, args.message)
        elif args.command == "update":
            result = store.transition(args.id, args.state, args.message, args.version)
        else:
            result = store.status()
        print(json.dumps(result, indent=2))
    except (ValueError, KeyError) as exc:
        parser.exit(2, f"error: {exc}\n")
    finally:
        store.close()


if __name__ == "__main__":
    main()
