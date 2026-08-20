"""Packaging for scriptnow-cli."""

import re
from pathlib import Path

from setuptools import find_packages, setup

# Single source of truth: cli_anything/scriptnow/__init__.py __version__
_init = Path(__file__).parent / "cli_anything" / "scriptnow" / "__init__.py"
_match = re.search(r'__version__\s*=\s*"([^"]+)"', _init.read_text(encoding="utf-8"))
if _match is None:
    raise RuntimeError("cannot read __version__ from cli_anything/scriptnow/__init__.py")

setup(
    name="scriptnow-cli",
    version=_match.group(1),
    description="Agent-native CLI for the ScriptNow creative platform — CLI-Anything pattern",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "click>=8.0",
        "requests>=2.28",
    ],
    entry_points={
        "console_scripts": [
            "scriptnow=cli_anything.scriptnow.scriptnow_cli:main",
        ],
    },
    python_requires=">=3.10",
)
