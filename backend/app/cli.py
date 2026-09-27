"""Admin CLI: python -m app.cli <command>."""

import argparse
import getpass
import sys
from datetime import date

from app.db import SessionLocal
from app.services import auth, fx
from app.services.common import DomainError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="create currencies, categories, accounts, rules (idempotent)")
    u = sub.add_parser("create-user", help="create a login")
    u.add_argument("--email", required=True)
    u.add_argument("--name", required=True)
    u.add_argument("--admin", action="store_true")
    u.add_argument("--locale", default="en", choices=["en", "ru"])
    u.add_argument("--password", help="omit to be prompted")
    f = sub.add_parser("fetch-fx", help="fetch ECB/CBR rates")
    f.add_argument("--since", type=date.fromisoformat)
    sub.add_parser("backup", help="write a consistent SQLite backup now")
    args = parser.parse_args(argv)

    with SessionLocal() as session:
        try:
            if args.cmd == "seed":
                from app.seed import seed

                print(seed(session) or "nothing to create")
            elif args.cmd == "create-user":
                password = args.password or getpass.getpass("Password: ")
                user = auth.create_user(session, args.email, args.name, password,
                                        role="admin" if args.admin else "member", locale=args.locale)
                print(f"created user {user.id} {user.email}")
            elif args.cmd == "fetch-fx":
                since = args.since or fx.default_since(session)
                try:
                    n = fx.fetch_rates(session, since, {"USD", "GBP", "RUB"})
                except fx.FxFetchError as e:
                    n = e.stored
                    print(f"warning: {e}", file=sys.stderr)
                print(f"{n} rates stored since {since}; recomputed {fx.recompute_estimated(session)} rows")
            elif args.cmd == "backup":
                from app.jobs import backup

                print(backup())
            session.commit()
        except DomainError as e:
            print(f"error: {e.message}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
