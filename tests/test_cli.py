import subprocess
import sys


def test_cli_exits_on_eof():
    result = subprocess.run(
        [sys.executable, "-m", "src.main"],
        input="",
        text=True,
        capture_output=True,
        timeout=3,
    )

    assert result.returncode == 0
    assert "EOF when reading a line" not in result.stdout


def test_cli_parse_outline_questions_are_not_placeholder_commands():
    result = subprocess.run(
        [sys.executable, "-m", "src.main"],
        input="/parse\n/outline\n/questions\n/quit\n",
        text=True,
        capture_output=True,
        timeout=3,
    )

    assert result.returncode == 0
    assert "正在开发中" not in result.stdout
    assert "请提供文件路径" in result.stdout
    assert "请先解析文档" in result.stdout


def test_cli_parse_missing_file_reports_clear_error(tmp_path):
    missing_file = tmp_path / "missing.pdf"

    result = subprocess.run(
        [sys.executable, "-m", "src.main"],
        input=f"/parse {missing_file}\n/quit\n",
        text=True,
        capture_output=True,
        timeout=3,
    )

    assert result.returncode == 0
    assert "正在开发中" not in result.stdout
    assert "文件不存在" in result.stdout
