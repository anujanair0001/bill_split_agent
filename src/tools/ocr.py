"""OCR helpers for receipt images and PDFs."""

from pathlib import Path
import shutil
import subprocess


class OcrError(RuntimeError):
    """Raised when OCR cannot be completed in the current environment."""


def extract_receipt_text(path: str | Path) -> str:
    receipt_path = Path(path)
    if not receipt_path.exists():
        raise OcrError(f"Receipt file not found: {receipt_path}")

    suffix = receipt_path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_text(receipt_path)
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        return _extract_image_text(receipt_path)
    raise OcrError("Unsupported receipt file type. Use an image or PDF.")


def _extract_image_text(path: Path) -> str:
    direct_text = _extract_image_text_with_tesseract_cli(path)
    if direct_text:
        return direct_text

    try:
        from PIL import Image
        import pytesseract
    except ImportError as exc:
        raise OcrError(
            "OCR dependencies are not installed. Run `pip install -r requirements.txt`, "
            "or paste the receipt text manually."
        ) from exc

    _configure_tesseract(pytesseract)

    try:
        text = pytesseract.image_to_string(Image.open(path))
    except Exception as exc:
        raise OcrError(
            "OCR failed. Check that Tesseract OCR is installed and available on PATH, "
            "or paste the receipt text manually."
        ) from exc

    return _require_text(text)


def _extract_image_text_with_tesseract_cli(path: Path) -> str:
    tesseract = _find_tesseract_exe()
    if not tesseract:
        return ""

    candidates = []
    commands = [
        [tesseract, str(path), "stdout"],
        [tesseract, str(path), "stdout", "--psm", "4"],
        [tesseract, str(path), "stdout", "--psm", "6"],
    ]

    for command in commands:
        text = _run_tesseract(command)
        if text:
            candidates.append(text)

    if candidates:
        return max(candidates, key=_score_ocr_text)

    return ""


def _run_tesseract(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return ""

    return (completed.stdout or "").strip()


def _score_ocr_text(text: str) -> tuple[int, int, int]:
    try:
        from src.tools.bill_tools import parse_bill_text

        bill = parse_bill_text(text)
        validation = bill.get("validation", {})
        subtotal_difference = validation.get("subtotal_difference")
        total_difference = validation.get("total_difference")
        difference_score = 0
        if subtotal_difference is not None:
            difference_score -= int(abs(subtotal_difference) * 100)
        if total_difference is not None:
            difference_score -= int(abs(total_difference) * 100)
        return (
            1 if bill.get("receipt_total") is not None else 0,
            difference_score,
            len(bill.get("items", [])),
        )
    except Exception:
        money_lines = sum(1 for line in text.splitlines() if any(char.isdigit() for char in line))
        return (0, 0, money_lines)


def _extract_pdf_text(path: Path) -> str:
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError as exc:
        raise OcrError(
            "PDF OCR dependencies are not installed. Run `pip install -r requirements.txt`, "
            "or paste the receipt text manually."
        ) from exc

    _configure_tesseract(pytesseract)

    try:
        pages = convert_from_path(path)
        text = "\n".join(pytesseract.image_to_string(page) for page in pages)
    except Exception as exc:
        raise OcrError(
            "PDF OCR failed. Check that Poppler and Tesseract are installed, "
            "or paste the receipt text manually."
        ) from exc

    return _require_text(text)


def _require_text(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        raise OcrError("OCR did not find readable text. Try a clearer image or paste the receipt text manually.")
    return cleaned


def _configure_tesseract(pytesseract_module) -> None:
    tesseract = _find_tesseract_exe()
    if tesseract:
        pytesseract_module.pytesseract.tesseract_cmd = tesseract


def _find_tesseract_exe() -> str:
    from_path = shutil.which("tesseract")
    if from_path:
        return from_path

    common_paths = [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]
    for path in common_paths:
        if path.exists():
            return str(path)
    return ""
