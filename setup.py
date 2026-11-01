from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPy(build_py):
    """Bundle the askovo runtime so a normal wheel install is self-contained."""

    def run(self) -> None:
        super().run()
        root = Path(__file__).resolve().parent
        build_lib = Path(self.build_lib)
        package_dir = build_lib / "askovo"
        runtime = package_dir / "runtime"
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
        shutil.copytree(root / "skills" / "askovo", runtime, dirs_exist_ok=True, ignore=ignore)
        shutil.copy2(root / "VERSION", package_dir / "VERSION")
        shutil.copy2(root / "VERSION", runtime / "VERSION")
        sample_src = root / "examples" / "sample-study"
        sample_dst = runtime / "examples" / "sample-study"
        shutil.copytree(sample_src, sample_dst, dirs_exist_ok=True, ignore=ignore)
        for name in ("CHANGELOG.md", "llms.txt", "README.md"):
            source = root / name
            if source.is_file():
                shutil.copy2(source, package_dir / name)


setup(cmdclass={"build_py": BuildPy})
