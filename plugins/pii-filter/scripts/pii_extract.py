"""Text extraction for office/PDF documents, so Presidio can check them like any text file.

extract(path) -> Extracted(blocks, notes, unreadable_pages)
  blocks: list of ("text", str) or ("table", [[cell, ...], ...]) in document order
  notes:  short remarks for the reader (e.g. pages without a text layer)

Libraries (in the plugin venv): pypdf, python-docx, openpyxl. pptx/odt via zipfile (stdlib).
Runs locally; nothing is sent anywhere.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

DOC_EXTENSIONS = {".pdf", ".docx", ".docm", ".pptx", ".xlsx", ".xlsm", ".odt", ".ods", ".odp"}


@dataclass
class Extracted:
    blocks: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    pages: int = 0
    unreadable_pages: list = field(default_factory=list)


def _pdf(path: Path, max_lines: int | None) -> Extracted:
    from pypdf import PdfReader

    out = Extracted()
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001
            raise ValueError("pdf is beveiligd met een wachtwoord")
    out.pages = len(reader.pages)
    lines = 0
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        has_images = False
        try:
            has_images = bool(page.images)
        except Exception:  # noqa: BLE001
            pass
        if len(text) < 20 and has_images:
            out.unreadable_pages.append(i)
        out.blocks.append(("text", f"=== pagina {i} ===\n{text}\n"))
        lines += text.count("\n") + 2
        if max_lines and lines >= max_lines:
            out.notes.append(f"afgekapt na pagina {i} van {out.pages}")
            break
    if out.unreadable_pages:
        out.notes.append("pagina's zonder tekstlaag (scan/afbeelding), niet gecontroleerd en niet getoond: "
                         + ", ".join(map(str, out.unreadable_pages)))
    return out


def _docx(path: Path, max_lines: int | None) -> Extracted:
    import docx  # python-docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    out = Extracted()
    d = docx.Document(str(path))

    def walk(parent_el, parent):
        for child in parent_el.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                t = Paragraph(child, parent).text
                if t.strip():
                    out.blocks.append(("text", t + "\n"))
            elif tag == "tbl":
                tbl = Table(child, parent)
                rows = []
                for r in tbl.rows:
                    cells, seen = [], set()
                    for c in r.cells:  # merged cells repeat; keep each once
                        if id(c._tc) in seen:
                            continue
                        seen.add(id(c._tc))
                        cells.append(c.text.replace("\n", " ").strip())
                    rows.append(cells)
                if rows:
                    out.blocks.append(("table", rows))

    for section in d.sections:
        for part, label in ((section.header, "koptekst"), (section.footer, "voettekst")):
            try:
                t = "\n".join(p.text for p in part.paragraphs if p.text.strip())
            except Exception:  # noqa: BLE001
                t = ""
            if t:
                out.blocks.append(("text", f"[{label}] {t}\n"))
    walk(d.element.body, d._body)
    # comments / footnotes are not extracted by python-docx: check the raw XML for them
    with zipfile.ZipFile(path) as z:
        for name in ("word/comments.xml", "word/footnotes.xml", "word/endnotes.xml"):
            if name in z.namelist():
                t = _xml_text(z.read(name))
                if t.strip():
                    out.blocks.append(("text", f"[{name.split('/')[-1][:-4]}]\n{t}\n"))
    return out


def _xml_text(raw: bytes) -> str:
    """All text nodes of an OOXML/ODF part, one paragraph per line."""
    root = ET.fromstring(raw)
    paras = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] in ("p", "h"):  # w:p, a:p, text:p, text:h
            t = "".join(el.itertext())
            if t.strip():
                paras.append(t)
    return "\n".join(paras)


def _pptx(path: Path, max_lines: int | None) -> Extracted:
    out = Extracted()
    with zipfile.ZipFile(path) as z:
        slides = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                        key=lambda n: int(re.search(r"\d+", n.rsplit("/", 1)[-1]).group()))
        for n in slides:
            num = re.search(r"\d+", n.rsplit("/", 1)[-1]).group()
            out.blocks.append(("text", f"=== dia {num} ===\n{_xml_text(z.read(n))}\n"))
            notes = f"ppt/notesSlides/notesSlide{num}.xml"
            if notes in z.namelist():
                t = _xml_text(z.read(notes))
                if t.strip():
                    out.blocks.append(("text", f"[notities dia {num}]\n{t}\n"))
        out.pages = len(slides)
    return out


def _xlsx(path: Path, max_lines: int | None) -> Extracted:
    import openpyxl

    out = Extracted()
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    for ws in wb.worksheets:
        rows = []
        for r in ws.iter_rows(values_only=True, max_row=max_lines):
            cells = ["" if v is None else str(v) for v in r]
            while cells and cells[-1] == "":
                cells.pop()
            rows.append(cells)
        while rows and not any(rows[-1]):
            rows.pop()
        out.blocks.append(("text", f"=== blad: {ws.title} ===\n"))
        if rows:
            out.blocks.append(("table", rows))
    wb.close()
    return out


def _odf(path: Path, max_lines: int | None) -> Extracted:
    out = Extracted()
    with zipfile.ZipFile(path) as z:
        out.blocks.append(("text", _xml_text(z.read("content.xml")) + "\n"))
    return out


def extract(path: Path, max_lines: int | None = None) -> Extracted:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _pdf(path, max_lines)
    if ext in (".docx", ".docm"):
        return _docx(path, max_lines)
    if ext == ".pptx":
        return _pptx(path, max_lines)
    if ext in (".xlsx", ".xlsm"):
        return _xlsx(path, max_lines)
    if ext in (".odt", ".ods", ".odp"):
        return _odf(path, max_lines)
    raise ValueError(f"geen extractor voor {ext}")
