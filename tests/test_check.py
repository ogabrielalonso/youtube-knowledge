import pytest
import yaml

from youtube_knowledge.check import REQUIRED, validate_notes


def note(vault, body="", kind="insight", count=60):
    fields = {key: "Example" for key in REQUIRED}
    fields.update(type=kind, tags=["learning"], related=[], parent=None,
                  duration=60, status="active", source_url="https://www.youtube.com/watch?v=abcdefghijk",
                  created="2026-10-01", modified="2026-10-01", upload_date="20261001")
    text = "---\n" + yaml.safe_dump(fields) + "---\n" + body + "\n"
    text += "\n".join(f"Specific point {i}." for i in range(count))
    path = vault / "Note.md"
    path.write_text(text)
    return path


def test_alias_heading_and_relative_links(tmp_path):
    folder = tmp_path / "cluster"
    folder.mkdir()
    (folder / "Sibling.md").write_text("# Heading\n")
    path = note(tmp_path, "[[Sibling|alias]] [[Sibling#Heading]] [[cluster/Sibling.md#Heading|label]] [[#Local]]")
    assert validate_notes([path], tmp_path)["ok"]


def test_broken_link(tmp_path):
    result = validate_notes([note(tmp_path, "[[Missing#Heading|alias]]")], tmp_path)
    assert not result["ok"]
    assert "Broken link" in result["files"][0]["errors"][0]


@pytest.mark.parametrize("codepoint", [0x2013, 0x2014])
def test_dashes_and_config_optout(tmp_path, codepoint):
    path = note(tmp_path, "A" + chr(codepoint) + "B")
    assert not validate_notes([path], tmp_path)["ok"]
    assert validate_notes([path], tmp_path, no_dashes=False)["ok"]


@pytest.mark.parametrize("kind,count", [("insight", 2), ("moc", 60)])
def test_short_notes_ignore_blank_lines(tmp_path, kind, count):
    path = note(tmp_path, "\n" * 200, kind=kind, count=count)
    result = validate_notes([path], tmp_path)
    assert not result["ok"]
    assert any("non-blank lines" in error for error in result["files"][0]["errors"])


def test_required_keys_and_duplicate_yaml(tmp_path):
    path = tmp_path / "Bad.md"
    path.write_text("---\ntype: insight\ntype: moc\n---\n")
    errors = validate_notes([path], tmp_path)["files"][0]["errors"]
    assert any("Duplicate" in error for error in errors)
    assert any("Missing frontmatter keys" in error for error in errors)


def test_link_cannot_escape_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (tmp_path / "Outside.md").write_text("private")
    path = note(vault, "[[../Outside]]")
    assert not validate_notes([path], vault)["ok"]


def test_attachment_links_and_embed_aliases(tmp_path):
    folder = tmp_path / "assets"
    folder.mkdir()
    (folder / "diagram.png").write_bytes(b"png")
    (folder / "paper.pdf").write_bytes(b"pdf")
    path = note(tmp_path, "![[diagram.png|preview]] [[assets/paper.pdf|paper]] ![[assets/diagram.png#page=1|image]]")
    assert validate_notes([path], tmp_path)["ok"]


def test_code_links_ignored_but_frontmatter_links_checked(tmp_path):
    path = note(tmp_path, "`[[InlineExample]]`\n~~~md\n[[FencedExample]]\n~~~\n")
    assert validate_notes([path], tmp_path)["ok"]
    content = path.read_text().replace("parent: null", "parent: '[[MissingParent]]'")
    path.write_text(content)
    assert any("MissingParent" in error for error in validate_notes([path], tmp_path)["files"][0]["errors"])


@pytest.mark.parametrize("field,value", [
    ("title", None), ("description", ""), ("tags", "not-a-list"),
    ("related", 7), ("related", ["plain text"]), ("tags", [7]),
    ("duration", "not-a-number"), ("source_url", None),
])
def test_frontmatter_value_schema(tmp_path, field, value):
    path = note(tmp_path)
    content = path.read_text()
    data = yaml.safe_load(content.split("---", 2)[1])
    data[field] = value
    path.write_text("---\n" + yaml.safe_dump(data) + "---\n" + content.split("---", 2)[2])
    assert not validate_notes([path], tmp_path)["ok"]


