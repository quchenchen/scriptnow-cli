"""Packaging for scriptnow-cli."""

from setuptools import find_packages, setup

setup(
    name="scriptnow-cli",
    version="0.3.0",
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
