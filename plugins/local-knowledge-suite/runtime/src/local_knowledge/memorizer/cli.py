# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from .core import (
    MemorizerError,
    backlinks,
    capture,
    distill,
    graph,
    init_vault,
    link,
    pin,
    rebuild_index,
    search,
    show,
    status,
    touch,
    validate_vault,
)


class MemorizerArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise MemorizerError(f"invalid arguments: {message}")


def _read_input(value: str) -> Any:
    try:
        if value == "-":
            return json.load(sys.stdin)
        return json.loads(Path(value).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise MemorizerError(f"cannot read capture input {value!r}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise MemorizerError(f"capture input is not valid JSON: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = MemorizerArgumentParser(
        prog="memorizer",
        description="Capture, distill, link, and retrieve a workspace-local memory vault.",
    )
    parser.add_argument("--root", default=".", help="workspace root; defaults to the current directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="initialize .memorizer in the workspace")

    capture_parser = subparsers.add_parser("capture", help="append a redacted heartbeat and distill it immediately")
    capture_parser.add_argument("--input", required=True, help="JSON file path or - for standard input")
    capture_parser.add_argument(
        "--defer",
        action="store_true",
        help="append only; leave distillation pending for recovery or an intentional batch",
    )

    subparsers.add_parser("distill", help="distill every pending heartbeat")

    search_parser = subparsers.add_parser("search", help="retrieve ranked memories")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("--include-superseded", action="store_true")

    show_parser = subparsers.add_parser("show", help="show one memory and count a revisit")
    show_parser.add_argument("memory_id")
    show_parser.add_argument("--no-touch", action="store_true", help="do not increment the revisit counter")

    pin_parser = subparsers.add_parser("pin", help="pin or unpin a memory")
    pin_parser.add_argument("memory_id")
    pin_parser.add_argument("--off", action="store_true")

    touch_parser = subparsers.add_parser("touch", help="increment a memory's revisit counter")
    touch_parser.add_argument("memory_id")

    link_parser = subparsers.add_parser("link", help="add a typed relation between existing nodes")
    link_parser.add_argument("source_id")
    link_parser.add_argument("target_id")
    link_parser.add_argument("--type", required=True, dest="relation_type")

    backlinks_parser = subparsers.add_parser("backlinks", help="list memories linking to a node")
    backlinks_parser.add_argument("target_id")

    graph_parser = subparsers.add_parser("graph", help="export the knowledge graph")
    graph_parser.add_argument("--format", choices=("json", "mermaid"), default="json")

    subparsers.add_parser("rebuild", help="atomically rebuild the derived SQLite index")
    subparsers.add_parser("validate", help="validate events, Markdown, links, and index consistency")
    subparsers.add_parser("status", help="show event, memory, and pending counts")
    return parser


def run(args: argparse.Namespace) -> Any:
    root = Path(args.root)
    if args.command == "init":
        return init_vault(root)
    if args.command == "capture":
        return capture(root, _read_input(args.input), defer=args.defer)
    if args.command == "distill":
        return distill(root)
    if args.command == "search":
        return search(root, args.query, args.limit, args.include_superseded)
    if args.command == "show":
        return show(root, args.memory_id, touch=not args.no_touch)
    if args.command == "pin":
        return pin(root, args.memory_id, pinned=not args.off)
    if args.command == "touch":
        return touch(root, args.memory_id)
    if args.command == "link":
        return link(root, args.source_id, args.target_id, args.relation_type)
    if args.command == "backlinks":
        return backlinks(root, args.target_id)
    if args.command == "graph":
        return graph(root, args.format)
    if args.command == "rebuild":
        return rebuild_index(root)
    if args.command == "validate":
        result = validate_vault(root)
        if not result["valid"]:
            raise MemorizerError("vault validation failed", result)
        return result
    if args.command == "status":
        return status(root)
    raise MemorizerError(f"unsupported command {args.command!r}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        result = run(args)
    except MemorizerError as exc:
        details = exc.args[1] if len(exc.args) > 1 and isinstance(exc.args[1], dict) else None
        payload = {"ok": False, "error": str(exc.args[0])}
        if details:
            payload["details"] = details
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error) as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    if isinstance(result, str):
        print(result, end="" if result.endswith("\n") else "\n")
    else:
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
