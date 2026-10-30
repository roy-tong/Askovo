"""askovo — evidence-led product research, powered by the SURE engine."""

from pathlib import Path


def _read_version() -> str:
    for candidate in (
        Path(__file__).resolve().parent.parent / "VERSION",
        Path(__file__).resolve().parent / "VERSION",
    ):
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return "dev"


__version__ = _read_version()
