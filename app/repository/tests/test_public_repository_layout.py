from pathlib import Path


PUBLIC_INFORMATION_PAIRS = (
    ("README.md", "README.de.md"),
    ("RELEASE_NOTES.md", "RELEASE_NOTES.de.md"),
    ("SECURITY.md", "SECURITY.de.md"),
    ("CONTRIBUTING.md", "CONTRIBUTING.de.md"),
    ("THIRD-PARTY-NOTICES.md", "THIRD-PARTY-NOTICES.de.md"),
    ("docs/README.md", "docs/README.de.md"),
    ("docker-compose/README.md", "docker-compose/README.de.md"),
)


def test_public_repository_excludes_private_project_operations():
    root = Path(__file__).resolve().parents[1]
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


def test_public_information_files_have_english_and_german_pairs():
    root = Path(__file__).resolve().parents[1]
    for english_name, german_name in PUBLIC_INFORMATION_PAIRS:
        assert (root / english_name).is_file(), english_name
        assert (root / german_name).is_file(), german_name
    assert not list(root.rglob("*.en.md"))


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
        "../SECURITY.de.md",
        "../CONTRIBUTING.md",
        "../CONTRIBUTING.de.md",
        "../THIRD-PARTY-NOTICES.md",
        "../THIRD-PARTY-NOTICES.de.md",
    ):
        assert marker in english
        assert marker in german
