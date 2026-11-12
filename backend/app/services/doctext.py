"""Text extraction for uploaded business documents (.pdf .docx .xlsx .txt .md .csv)."""

from __future__ import annotations

from pathlib import Path


def extract_file_text(path: str, *, max_pdf_pages: int | None = None) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix == "pdf":
        from pypdf import PdfReader

        pages = PdfReader(path).pages
        if max_pdf_pages is not None:
            pages = pages[:max_pdf_pages]
        return "\n".join(page.extract_text() or "" for page in pages)
    if suffix == "docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("python-docx is required to read DOCX uploads") from exc
        doc = Document(path)
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        return "\n".join(parts)
    if suffix == "xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise RuntimeError("openpyxl is required to read XLSX uploads") from exc
        workbook = load_workbook(path, read_only=True, data_only=True)
        parts: list[str] = []
        for sheet in workbook.worksheets:
            parts.append(f"[Sheet: {sheet.title}]")
            for row in sheet.iter_rows(values_only=True):
                values = [str(v) if v is not None else "" for v in row]
                if any(values):
                    parts.append(" | ".join(values))
        workbook.close()
        return "\n".join(parts)
    if suffix in ("txt", "md", "csv"):
        return Path(path).read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"unsupported document type: .{suffix or '<none>'}")
