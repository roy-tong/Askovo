"""Document intake is local, provenance-preserving and optional-dependency safe."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from askovo.documents import DocumentIntakeError, ingest_document


class DocumentIntakeTests(unittest.TestCase):
    def test_text_document_writes_markdown_and_source_hash(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "research.txt"
            source.write_text("First-party interview summary\n", encoding="utf-8")
            result = ingest_document(source, root / "research.md")
            output = Path(result["markdown"])
            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(output.read_text(encoding="utf-8"), source.read_text(encoding="utf-8"))
            self.assertEqual(manifest["source_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(manifest["review_status"], "unreviewed")
            self.assertEqual(manifest["research_evidence_status"], "not_registered")
            with self.assertRaises(DocumentIntakeError):
                ingest_document(source, output)

    def test_rejects_unsupported_and_empty(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bad = root / "binary.exe"
            bad.write_bytes(b"contents")
            with self.assertRaises(DocumentIntakeError):
                ingest_document(bad, root / "out.md")
            empty = root / "empty.txt"
            empty.write_bytes(b"")
            with self.assertRaises(DocumentIntakeError):
                ingest_document(empty, root / "empty.md")

    def test_missing_docling_is_actionable_without_modifying_output(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "statement.pdf"
            source.write_bytes(b"%PDF-1.4 fake fixture")
            destination = root / "statement.md"
            with patch.dict("sys.modules", {"docling": None}):
                with self.assertRaisesRegex(DocumentIntakeError, "Docling is optional"):
                    ingest_document(source, destination)
            self.assertFalse(destination.exists())
            self.assertFalse(Path(str(destination) + ".provenance.json").exists())


if __name__ == "__main__":
    unittest.main()
