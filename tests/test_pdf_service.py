from io import BytesIO

from app.services import pdf_service as pdf_service_module
from app.services.pdf_service import PDFService


def _service_in(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    pdf_dir = tmp_path / "pdfs"
    cache_dir.mkdir()
    pdf_dir.mkdir()
    monkeypatch.setattr(pdf_service_module, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(pdf_service_module, "PDFS_DIR", pdf_dir)
    return PDFService(), pdf_dir


def test_parse_filename_recognizes_supported_exam_metadata(tmp_path, monkeypatch):
    service, _ = _service_in(tmp_path, monkeypatch)

    assert service.parse_filename("2024年12月英语六级真题(第2套).pdf") == {
        "exam_type": "CET-6",
        "year": 2024,
        "month": 12,
        "set_number": 2,
    }
    assert service.parse_filename("2024年9月英语六级真题(第2套).pdf") is None


def test_uploaded_pdf_is_parsed_and_saved(tmp_path, monkeypatch):
    service, pdf_dir = _service_in(tmp_path, monkeypatch)
    monkeypatch.setattr(service, "extract_translation_text", lambda _path: "中国文化源远流长。")

    paper = service.parse_uploaded_pdf(BytesIO(b"new pdf"), "CET-4", 2025, 6, 1)

    assert paper is not None
    assert paper.chinese_text == "中国文化源远流长。"
    assert (pdf_dir / "CET-4_2025_6_set1.pdf").read_bytes() == b"new pdf"
    assert service.get_cached_paper("CET-4", 2025, 6, 1) is not None


def test_failed_parse_does_not_replace_existing_pdf(tmp_path, monkeypatch):
    service, pdf_dir = _service_in(tmp_path, monkeypatch)
    existing_pdf = pdf_dir / "CET-4_2025_6_set1.pdf"
    existing_pdf.write_bytes(b"existing pdf")
    monkeypatch.setattr(service, "extract_translation_text", lambda _path: None)

    paper = service.parse_uploaded_pdf(BytesIO(b"invalid pdf"), "CET-4", 2025, 6, 1)

    assert paper is None
    assert existing_pdf.read_bytes() == b"existing pdf"
    assert not (pdf_dir / "CET-4_2025_6_set1.uploading.pdf").exists()
