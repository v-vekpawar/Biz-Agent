from pathlib import Path
from docx import Document
from openpyxl import Workbook
from app.services.doctext import extract_file_text


def test_docx_extracts_paragraphs_and_tables(tmp_path: Path):
    path = tmp_path / "brief.docx"
    doc = Document()
    doc.add_paragraph("Customer interviews")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Segment"
    table.cell(0, 1).text = "SMB"
    doc.save(path)
    text = extract_file_text(str(path))
    assert "Customer interviews" in text
    assert "Segment | SMB" in text


def test_xlsx_extracts_sheet_names_and_values(tmp_path: Path):
    path = tmp_path / "research.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Market sizing"
    sheet.append(["Region", "Customers"])
    sheet.append(["Delhi", 1200])
    workbook.save(path)
    text = extract_file_text(str(path))
    assert "[Sheet: Market sizing]" in text
    assert "Delhi | 1200" in text


def test_unsupported_type_is_rejected(tmp_path: Path):
    import pytest
    path = tmp_path / "x.exe"
    path.write_bytes(b"MZ")
    with pytest.raises(ValueError):
        extract_file_text(str(path))
