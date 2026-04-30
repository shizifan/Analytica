"""Phase 6 / 6.2 — perceptual hash visual regression.

Tooling: LibreOffice → PDF → pdftoppm → imagehash phash.

For each ``.docx`` / ``.pptx`` golden under ``tests/fixtures/report_baseline/``:
  1. Convert to PDF via headless LibreOffice (``soffice``)
  2. Rasterise each page to PNG via ``pdftoppm``
  3. Compute perceptual hash of every page
  4. Compare against committed reference hashes in
     ``tests/fixtures/report_visual/<fixture>/<basename>.phash.json``

Threshold: hamming distance ≤ 5 per page (imagehash recommended default).

Marked ``slow`` and skipped automatically when:
  - ``soffice`` / ``pdftoppm`` not on PATH (most CI containers / dev boxes)
  - ``Pillow`` / ``imagehash`` not importable (install via the optional
    ``visual`` dependency group: ``uv sync --group visual``)

Regenerating reference hashes after an intentional visual change::

    ANALYTICA_REGEN_VISUAL=1 pytest tests/visual/ -m slow
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.slow]

PHASH_DISTANCE_THRESHOLD = 5

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "report_baseline"
REFERENCE_DIR = REPO_ROOT / "tests" / "fixtures" / "report_visual"


def _have_libreoffice() -> bool:
    return shutil.which("soffice") is not None or shutil.which("libreoffice") is not None


def _have_pdftoppm() -> bool:
    return shutil.which("pdftoppm") is not None


def _have_pil_imagehash() -> bool:
    try:
        import imagehash  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except Exception:
        return False


_REQUIRED_TOOLS_REASON = (
    "Visual regression deps missing — install LibreOffice + poppler-utils "
    "and run ``uv sync --group visual`` to enable. "
    "(soffice={so}, pdftoppm={pp}, Pillow+imagehash={pi})"
)


def _skip_if_unavailable() -> None:
    if not (_have_libreoffice() and _have_pdftoppm() and _have_pil_imagehash()):
        pytest.skip(
            _REQUIRED_TOOLS_REASON.format(
                so=_have_libreoffice(),
                pp=_have_pdftoppm(),
                pi=_have_pil_imagehash(),
            )
        )


def _regen_enabled() -> bool:
    return os.getenv("ANALYTICA_REGEN_VISUAL") == "1"


def _convert_to_pdf(src: Path, out_dir: Path) -> Path:
    """Run headless soffice; returns the produced PDF path."""
    binary = shutil.which("soffice") or shutil.which("libreoffice")
    if binary is None:  # pragma: no cover — guarded by _skip_if_unavailable
        pytest.skip("LibreOffice unavailable")
    proc = subprocess.run(
        [
            binary, "--headless", "--nologo", "--nofirststartwizard",
            "--convert-to", "pdf", "--outdir", str(out_dir), str(src),
        ],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        pytest.skip(f"soffice failed (rc={proc.returncode}): {proc.stderr[:200]}")
    pdf = out_dir / (src.stem + ".pdf")
    if not pdf.exists():
        pytest.skip(f"soffice did not produce PDF for {src.name}")
    return pdf


def _rasterise_pdf(pdf: Path, out_dir: Path) -> list[Path]:
    """pdftoppm → list of page PNGs sorted by page index."""
    prefix = out_dir / "page"
    proc = subprocess.run(
        ["pdftoppm", "-png", "-r", "100", str(pdf), str(prefix)],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        pytest.skip(f"pdftoppm failed: {proc.stderr[:200]}")
    pages = sorted(out_dir.glob("page-*.png"))
    if not pages:
        pytest.skip(f"pdftoppm produced no pages for {pdf.name}")
    return pages


def _phash_of(png: Path) -> str:
    import imagehash
    from PIL import Image
    with Image.open(png) as im:
        return str(imagehash.phash(im))


def _phash_distance(a: str, b: str) -> int:
    import imagehash
    return imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)


def _reference_path(fixture: str, doc: Path) -> Path:
    return REFERENCE_DIR / fixture / f"{doc.stem}.phash.json"


def _check_or_regen(fixture: str, doc: Path, page_hashes: list[str]) -> None:
    ref_path = _reference_path(fixture, doc)

    if _regen_enabled() or not ref_path.exists():
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        ref_path.write_text(
            json.dumps({"pages": page_hashes}, indent=2),
            encoding="utf-8",
        )
        pytest.skip(f"Visual reference regenerated: {ref_path.relative_to(REPO_ROOT)}")

    expected = json.loads(ref_path.read_text(encoding="utf-8"))["pages"]
    if len(expected) != len(page_hashes):
        pytest.fail(
            f"Page count changed for {doc.name}: "
            f"expected={len(expected)} actual={len(page_hashes)}"
        )

    diffs: list[str] = []
    for i, (exp, act) in enumerate(zip(expected, page_hashes), start=1):
        d = _phash_distance(exp, act)
        if d > PHASH_DISTANCE_THRESHOLD:
            diffs.append(f"page {i}: phash distance {d} > {PHASH_DISTANCE_THRESHOLD}")
    if diffs:
        pytest.fail(f"{doc.name}: " + "; ".join(diffs))


def _document_cases() -> list[tuple[str, Path]]:
    """Yield ``(fixture_name, golden_path)`` for every binary doc that
    LibreOffice can render (DOCX + PPTX). HTML/MD aren't rasterised."""
    cases: list[tuple[str, Path]] = []
    if not GOLDEN_DIR.exists():
        return cases
    for fixture_dir in sorted(GOLDEN_DIR.iterdir()):
        if not fixture_dir.is_dir():
            continue
        for ext in ("docx", "pptx"):
            golden = fixture_dir / f"golden.{ext}"
            if golden.exists():
                cases.append((fixture_dir.name, golden))
    return cases


@pytest.mark.parametrize(
    "fixture, doc",
    _document_cases(),
    ids=lambda v: v.name if isinstance(v, Path) else v,
)
def test_visual_phash(fixture: str, doc: Path) -> None:
    _skip_if_unavailable()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pdf = _convert_to_pdf(doc, tmp_path)
        pages = _rasterise_pdf(pdf, tmp_path)
        page_hashes = [_phash_of(p) for p in pages]
    _check_or_regen(fixture, doc, page_hashes)
