from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_installs_verified_dependency_set():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    ci_requirements = (ROOT / "requirements-ci.txt").read_text(encoding="utf-8")

    assert "pip install -r requirements-ci.txt" in workflow
    assert "mi-mo-v2.5" not in ci_requirements
    assert "deepseek-api" not in ci_requirements
