from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys

from app.bootstrap import bootstrap_store
from app.core.config import get_settings
from app.core.errors import DomainError
from app.demo_seed import seed_demo_store
from app.persistence.database import Database


def prompt_owner_password() -> str:
    password = getpass.getpass("Owner password: ")
    confirmation = getpass.getpass("Confirm owner password: ")
    if password != confirmation:
        raise ValueError("Owner password confirmation does not match")
    return password


async def run_bootstrap(args: argparse.Namespace) -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        async with database.session_factory() as session, session.begin():
            result = await bootstrap_store(
                session,
                settings,
                tenant_code=args.tenant_code,
                tenant_name=args.tenant_name,
                legal_entity_code=args.legal_entity_code,
                legal_entity_name=args.legal_entity_name,
                store_code=args.store_code,
                store_name=args.store_name,
                owner_username=args.owner_username,
                owner_display_name=args.owner_display_name,
                owner_password=args.owner_password,
            )
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    finally:
        await database.dispose()


async def run_seed_demo() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        async with database.session_factory() as session, session.begin():
            result = await seed_demo_store(session, settings)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="SipPilot Edge API administration")
    subparsers = parser.add_subparsers(dest="command", required=True)
    bootstrap_parser = subparsers.add_parser(
        "bootstrap-store", help="Create the first tenant, store, owner, and device credentials"
    )
    bootstrap_parser.add_argument("--tenant-code", required=True)
    bootstrap_parser.add_argument("--tenant-name", required=True)
    bootstrap_parser.add_argument("--legal-entity-code", required=True)
    bootstrap_parser.add_argument("--legal-entity-name", required=True)
    bootstrap_parser.add_argument("--store-code", required=True)
    bootstrap_parser.add_argument("--store-name", required=True)
    bootstrap_parser.add_argument("--owner-username", required=True)
    bootstrap_parser.add_argument("--owner-display-name", required=True)
    bootstrap_parser.add_argument(
        "--owner-password",
        help=(
            "Owner password (omit to use a hidden prompt; command-line values can be visible "
            "in shell history)"
        ),
    )
    subparsers.add_parser(
        "seed-demo",
        help="Create or verify the development-only Netherlands demo store",
    )
    args = parser.parse_args()
    try:
        if args.command == "bootstrap-store":
            if args.owner_password is None:
                args.owner_password = prompt_owner_password()
            asyncio.run(run_bootstrap(args))
        elif args.command == "seed-demo":
            asyncio.run(run_seed_demo())
    except (DomainError, EOFError, ValueError) as exc:
        print(f"{args.command} failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        print(f"{args.command} cancelled", file=sys.stderr)
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
