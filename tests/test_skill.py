from pathlib import Path


SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


def test_existing_notes_are_preserved_and_only_additively_edited():
    content = SKILL.read_text()

    assert "Existing notes are the user's content." in content
    assert "Never delete, rewrite, reorder,\nor reformat existing text" in content
    assert "record its current\ncontent by reading it" in content
    assert "confirm that the original text is still present\nverbatim" in content
    assert "if it is not, restore it" in content
    assert "Edits to existing notes are additive only." in content
    assert "List every existing note touched and exactly what was appended." in content
    assert "improve an existing note" not in content.lower()
