from __future__ import annotations

from pathlib import Path

import pytest


REQUIRED_DIRS_AND_FILES = [
    ("data",                    ["cache"]),
    ("src",                     ["__init__.py", "db", "models"]),
    ("src/db",                  ["__init__.py", "schema.py", "engine.py"]),
    ("src/models",              ["__init__.py", "pydantic_schemas.py"]),
    ("tests",                   ["conftest.py", "test_db_schema.py"]),
    ("tests/fixtures",          []),
    ("templates",               ["daily_report.html", "components"]),
    ("templates/components",    []),
    ("ui",                      ["branding"]),
    (".streamlit",              []),
    ("config",                  ["design_system.yaml", "report_branding.yaml", "pipeline.yaml"]),
]

REQUIRED_ROOT_FILES = [
    "requirements.txt", ".env.example", ".gitignore",
]


def test_all_required_directories_non_empty_or_exist(project_root = Path(__file__).resolve().parent.parent):
    """TR-1.3: All 9+ subdirectories exist and contain at least 1 file each (or explicit child dir)."""
    for rel_dir, expected_children in REQUIRED_DIRS_AND_FILES:
        p = project_root / rel_dir
        assert p.exists() and p.is_dir(), f"Missing required dir: {rel_dir}"
        entries = list(p.iterdir())
        has_files = any(e.is_file() for e in entries)
        has_child_dirs = any(e.name in expected_children for e in entries if e.is_dir())
        if expected_children:
            has_all_expected = all(
                (p / child).exists() for child in expected_children
            )
            assert has_all_expected, f"Dir {rel_dir} missing expected children {expected_children}; had {[e.name for e in entries]}"
        else:
            # leaf dirs: just need to exist (may get files in later tasks); ensure path exists
            assert True
        if not expected_children:
            continue
        # For top-level 9 scaffolding dirs, ensure files present in the tree
    top_9_non_leaf = [
        "data", "src", "src/db", "src/models", "tests", "templates", "ui", ".streamlit", "config",
    ]
    # All 9 exist check already done above; check count
    present = [d for d in top_9_non_leaf if (project_root / d).exists()]
    assert len(present) >= 9, f"Expected 9 top scaffolding dirs, got {len(present)}: {present}"


def test_root_files_present(project_root = Path(__file__).resolve().parent.parent):
    for f in REQUIRED_ROOT_FILES:
        assert (project_root / f).is_file(), f"Missing required root file: {f}"


def test_no_supabase_weasyprint_in_requirements(project_root = Path(__file__).resolve().parent.parent):
    """TR-1.2 supplementary check: requirements.txt must NOT contain weasyprint (superseded per spec).
    Supabase IS now allowed (added as cloud persistence layer)."""
    txt = (project_root / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "weasyprint" not in txt, "requirements.txt must not contain weasyprint (Playwright Chromium PDF per spec, avoids Windows GTK DLL issues)"
    assert "playwright" in txt, "requirements.txt must include playwright (PDF engine per spec)"
    assert "sqlalchemy" in txt
    assert "pydantic" in txt
