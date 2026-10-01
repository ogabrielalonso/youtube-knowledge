"""Validate note schema, substantive line counts, and Obsidian note links."""

from pathlib import Path
import re
from datetime import date
import math

from markdown_it import MarkdownIt

import yaml

REQUIRED = {"source", "type", "title", "description", "source_title", "source_url", "channel",
            "duration", "upload_date", "tags", "status", "created", "modified", "parent", "related"}
MIN_LINES = {"moc": 150, "insight": 50, "tactic": 50, "principle": 50}
NULLABLE_SOURCE = {"source_title", "channel", "duration", "upload_date"}
TEXT_FIELDS = {"source", "type", "title", "description", "source_title", "source_url",
               "channel", "status"}
LINK = re.compile(r"\[\[([^\]\n]+)\]\]")


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicate fields instead of silently taking the last value."""


def unique_mapping(loader, node):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in mapping:
            raise ValueError(f"Duplicate frontmatter key: {key}")
        mapping[key] = loader.construct_object(value_node)
    return mapping


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def body_text(lines: list[str]) -> str:
    """Scan only rendered text, excluding every Markdown code context."""
    def texts(tokens):
        for token in tokens:
            if token.type == "text":
                yield token.content
            elif token.children and token.type not in {"code_inline", "code_block", "fence"}:
                yield from texts(token.children)

    return "\n".join(texts(MarkdownIt("commonmark").parse("\n".join(lines))))


def valid_date(value, compact: bool = False) -> bool:
    if type(value) is date:
        return True
    if not isinstance(value, str):
        return False
    if compact and re.fullmatch(r"[0-9]{8}", value):
        value = f"{value[:4]}-{value[4:6]}-{value[6:]}"
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def schema_errors(fields: dict) -> list[str]:
    errors = []
    for key in REQUIRED & fields.keys():
        value = fields[key]
        if value is None and key in NULLABLE_SOURCE | {"parent"}:
            continue
        if key in TEXT_FIELDS and (not isinstance(value, str) or not value.strip()):
            errors.append(f"{key} must be a nonempty string")
        elif key == "duration" and (
            isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or
            (isinstance(value, float) and not math.isfinite(value))
        ):
            errors.append("duration must be a finite nonnegative number")
        elif key in {"created", "modified", "upload_date"} and not valid_date(value, compact=key == "upload_date"):
            errors.append(f"{key} must be a valid calendar date in YYYY-MM-DD" +
                          (" or YYYYMMDD format" if key == "upload_date" else " format"))
        elif key == "status" and value != "active":
            errors.append("status must be active")
        elif key == "parent" and (not isinstance(value, str) or not LINK.fullmatch(value.strip())):
            errors.append("parent must be a quoted wikilink or null")
        elif key in {"tags", "related"} and (
            not isinstance(value, list) or (key == "tags" and not value) or
            any(not isinstance(item, str) or not item.strip() or
                (key == "related" and not LINK.fullmatch(item.strip())) for item in value)
        ):
            errors.append(f"{key} must be a list of nonempty strings" +
                          (" containing wikilinks" if key == "related" else ""))
    return errors


def validate_notes(notes: list[Path], vault: Path, no_dashes: bool = True) -> dict:
    vault = vault.expanduser().resolve()
    if not vault.is_dir():
        raise ValueError(f"Vault does not exist: {vault}")
    files = [p for p in vault.rglob("*") if p.is_file() and p.resolve().is_relative_to(vault)
             and not any(part.startswith(".") for part in p.relative_to(vault).parts)]
    by_name = {}
    for path in files:
        by_name.setdefault(path.name, []).append(path)
    results = []
    for note in notes:
        note = note.expanduser().resolve()
        errors = []
        try:
            text = note.read_text(encoding="utf-8")
        except OSError as exc:
            results.append({"path": str(note), "ok": False, "lines": 0, "errors": [str(exc)]})
            continue
        if not note.is_relative_to(vault):
            errors.append("Note must be inside the vault")
        lines = text.splitlines()
        real_lines = sum(bool(line.strip()) for line in lines)
        frontmatter = {}
        end = None
        try:
            if not lines or lines[0] != "---":
                raise ValueError("Missing YAML frontmatter")
            end = lines.index("---", 1)
            frontmatter = yaml.load("\n".join(lines[1:end]), Loader=UniqueLoader)
            if not isinstance(frontmatter, dict):
                raise ValueError("Frontmatter must be a mapping")
        except (ValueError, yaml.YAMLError, TypeError) as exc:
            errors.append(f"Invalid frontmatter: {exc}")
            frontmatter = {}
        missing = sorted(REQUIRED - set(frontmatter))
        if missing:
            errors.append(f"Missing frontmatter keys: {', '.join(missing)}")
        errors.extend(schema_errors(frontmatter))
        kind = str(frontmatter.get("type", "")).lower()
        if kind not in MIN_LINES:
            errors.append("type must be moc, insight, tactic, or principle")
        elif real_lines < MIN_LINES[kind]:
            errors.append(f"{kind} requires {MIN_LINES[kind]} non-blank lines; found {real_lines}")
        if no_dashes:
            for index, line in enumerate(lines, 1):
                if any(char in line for char in (chr(0x2013), chr(0x2014))):
                    errors.append(f"Forbidden dash at line {index}")
        front_links = "\n".join(str(frontmatter.get(key) or "") for key in ("parent", "related"))
        body = body_text(lines[end + 1:] if end is not None else lines)
        for raw in LINK.findall(front_links + "\n" + body):
            link = raw.split("|", 1)[0].split("#", 1)[0].strip()
            if not link:  # [[#heading]] refers to the current note.
                continue
            found = False
            for target in (link, link + ".md"):
                if "/" in target:
                    candidates = [(vault / target.lstrip("/")).resolve(),
                                  (note.parent / target).resolve()]
                    found = any(p.is_relative_to(vault) and p.is_file() for p in candidates)
                else:
                    found = bool(by_name.get(target))
                if found:
                    break
            if not found:
                errors.append(f"Broken link: [[{raw}]]")
        results.append({"path": str(note), "ok": not errors, "lines": real_lines, "errors": errors})
    return {"ok": all(item["ok"] for item in results), "files": results}
