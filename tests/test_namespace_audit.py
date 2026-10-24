import zipfile

from scripts.audit_namespace import audit


def test_audit_text_filename_and_office_notes(tmp_path):
    (tmp_path / "sample.txt").write_text("retired-brand")
    (tmp_path / "retired-brand.txt").write_text("new")
    with zipfile.ZipFile(tmp_path / "slides.pptx", "w") as z:
        z.writestr("ppt/notesSlides/notesSlide1.xml", "RETIRED-BRAND")
    findings = audit(tmp_path, ["sample.txt", "retired-brand.txt", "slides.pptx"], ["retired-brand"])
    assert {(f["path"], f["location"]) for f in findings} == {
        ("sample.txt", "content"), ("retired-brand.txt", "path"),
        ("slides.pptx", "ppt/notesSlides/notesSlide1.xml"),
    }


def test_audit_excludes_unselected_history(tmp_path):
    (tmp_path / "current.md").write_text("Aegis-RAG")
    (tmp_path / "history.txt").write_text("retired-brand")
    assert audit(tmp_path, ["current.md"], ["retired-brand"]) == []
