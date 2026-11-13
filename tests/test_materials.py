"""Reading text out of uploaded PDF and Word files."""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def make_pdf(lines):
    """A minimal one-page text PDF, written by hand so the test needs no PDF writer."""
    content = "BT /F1 12 Tf 72 720 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(body_xml, prolog=""):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", f'<?xml version="1.0"?>{prolog}<w:document {W}><w:body>{body_xml}</w:body></w:document>')
    return buffer.getvalue()


def extract(data, filename):
    return client.post(f"/api/materials/extract?filename={filename}", content=data)


def test_pdf_text_is_extracted():
    pytest.importorskip("pypdf")
    response = extract(make_pdf(["Maria Example", "Marketing manager, five years"]), "cv.pdf")
    assert response.status_code == 200
    text = response.json()["text"]
    assert "Maria Example" in text and "Marketing manager, five years" in text
    assert response.json()["characters"] == len(text)


def test_pdf_without_text_and_broken_pdf_are_explained():
    pytest.importorskip("pypdf")
    scan = extract(make_pdf([]), "scan.pdf")
    assert scan.status_code == 422 and "no selectable text" in scan.json()["detail"]
    broken = extract(b"%PDF-1.4 this is not really a pdf", "broken.pdf")
    assert broken.status_code == 422 and "could not be read" in broken.json()["detail"]


def test_docx_paragraphs_tables_tabs_and_breaks():
    body = (
        "<w:p><w:r><w:t>職務経歴書</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Skills:</w:t><w:tab/><w:t>SQL</w:t><w:br/><w:t>Python</w:t></w:r></w:p>"
        "<w:p></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>2020</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>ABC Company</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    )
    response = extract(make_docx(body), "cv.docx")
    assert response.json()["text"] == "職務経歴書\nSkills:\tSQL\nPython\n2020\nABC Company"


def test_unsupported_and_invalid_files_are_explained():
    old_doc = extract(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100, "cv.doc")
    assert old_doc.status_code == 422 and "Save As" in old_doc.json()["detail"]
    assert "valid .docx" in extract(b"PK not a zip", "cv.docx").json()["detail"]
    assert "No text" in extract(make_docx(""), "empty.docx").json()["detail"]
    assert "not supported" in extract(b"hello", "notes.xyz").json()["detail"]
    assert extract(b"", "cv.pdf").status_code == 400
    entity = make_docx("", prolog='<!DOCTYPE x [<!ENTITY a "b">]>')
    assert "unexpected structure" in extract(entity, "odd.docx").json()["detail"]