def test_unavailable_source_fields_can_be_null(tmp_path):
    path = note(tmp_path)
    content = path.read_text()
    data = yaml.safe_load(content.split("---", 2)[1])
    for field in ("source_title", "channel", "duration", "upload_date"):
        data[field] = None
    path.write_text("---\n" + yaml.safe_dump(data) + "---\n" + content.split("---", 2)[2])
    assert validate_notes([path], tmp_path)["ok"]


def test_source_dash_normalization_contract(tmp_path):
    from pathlib import Path

    skill = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text()
    assert "frontmatter `source_title`" in skill
    assert "hyphen with surrounding spaces" in skill
    source = "Part A" + chr(0x2014) + "Part B"
    path = note(tmp_path, "> " + source.replace(chr(0x2014), " - "))
    path.write_text(path.read_text().replace("source_title: Example", "source_title: " + source.replace(chr(0x2014), " - ")))
    assert validate_notes([path], tmp_path)["ok"]


@pytest.mark.parametrize("body", [
    "> ```md\n> [[MissingExample]]\n> ```\n",
    "- item\n\n  ```md\n  [[MissingExample]]\n  ```\n",
    "    [[MissingExample]]\n",
    "`line one\n[[MissingExample]]\nline three`\n",
    "``line ` one\n[[MissingExample]]\nline three``\n",
])
def test_markdown_parser_ignores_all_code_contexts(tmp_path, body):
    assert validate_notes([note(tmp_path, body)], tmp_path)["ok"]
    result = validate_notes([note(tmp_path, body + "\n[[ActuallyMissing]]")], tmp_path)
    assert any("ActuallyMissing" in error for error in result["files"][0]["errors"])


@pytest.mark.parametrize("target", ["API.v2", "cluster/API.v2", "API.v2.md", "cluster/API.v2.md", "LICENSE", "cluster/LICENSE"])
def test_exact_and_dotted_link_resolution(tmp_path, target):
    folder = tmp_path / "cluster"
    folder.mkdir()
    (folder / "API.v2.md").write_text("Note")
    (folder / "LICENSE").write_text("Attachment")
    assert validate_notes([note(tmp_path, f"[[{target}|alias]]")], tmp_path)["ok"]


@pytest.mark.parametrize("field,value", [
    ("created", "not-a-date"), ("created", "2026-02-29"), ("created", "20261001"),
    ("modified", "2026-99-99"), ("modified", "2026-10-01T12:00:00"),
    ("upload_date", "20260229"), ("upload_date", "2026-04-31"),
    ("upload_date", 20261001), ("duration", float("nan")),
    ("duration", float("inf")), ("duration", -1), ("duration", True), ("status", "wrong"),
])
def test_schema_rejects_invalid_values(tmp_path, field, value):
    path = note(tmp_path)
    _, front, body = path.read_text().split("---", 2)
    fields = yaml.safe_load(front)
    fields[field] = value
    path.write_text("---\n" + yaml.safe_dump(fields) + "---\n" + body)
    result = validate_notes([path], tmp_path)
    assert not result["ok"]
    assert any(field in error for error in result["files"][0]["errors"])


@pytest.mark.parametrize("value", ["2024-02-29", "20240229", None])
def test_schema_accepts_valid_dates_and_finite_duration(tmp_path, value):
    from datetime import date
    path = note(tmp_path)
    _, front, body = path.read_text().split("---", 2)
    fields = yaml.safe_load(front)
    fields.update(created=date(2024, 2, 29), modified="2026-10-01", upload_date=value, duration=0.25, status="active")
    path.write_text("---\n" + yaml.safe_dump(fields) + "---\n" + body)
    assert validate_notes([path], tmp_path)["ok"]
