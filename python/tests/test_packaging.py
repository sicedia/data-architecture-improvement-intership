"""Installed (non-editable) packages must carry their Jinja templates (the Airflow image does)."""

import tomllib

from scrapagents.paths import REPO_ROOT


def test_every_template_directory_is_declared_as_package_data():
    declared = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["tool"]["setuptools"][
        "package-data"
    ]
    package_root = REPO_ROOT / "python"
    needed = {
        ".".join(path.parent.parent.relative_to(package_root).parts)
        for path in (package_root / "scrapagents").rglob("templates/*.j2")
    }
    assert needed, "expected template directories"
    missing = sorted(pkg for pkg in needed if "templates/*.j2" not in declared.get(pkg, []))
    assert missing == [], f"add to [tool.setuptools.package-data]: {missing}"
