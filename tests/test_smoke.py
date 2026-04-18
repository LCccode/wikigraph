"""Minimal smoke tests — ensure the package imports and CLI is wired."""

import subprocess
import sys


def test_package_imports():
    import lcwiki

    assert lcwiki.__version__


def test_core_modules_import():
    from lcwiki import compile, detect, convert, structure, graph_cmd, query  # noqa: F401


def test_cli_version():
    result = subprocess.run(
        [sys.executable, "-m", "lcwiki", "version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "lcwiki" in result.stdout.lower()
