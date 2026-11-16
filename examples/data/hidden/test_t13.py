import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(*args):
    return subprocess.run(
        [sys.executable, "-m", "unitcraft", *args],
        cwd=HERE,
        capture_output=True,
        text=True,
    )


def test_good_conversions_print_four_places():
    r = run("convert", "3", "ft", "m")
    assert (r.returncode, r.stdout) == (0, "0.9144\n")
    r = run("convert", "1", "m", "ft")
    assert (r.returncode, r.stdout) == (0, "3.2808\n")


def test_bad_unit_exits_2_with_one_line():
    for args in (("convert", "3", "ft", "xx"), ("convert", "3", "furlong", "m")):
        r = run(*args)
        assert r.returncode == 2, args
        assert r.stdout == "", args
        assert len(r.stderr.strip().splitlines()) == 1, args
