from pathlib import Path


def test_public_repository_excludes_private_project_operations():
    root = Path(__file__).resolve().parents[1]
    assert (root / "docs" / "README.md").is_file()
    assert (root / "docs" / "README.de.md").is_file()
    for rel_name in (
        "docs/HANDOVER.md",
        "docs/HANDOVER.de.md",
        "docs/PROJECT_STATUS.md",
        "docs/PROJECT_STATUS.de.md",
        "docs/RELEASE_CHECKLIST.md",
        "docs/RELEASE_CHECKLIST.de.md",
        "docs/project/HANDOVER.md",
        "docs/project/HANDOVER.de.md",
        "docs/project/PROJECT_STATUS.md",
        "docs/project/PROJECT_STATUS.de.md",
        "docs/project/RELEASE_CHECKLIST.md",
        "docs/project/RELEASE_CHECKLIST.de.md",
    ):
        assert not (root / rel_name).exists()


def test_public_documentation_index_points_to_supported_files():
    root = Path(__file__).resolve().parents[1]
    english = (root / "docs" / "README.md").read_text(encoding="utf-8")
    german = (root / "docs" / "README.de.md").read_text(encoding="utf-8")
    for marker in (
        "../README.md",
        "../README.de.md",
        "../RELEASE_NOTES.md",
        "../RELEASE_NOTES.de.md",
        "../SECURITY.md",
        "../CONTRIBUTING.md",
    ):
        assert marker in english
        assert marker in german
