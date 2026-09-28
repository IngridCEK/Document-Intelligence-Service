
import hashlib
import os
import fitz  # PyMuPDF
import pytesseract
from PIL import Image

# Idiomas del OCR. El benchmark mostró que con solo "eng" fallan los acentos y las eñes.
OCR_LANG = "spa+eng"
# Una página del PDF con menos caracteres que esto se considera escaneada y se le aplica OCR.
MIN_TEXT_CHARS_PER_PAGE = 40
OCR_RENDER_DPI = 150        # 100-200 dpi dieron la misma calidad en el benchmark; 300 solo fue más lento
OCR_TIMEOUT_SECONDS = 30


class CorruptedFileError(Exception):
    pass

class EncryptedPDFError(Exception):
    pass

class UnsupportedFormatError(Exception):
    pass

def calculate_sha256(file_path: str) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def _ocr_image(img: Image.Image):
    """OCR con Tesseract. Devuelve (texto, confianza_media_0_a_100 o None)."""
    ocr_data = pytesseract.image_to_data(
        img, lang=OCR_LANG, output_type=pytesseract.Output.DICT, timeout=OCR_TIMEOUT_SECONDS
    )
    text = " ".join(word for word in ocr_data["text"] if word.strip())
    conf_values = [float(c) for c in ocr_data["conf"] if float(c) > 0]
    avg_conf = sum(conf_values) / len(conf_values) if conf_values else None
    return text, avg_conf

def process_pdf(file_path: str):
    # PyMuPDF valida el archivo, lee el texto digital y renderiza las páginas escaneadas
    try:
        doc = fitz.open(file_path)
    except Exception as e:
        raise CorruptedFileError(f"Archivo PDF corrupto o no válido: {str(e)}")

    full_text = []
    scanned_pages_count = 0
    total_ocr_confidence = 0
    ocr_confidence_samples = 0

    try:
        if doc.is_encrypted:
            raise EncryptedPDFError("El archivo PDF está protegido con contraseña.")
        total_pages = len(doc)
        doc_metadata = doc.metadata or {}
        # True si el PDF estaba dañado y PyMuPDF tuvo que repararlo al abrirlo (el texto podría estar incompleto)
        pdf_repaired = bool(doc.is_repaired)

        for idx, page in enumerate(doc):
            page_text = page.get_text()
            # Si la página tiene poco texto, aplicar OCR solo a esa página
            if len(page_text.strip()) < MIN_TEXT_CHARS_PER_PAGE:
                scanned_pages_count += 1
                try:
                    pix = page.get_pixmap(dpi=OCR_RENDER_DPI)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    page_text, conf = _ocr_image(img)
                    if conf is not None:
                        total_ocr_confidence += conf
                        ocr_confidence_samples += 1
                except Exception as ocr_err:
                    page_text = f"[Error realizando OCR en página {idx+1}: {str(ocr_err)}]"

            full_text.append(f"--- Página {idx + 1} ---\n{page_text}")
    except EncryptedPDFError:
        raise
    except Exception as e:
        raise CorruptedFileError(f"Error extrayendo contenido del PDF: {str(e)}")
    finally:
        doc.close()

    extracted_text = "\n\n".join(full_text)
    avg_confidence = round(total_ocr_confidence / ocr_confidence_samples, 2) if ocr_confidence_samples > 0 else 100.0

    metadata = {
        "parser_used": "hybrid_pymupdf_ocr",
        "ocr_language": OCR_LANG,
        "total_pages": total_pages,
        "scanned_pages_detected": scanned_pages_count,
        "pdf_repaired": pdf_repaired,
        "pdf_title": doc_metadata.get("title", ""),
        "pdf_author": doc_metadata.get("author", ""),
        "character_count": len(extracted_text),
        "word_count": len(extracted_text.split()),
        "average_ocr_confidence": avg_confidence,
        "low_text_warning": len(extracted_text.strip()) < 50
    }

    return extracted_text, metadata

def process_image(file_path: str):
    try:
        img = Image.open(file_path)
        img.verify()  # Verificar integridad
        img = Image.open(file_path)  # Reabrir tras verify
    except Exception as e:
        raise CorruptedFileError(f"Archivo de imagen corrupto o inválido: {str(e)}")

    try:
        text, conf = _ocr_image(img)
        avg_confidence = round(conf, 2) if conf is not None else 0.0
    except Exception as e:
        raise CorruptedFileError(f"Error procesando OCR en imagen: {str(e)}")

    metadata = {
        "parser_used": "pytesseract_ocr",
        "ocr_language": OCR_LANG,
        "image_format": img.format,
        "image_size_px": f"{img.width}x{img.height}",
        "character_count": len(text),
        "word_count": len(text.split()),
        "ocr_confidence": avg_confidence,
        "low_text_warning": len(text.strip()) < 20
    }

    return text, metadata

def process_text_file(file_path: str):
    encodings = ["utf-8", "latin-1", "cp1252"]
    text = ""
    used_encoding = None

    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc) as f:
                text = f.read()
            used_encoding = enc
            break
        except (UnicodeDecodeError, Exception):
            continue

    if used_encoding is None:
        raise CorruptedFileError("No se pudo decodificar el archivo de texto plano.")

    metadata = {
        "parser_used": "plain_text_reader",
        "encoding": used_encoding,
        "character_count": len(text),
        "word_count": len(text.split()),
        "low_text_warning": len(text.strip()) == 0
    }

    return text, metadata