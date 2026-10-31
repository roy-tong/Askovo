"""Local document intake for Askovo research.

This adapter only converts user-supplied, local documents to auditable Markdown.
It does not invent evidence, infer claims, or bypass study access rules. The
optional Docling dependency is loaded only for non-text formats.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DOCUMENT_FORMATS = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm",
                    ".epub", ".eml", ".msg", ".png", ".jpg", ".jpeg", ".tiff"}
TEXT_FORMATS = {".md", ".markdown", ".txt", ".text"}


class DocumentIntakeError(ValueError):
    """Bad source, unavailable optional parser, or unsafe output."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".askovo-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def ingest_document(source: str | Path, output: str | Path, *, overwrite: bool = False) -> dict:
    """Extract Markdown and a provenance sidecar; never registers a research claim.

    Both output files are checked before conversion. A user must explicitly
    import the Markdown into a study and assess its access/claim eligibility.
    """
    path = Path(source).expanduser().resolve()
    dest = Path(output).expanduser().resolve()
    sidecar = dest.with_name(dest.name + ".provenance.json")
    if not path.is_file():
        raise DocumentIntakeError("input must be a local readable file")
    if path.suffix.lower() not in DOCUMENT_FORMATS | TEXT_FORMATS:
        raise DocumentIntakeError("unsupported document extension: " + path.suffix)
    if dest.suffix.lower() not in (".md", ".markdown"):
        raise DocumentIntakeError("output must be a Markdown file (.md)")
    if path in (dest, sidecar):
        raise DocumentIntakeError("input and output paths must differ")
    if not overwrite and (dest.exists() or sidecar.exists()):
        raise DocumentIntakeError("output already exists; use --force to replace")
    if dest.is_dir() or sidecar.is_dir():
        raise DocumentIntakeError("output path is a directory")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DocumentIntakeError(str(exc)) from exc
    if not raw:
        raise DocumentIntakeError("source file is empty")

    if path.suffix.lower() in TEXT_FORMATS:
        try:
            markdown = raw.decode("utf-8-sig")
        except UnicodeError as exc:
            raise DocumentIntakeError("text source must be UTF-8") from exc
        engine = "utf-8"
    else:
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise DocumentIntakeError(
                "Docling is optional and not installed. On Python >=3.10: "
                "pip install docling; conversion of PDF/Office/image formats requires it."
            ) from exc
        # Local path only; the adapter does not fetch remote URLs.
        try:
            markdown = DocumentConverter().convert(str(path)).document.export_to_markdown()
        except Exception as exc:
            raise DocumentIntakeError("Docling conversion failed: " + str(exc)) from exc
        engine = "docling"
    if not isinstance(markdown, str) or not markdown.strip():
        raise DocumentIntakeError("extraction returned no text; review input manually")
    content = markdown.encode("utf-8")
    manifest = {
        "schema_version": "1.0",
        "kind": "askovo.document-intake",
        "source_filename": path.name,
        "source_sha256": _digest(raw),
        "source_bytes": len(raw),
        "extraction_engine": engine,
        "markdown_sha256": _digest(content),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "review_status": "unreviewed",
        "research_evidence_status": "not_registered",
        "note": ("Extraction is not proof of source truth, data rights, "
                 "population representativeness, or claim eligibility."),
    }
    encoded = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    # Convert before writing; no assertion of a two-file atomic transaction.
    _atomic_write(dest, content)
    _atomic_write(sidecar, encoded)
    return {"markdown": str(dest), "manifest": str(sidecar), **manifest}
