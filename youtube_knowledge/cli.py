"""Small machine-readable CLI; diagnostics and progress stay on stderr."""

import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys

from . import __version__, config


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="yk", description="Extract YouTube knowledge for your Obsidian vault.")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--json", action="store_true", help="Print one JSON result")
    commands = root.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="Fetch transcript, metadata, video and frames")
    fetch.add_argument("url")
    fetch.add_argument("--workdir", type=Path, help="Exact directory, named yt_<video_id>")
    fetch.add_argument("--no-video", action="store_true", help="Skip video/frames; audio is still fetched for Whisper if necessary")
    keyframes = commands.add_parser("keyframes", help="Select visually distinct frames")
    keyframes.add_argument("workdir", type=Path)
    keyframes.add_argument("--threshold", type=float, default=12.0)
    keyframes.add_argument("--max", type=int, dest="maximum")
    check = commands.add_parser("check", help="Validate notes and links")
    check.add_argument("notes", type=Path, nargs="+")
    check.add_argument("--vault", required=True, type=Path)
    clean = commands.add_parser("clean", help="Release a lease; remove the workdir after its last lease")
    clean.add_argument("workdir", help="Exact absolute workdir returned by fetch")
    clean.add_argument("--lease", required=True, help="Lease token returned by that fetch")
    commands.add_parser("doctor", help="Check installed dependencies, vault and skill")
    settings = commands.add_parser("config", help="Read or write user configuration")
    settings.add_argument("action", choices=("get", "set"), nargs="?", default="get")
    settings.add_argument("key", nargs="?", choices=tuple(config.DEFAULTS))
    settings.add_argument("value", nargs="?")
    for command in commands.choices.values():
        command.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    return root


def execute(args) -> dict:
    if args.command == "config":
        if args.action == "set":
            if args.key is None or args.value is None:
                raise ValueError("Usage: yk config set <key> <value>")
            return config.set_value(args.key, args.value)
        if args.value is not None:
            raise ValueError("config get does not accept a value")
        return {args.key: config.get(args.key)} if args.key else config.load()
    if args.command == "fetch":
        from .fetch import fetch
        return fetch(args.url, args.workdir, args.no_video)
    if args.command == "keyframes":
        from .keyframes import select
        return select(args.workdir.expanduser(), args.threshold, args.maximum)
    if args.command == "check":
        from .check import validate_notes
        return validate_notes(args.notes, args.vault, config.get("no_dashes"))
    if args.command == "clean":
        from .fetch import clean
        return clean(args.workdir, args.lease)
    if args.command == "doctor":
        from .doctor import diagnose
        return diagnose()
    raise ValueError("Unknown command")


def display(result: dict, command: str):
    if command == "doctor":
        color = sys.stdout.isatty()
        for check in result["checks"]:
            label = "OK" if check["ok"] else "FAIL"
            if color:
                label = f"\033[{32 if check['ok'] else 31}m{label}\033[0m"
            print(f"{label} {check['name']}: {check['detail']}")
    elif command == "check":
        for item in result["files"]:
            print(f"{'OK' if item['ok'] else 'FAIL'} {item['path']}: {item['lines']} non-blank lines")
            for error in item["errors"]:
                print(f"  {error}")
    elif command == "fetch":
        print(f"Fetched {result['title']}: {result['transcript_source']} transcript, {result['frame_count']} frames")
        print(f"workdir: {result['workdir']}")
        print(f"lease: {result['lease']}")
        for warning in result.get("warnings", []):
            print(f"Warning: {warning}", file=sys.stderr)
    elif command == "keyframes":
        print(f"Selected {result['keyframe_count']} of {result['frame_count']} frames. Wrote keyframes.json.")
        if result["truncated"]:
            print("The requested cap omitted visual changes. Rerun without --max for complete analysis.")
    elif command == "clean":
        print(f"{'Removed' if result['removed'] else 'Lease released; workdir retained'}: {result['workdir']}")
    else:
        for key, value in result.items():
            print(f"{key}: {str(value).lower() if isinstance(value, bool) else value}")


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        with redirect_stdout(sys.stderr):
            result = execute(args)
    except (Exception, KeyboardInterrupt) as exc:
        message = str(exc) or "Interrupted. Completed artifacts are retained for retry."
        if args.json:
            print(json.dumps({"ok": False, "error": message}, ensure_ascii=True))
        else:
            print(f"Error: {message}", file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    if args.json:
        print(json.dumps(result, ensure_ascii=True))
    else:
        display(result, args.command)
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
