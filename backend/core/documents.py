"""Client documents uploaded as files (PDF, TXT, Markdown).

Text is extracted locally (pypdf), so the file itself never goes to the model. The extracted text
goes through the same safety screen as pasted text: PDFs can hide white or tiny text, and that
text comes out in extraction, where the injection screen can see and flag it.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from . import guardrails, store
from .auth import current_user
from .config import MAX_ATTACHMENT_BYTES, MAX_ATTACHMENT_CHARS, MAX_ATTACHMENT_PAGES

ALLOWED = {".pdf": "pdf", ".txt": "text", ".md": "text", ".eml": "text"}


class DocumentError(ValueError):
    pass


TINY_PT = 3.0  # text drawn smaller than this is invisible to a human reader


def _hidden_segments(reader: PdfReader) -> list[str]:
    """Text a person can't see: drawn at a tiny effective font size (a common prompt-injection trick)."""
    hidden: list[str] = []

    def visitor(text, cm, tm, font_dict, font_size):  # noqa: ANN001 - pypdf callback signature
        if not text or not text.strip():
            return
        scale = abs(tm[3] or tm[0] or 1) * abs(cm[3] or cm[0] or 1)
        if font_size and font_size * scale < TINY_PT:
            hidden.append(text.strip())

    for page in reader.pages:
        try:
            page.extract_text(visitor_text=visitor)
        except Exception:  # noqa: BLE001 - detection is best-effort; extraction errors are handled below
            continue
    return [h for h in hidden if len(h) > 3]


def extract(name: str, data: bytes) -> tuple[str, str, int, list[str]]:
    """Return (kind, text, pages, hidden_segments) for an uploaded file, or raise DocumentError with a user-facing reason."""
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    kind = ALLOWED.get(ext)
    if not kind:
        raise DocumentError("Upload a PDF, TXT or Markdown file. (Word files: save as PDF first.)")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise DocumentError(f"File is {len(data) / 1e6:.1f} MB; the limit is {MAX_ATTACHMENT_BYTES / 1e6:.0f} MB.")
    if kind == "text":
        return kind, data.decode("utf-8", errors="replace"), 1, []
    if not data.startswith(b"%PDF"):
        raise DocumentError("That file does not look like a PDF.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentError("The PDF is password-protected. Remove the password and upload it again.")
        if len(reader.pages) > MAX_ATTACHMENT_PAGES:
            raise DocumentError(f"The PDF has {len(reader.pages)} pages; the limit is {MAX_ATTACHMENT_PAGES}.")
        pages = [p.extract_text() or "" for p in reader.pages]
        hidden = _hidden_segments(reader)
    except DocumentError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise DocumentError(f"Could not read the PDF ({type(exc).__name__}).") from exc
    text = "\n\n".join(t.strip() for t in pages if t.strip())
    if len(text.strip()) < 20:
        raise DocumentError("No text found in the PDF. It may be a scanned image; OCR is not supported yet.")
    return kind, text, len(pages), hidden


def extract_text(name: str, data: bytes) -> tuple[str, str, int]:
    kind, text, pages, _ = extract(name, data)
    return kind, text, pages


def ingest(name: str, data: bytes) -> dict:
    """Extract, screen, cap and store a document. Returns the stored record (without the full text)."""
    kind, raw, pages, hidden = extract(name, data)
    findings: list[guardrails.Finding] = []
    for seg in hidden:  # remove invisible text before anything else reads the document
        if seg in raw:
            raw = raw.replace(seg, " ")
            sev = "high" if any(pat.search(seg) for _, _, pat in guardrails.INJECTION_PATTERNS) else "warning"
            findings.append(guardrails.Finding(
                "hidden_pdf_text", sev,
                "Removed invisible tiny text from the PDF" + (" containing instructions aimed at the AI." if sev == "high" else "."),
                seg[:220]))
    raw = re.sub(r"[ \t]+\n", "\n", raw)
    screened = guardrails.screen_untrusted(raw)
    screened.findings = findings + screened.findings
    text = screened.clean_text
    truncated = len(text) > MAX_ATTACHMENT_CHARS
    if truncated:
        text = text[:MAX_ATTACHMENT_CHARS]
    att = {
        "id": uuid.uuid4().hex[:10],
        "name": name[:120],
        "kind": kind,
        "pages": pages,
        "chars": len(text),
        "truncated": truncated,
        "text": text,
        "findings": [f.to_dict() for f in screened.findings],
    }
    store.save_attachment(att)
    for f in screened.findings:
        if f.severity == "high":
            store.add_safety_event("prompt_injection_flagged", "high", f"In uploaded file '{att['name']}': {f.message}",
                                   None, f.to_dict())
    return public(att)


def public(att: dict) -> dict:
    return {k: att[k] for k in ("id", "name", "kind", "pages", "chars", "truncated", "findings")} | {
        "preview": att["text"][:600],
        "injection_suspected": any(f["severity"] == "high" for f in att["findings"]),
    }


# ---------------------------------------------------------------------------- API

router = APIRouter(prefix="/api/files", tags=["files"], dependencies=[Depends(current_user)])


class Upload(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    data_base64: str = Field(min_length=4, max_length=int(MAX_ATTACHMENT_BYTES * 1.4))


@router.post("")
def upload(body: Upload) -> dict:
    try:
        data = base64.b64decode(body.data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "File upload was corrupted (bad base64).") from exc
    try:
        return ingest(body.filename, data)
    except DocumentError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{att_id}")
def get_file(att_id: str) -> dict:
    att = store.get_attachment(att_id)
    if not att:
        raise HTTPException(404, "No such file.")
    return public(att) | {"text": att["text"]}


# Bundled sample documents (data/sample_docs) so the upload flow can be tried with one click.
SAMPLE_DOCS = {
    "brightsmile_rfp.pdf": "US dental chain RFP (clean)",
    "maison_verlaine_rfp.pdf": "Belgian e-commerce RFP with hidden white 1-pt text (security test)",
}


@router.get("/samples/list")
def sample_list() -> list[dict]:
    from .config import ROOT

    return [{"name": n, "label": label} for n, label in SAMPLE_DOCS.items() if (ROOT / "data" / "sample_docs" / n).exists()]


@router.post("/samples/{name}")
def load_sample(name: str) -> dict:
    from .config import ROOT

    if name not in SAMPLE_DOCS:
        raise HTTPException(404, "No such sample.")
    path = ROOT / "data" / "sample_docs" / name
    if not path.exists():
        raise HTTPException(404, "Sample file missing; run scripts/make_sample_pdfs.py.")
    return ingest(name, path.read_bytes())
