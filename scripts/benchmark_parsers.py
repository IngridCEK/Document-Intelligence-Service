#!/usr/bin/env python3
"""
Benchmark de extracción de texto para el Document Intelligence Service.

Compara, con las mismas librerías que ya están en la imagen Docker:

  Experimento 1 - PDF digital:    pdfplumber vs PyMuPDF vs pdftotext (poppler)
  Experimento 2 - Imágenes (OCR): Tesseract con distintos idiomas y preprocesamientos
                                  (+ RapidOCR opcional con --rapidocr)
  Experimento 3 - PDF escaneado:  Tesseract con distintas resoluciones de render (DPI)

Como el corpus se GENERA con texto conocido (ground truth), además de tiempo y
cantidad de caracteres se mide la CALIDAD: CER (tasa de error de caracteres) y
WER (tasa de error de palabras). Menor es mejor.

También puedes medir tus propios documentos con --samples-dir (ver README del script).

Uso (desde la raíz del proyecto, con Docker):
  docker compose run --rm --no-deps \
      -v "$PWD/scripts:/app/scripts" -v "$PWD/benchmark_results:/app/benchmark_results" \
      worker python scripts/benchmark_parsers.py --out benchmark_results
"""
import argparse
import io
import json
import os
import random
import shutil
import statistics
import subprocess
import time
import unicodedata

import fitz  # PyMuPDF
import pdfplumber
import pytesseract
from PIL import Image, ImageChops, ImageFilter, ImageOps

# --------------------------------------------------------------------------- #
# Corpus sintético: texto en español con acentos, números y símbolos
# --------------------------------------------------------------------------- #
GROUND_TRUTH_PAGES = [
    "Informe trimestral de operaciones. La empresa procesó 12,480 documentos durante el "
    "tercer trimestre de 2026, lo que representa un aumento del 18.5% respecto al periodo "
    "anterior. La mayor parte de la información llegó en formato PDF, seguida de imágenes "
    "escaneadas y archivos de texto plano. El tiempo promedio de atención fue de 3.2 segundos "
    "por página, y el 97% de las solicitudes se completó sin intervención manual.",

    "Factura número 2026-0451. Cliente: Ingeniería y Diseño del Sureste, S.A. de C.V. "
    "Concepto: servicio de digitalización, clasificación y extracción de información. "
    "Subtotal: $10,758.62 MXN. IVA (16%): $1,721.38 MXN. Total a pagar: $12,480.00 MXN. "
    "Forma de pago: transferencia electrónica. ¿Necesitas una corrección? Escríbenos a "
    "facturación@ejemplo.mx antes del 30 de septiembre.",

    "Conclusiones y recomendaciones. Primero, conviene validar el tipo real de cada archivo "
    "antes de procesarlo. Segundo, los documentos escaneados requieren reconocimiento óptico "
    "de caracteres, mientras que los PDF digitales se resuelven leyendo su capa de texto. "
    "Tercero, la calidad de la imagen influye más que el motor: una resolución baja o un "
    "escaneo torcido generan errores en acentos, eñes y números.",
]

LANG_ES_EN = "spa+eng"


# --------------------------------------------------------------------------- #
# Métricas
# --------------------------------------------------------------------------- #
def normalize(text: str) -> str:
    """Normaliza Unicode y colapsa espacios; conserva acentos y mayúsculas."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def levenshtein(a, b) -> int:
    """Distancia de edición; sirve para cadenas (caracteres) y listas (palabras)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def score(ref_pages, hyp_pages, max_chars_for_cer=6000):
    """Devuelve (CER%, WER%). Compara por página si coinciden; si no, el texto completo."""
    ref_pages = [normalize(p) for p in ref_pages]
    hyp_pages = [normalize(p) for p in hyp_pages]
    if len(ref_pages) != len(hyp_pages):
        ref_pages, hyp_pages = [" ".join(ref_pages)], [" ".join(hyp_pages)]
    ref_len = sum(len(p) for p in ref_pages)
    cer = None
    if ref_len <= max_chars_for_cer:
        cer = 100 * sum(levenshtein(r, h) for r, h in zip(ref_pages, hyp_pages)) / max(ref_len, 1)
    ref_words = sum(len(p.split()) for p in ref_pages)
    wer = 100 * sum(levenshtein(r.split(), h.split()) for r, h in zip(ref_pages, hyp_pages)) / max(ref_words, 1)
    return cer, wer


def timed(fn, repeats):
    """Ejecuta fn() `repeats` veces. Devuelve (mediana_segundos, resultado_de_la_1a_ejecución)."""
    times, first = [], None
    for i in range(repeats):
        t0 = time.perf_counter()
        out = fn()
        times.append(time.perf_counter() - t0)
        if i == 0:
            first = out
    return statistics.median(times), first


# --------------------------------------------------------------------------- #
# Generación del corpus (solo con PyMuPDF y Pillow: no requiere fuentes del sistema)
# --------------------------------------------------------------------------- #
def make_digital_pdf(path):
    doc = fitz.open()
    for text in GROUND_TRUTH_PAGES:
        page = doc.new_page()  # A4
        rc = page.insert_textbox(fitz.Rect(50, 60, 545, 780), text, fontsize=12, fontname="helv")
        if rc < 0:
            raise RuntimeError("El texto de prueba no cabe en la página; reduce el tamaño.")
    doc.save(path)
    doc.close()


def make_large_pdf(digital_path, out_path, copies=20):
    """Repite el PDF digital para tener un documento de 60 páginas (mide velocidad real)."""
    src = fitz.open(digital_path)
    doc = fitz.open()
    for _ in range(copies):
        doc.insert_pdf(src)
    doc.save(out_path)
    doc.close()
    src.close()


def render_pdf_pages(pdf_path, dpi, max_pages=None):
    imgs = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            if max_pages and i >= max_pages:
                break
            pix = page.get_pixmap(dpi=dpi)
            imgs.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    return imgs


def make_scanned_pdf(digital_path, out_path, dpi=200):
    """PDF de solo imágenes (sin capa de texto), como uno escaneado."""
    doc = fitz.open()
    for img in render_pdf_pages(digital_path, dpi):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        page = doc.new_page()
        page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(out_path)
    doc.close()


def degrade(img, seed=42, noise_blend=0.16):
    """Simula un mal escaneo/foto: ruido, desenfoque y ligera rotación (semilla fija = reproducible)."""
    g = ImageOps.grayscale(img)
    noise = Image.frombytes("L", g.size, random.Random(seed).randbytes(g.width * g.height))
    g = ImageChops.blend(g, noise, noise_blend)
    g = g.filter(ImageFilter.GaussianBlur(1.3))
    g = g.rotate(2.0, resample=Image.BICUBIC, expand=False, fillcolor=255)
    return g.convert("RGB")


def build_corpus(outdir):
    os.makedirs(outdir, exist_ok=True)
    digital = os.path.join(outdir, "digital.pdf")
    scanned = os.path.join(outdir, "escaneado.pdf")
    clean_png = os.path.join(outdir, "limpia.png")
    bad_jpgs = [os.path.join(outdir, f"degradada_{i}.jpg") for i in (1, 2, 3)]
    large = os.path.join(outdir, "digital_grande.pdf")
    make_digital_pdf(digital)
    make_large_pdf(digital, large, copies=20)
    make_scanned_pdf(digital, scanned, dpi=200)
    render_pdf_pages(digital, 150, max_pages=1)[0].save(clean_png)
    base = render_pdf_pages(digital, 96, max_pages=1)[0]
    for i, path in enumerate(bad_jpgs):  # 3 variantes con semillas distintas (reproducibles)
        degrade(base, seed=42 + i).save(path, "JPEG", quality=30)
    return {"digital_pdf": digital, "large_pdf": large, "scanned_pdf": scanned,
            "clean_png": clean_png, "bad_jpgs": bad_jpgs}


# --------------------------------------------------------------------------- #
# Extractores de texto de PDF (capa digital)
# --------------------------------------------------------------------------- #
def ex_pdfplumber(path):
    with pdfplumber.open(path) as pdf:
        return [p.extract_text() or "" for p in pdf.pages]


def ex_pymupdf(path):
    with fitz.open(path) as doc:
        return [p.get_text() for p in doc]


def ex_pdftotext(path):
    out = subprocess.run(["pdftotext", "-enc", "UTF-8", path, "-"], capture_output=True, check=True).stdout
    pages = out.decode("utf-8", errors="replace").split("\f")
    return pages[:-1] if pages and not pages[-1].strip() else pages


PDF_EXTRACTORS = {"pdfplumber": ex_pdfplumber, "PyMuPDF": ex_pymupdf}
if shutil.which("pdftotext"):
    PDF_EXTRACTORS["pdftotext (poppler)"] = ex_pdftotext


# --------------------------------------------------------------------------- #
# OCR
# --------------------------------------------------------------------------- #
def otsu_threshold(gray):
    hist = gray.histogram()[:256]
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    w_b = sum_b = 0
    best, thr = 0.0, 128
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b, m_f = sum_b / w_b, (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best:
            best, thr = var, t
    return thr


def prep_none(img):
    return img


def prep_gray(img):
    return ImageOps.autocontrast(ImageOps.grayscale(img))


def prep_gray_x2(img):
    g = prep_gray(img)
    return g.resize((g.width * 2, g.height * 2), Image.LANCZOS)


def prep_binarize(img):
    g = prep_gray_x2(img).filter(ImageFilter.MedianFilter(3))
    thr = otsu_threshold(g)
    return g.point(lambda p: 255 if p > thr else 0)


PREPROCESSING = {
    "sin preproc.": prep_none,
    "gris+contraste": prep_gray,
    "gris+contraste+x2": prep_gray_x2,
    "binarizado (Otsu)": prep_binarize,
}


def tesseract_ocr(img, lang, psm=3):
    """Misma estrategia que el pipeline: image_to_data, palabras unidas + confianza media."""
    data = pytesseract.image_to_data(
        img, lang=lang, config=f"--psm {psm}", output_type=pytesseract.Output.DICT, timeout=120
    )
    words = [w for w in data["text"] if w.strip()]
    confs = [float(c) for c, w in zip(data["conf"], data["text"]) if w.strip() and float(c) > 0]
    return " ".join(words), (sum(confs) / len(confs) if confs else None)


_rapid_engine = None


def rapidocr_ocr(img):
    """RapidOCR (modelos PaddleOCR sobre ONNX). Solo se usa con --rapidocr."""
    global _rapid_engine
    import numpy as np
    if _rapid_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _rapid_engine = RapidOCR()
    result, _ = _rapid_engine(np.array(img.convert("RGB")))
    if not result:
        return "", None
    result = sorted(result, key=lambda r: (round(r[0][0][1] / 20), r[0][0][0]))  # orden de lectura
    return " ".join(r[1] for r in result), sum(float(r[2]) for r in result) / len(result) * 100


# --------------------------------------------------------------------------- #
# Ejecución de experimentos
# --------------------------------------------------------------------------- #
def row(experiment, document, method, seconds, hyp_pages, ref_pages, conf=None):
    cer, wer = score(ref_pages, hyp_pages) if ref_pages is not None else (None, None)
    return {
        "experimento": experiment, "documento": document, "metodo": method,
        "tiempo_s": round(seconds, 3),
        "caracteres": sum(len(p.strip()) for p in hyp_pages),
        "cer_pct": None if cer is None else round(cer, 2),
        "wer_pct": None if wer is None else round(wer, 2),
        "confianza_ocr": None if conf is None else round(conf, 1),
    }


def exp1_pdf_digital(files, repeats):
    rows = []
    cases = (
        ("PDF digital (3 páginas)", "digital_pdf", GROUND_TRUTH_PAGES),
        ("PDF digital grande (60 páginas)", "large_pdf", GROUND_TRUTH_PAGES * 20),
        ("PDF escaneado (sin capa de texto)", "scanned_pdf", GROUND_TRUTH_PAGES),
    )
    for label, key, ref in cases:
        for name, fn in PDF_EXTRACTORS.items():
            secs, pages = timed(lambda fn=fn, p=files[key]: fn(p), repeats)
            rows.append(row("1. Extracción de texto de PDF", label, name, secs, pages, ref))
    return rows


def average_rows(rs):
    out = dict(rs[0])
    for k in ("tiempo_s", "caracteres", "cer_pct", "wer_pct", "confianza_ocr"):
        vals = [r[k] for r in rs if r[k] is not None]
        out[k] = (round(sum(vals) / len(vals), 3 if k == "tiempo_s" else 2) if vals else None)
    out["caracteres"] = int(round(out["caracteres"]))
    return out


def exp2_images(files, repeats, use_rapid):
    rows = []
    ref = [GROUND_TRUTH_PAGES[0]]
    scenarios = (
        ("Imagen limpia (PNG 150 dpi)", [files["clean_png"]]),
        ("Imagen degradada (JPG, promedio de 3 variantes)", files["bad_jpgs"]),
    )
    for label, paths in scenarios:
        imgs = [Image.open(p).convert("RGB") for p in paths]
        configs = [("Tesseract eng / sin preproc.", "eng", prep_none)]
        configs += [(f"Tesseract {LANG_ES_EN} / {pname}", LANG_ES_EN, pfn) for pname, pfn in PREPROCESSING.items()]
        for name, lang, pfn in configs:
            per_image = []
            for img in imgs:
                secs, (text, conf) = timed(lambda lang=lang, pfn=pfn, img=img: tesseract_ocr(pfn(img), lang), repeats)
                per_image.append(row("2. OCR de imágenes", label, name, secs, [text], ref, conf))
            rows.append(average_rows(per_image))
        if use_rapid:
            per_image = []
            for img in imgs:
                secs, (text, conf) = timed(lambda img=img: rapidocr_ocr(img), repeats)
                per_image.append(row("2. OCR de imágenes", label, "RapidOCR (ONNX)", secs, [text], ref, conf))
            rows.append(average_rows(per_image))
    return rows


def exp3_scanned_dpi(files, repeats):
    rows = []
    for dpi in (100, 150, 200, 300):
        def run(dpi=dpi):
            texts, confs = [], []
            for img in render_pdf_pages(files["scanned_pdf"], dpi):
                t, c = tesseract_ocr(img, LANG_ES_EN)
                texts.append(t)
                if c is not None:
                    confs.append(c)
            return texts, (sum(confs) / len(confs) if confs else None)
        secs, (texts, conf) = timed(run, repeats)
        rows.append(row("3. OCR de PDF escaneado (3 páginas)", "PDF escaneado",
                        f"Tesseract {LANG_ES_EN} / render a {dpi} dpi", secs, texts, GROUND_TRUTH_PAGES, conf))
    return rows


def samples_mode(samples_dir, repeats, max_pages, use_rapid):
    """Mide documentos reales. Si existe <nombre>.gt.txt se calcula CER/WER contra él."""
    rows = []
    for fname in sorted(os.listdir(samples_dir)):
        path = os.path.join(samples_dir, fname)
        stem, ext = os.path.splitext(fname)
        ext = ext.lower()
        if ext not in (".pdf", ".png", ".jpg", ".jpeg"):
            continue
        gt_path = os.path.join(samples_dir, stem + ".gt.txt")
        ref = [open(gt_path, encoding="utf-8").read()] if os.path.exists(gt_path) else None
        exp = "Documentos reales"
        if ext == ".pdf":
            for name, fn in PDF_EXTRACTORS.items():
                secs, pages = timed(lambda fn=fn: fn(path), repeats)
                rows.append(row(exp, fname, name, secs, pages, ref))

            def run_ocr():
                texts = [tesseract_ocr(im, LANG_ES_EN)[0] for im in render_pdf_pages(path, 150, max_pages)]
                return texts
            secs, texts = timed(run_ocr, 1)
            rows.append(row(exp, fname, f"Tesseract {LANG_ES_EN} / 150 dpi (primeras {max_pages} pág.)", secs, texts, ref))
        else:
            img = Image.open(path).convert("RGB")
            for pname, pfn in PREPROCESSING.items():
                secs, (text, conf) = timed(lambda pfn=pfn: tesseract_ocr(pfn(img), LANG_ES_EN), repeats)
                rows.append(row(exp, fname, f"Tesseract {LANG_ES_EN} / {pname}", secs, [text], ref, conf))
            if use_rapid:
                secs, (text, conf) = timed(lambda: rapidocr_ocr(img), repeats)
                rows.append(row(exp, fname, "RapidOCR (ONNX)", secs, [text], ref, conf))
    return rows


# --------------------------------------------------------------------------- #
# Reporte
# --------------------------------------------------------------------------- #
def fmt(v, suffix=""):
    return "-" if v is None else f"{v}{suffix}"


def to_markdown(rows, meta):
    lines = ["# Resultados del benchmark", ""]
    lines.append(f"- Fecha: {meta['fecha']}")
    lines.append(f"- Repeticiones por medición (mediana): {meta['repeats']}")
    lines.append(f"- Tesseract: {meta['tesseract']} | PyMuPDF: {meta['pymupdf']} | CPUs visibles: {meta['cpus']}")
    lines.append("- CER = error de caracteres, WER = error de palabras (menor es mejor). Tiempos en segundos (mediana).")
    lines.append("")
    groups = {}
    for r in rows:
        groups.setdefault((r["experimento"], r["documento"]), []).append(r)
    for (exp, doc), rs in groups.items():
        lines += [f"## {exp} - {doc}", "",
                  "| Método | Tiempo (s) | Caracteres | CER % | WER % | Conf. OCR |",
                  "|---|---:|---:|---:|---:|---:|"]
        scored = [r for r in rs if r["cer_pct"] is not None or r["wer_pct"] is not None]
        def err(r):
            return r["cer_pct"] if r["cer_pct"] is not None else r["wer_pct"]
        best = min(scored, key=lambda r: (err(r), r["tiempo_s"])) if scored else None
        if best is not None and err(best) >= 100:
            best = None  # todos fallaron: no hay ganador
        for r in rs:
            name = f"**{r['metodo']}**" if r is best else r["metodo"]
            lines.append(f"| {name} | {r['tiempo_s']} | {r['caracteres']} | {fmt(r['cer_pct'])} | {fmt(r['wer_pct'])} | {fmt(r['confianza_ocr'])} |")
        lines.append("")
    lines.append("En negrita: menor error (a igualdad, el más rápido). CER no se calcula en textos de más de 6000 caracteres.")
    return "\n".join(lines)


def print_console(rows):
    cur = None
    for r in rows:
        key = (r["experimento"], r["documento"])
        if key != cur:
            cur = key
            print(f"\n=== {key[0]} | {key[1]}")
            print(f"{'Método':<46}{'t(s)':>8}{'chars':>8}{'CER%':>8}{'WER%':>8}{'conf':>8}")
        print(f"{r['metodo']:<46}{r['tiempo_s']:>8}{r['caracteres']:>8}"
              f"{fmt(r['cer_pct']):>8}{fmt(r['wer_pct']):>8}{fmt(r['confianza_ocr']):>8}")


def main():
    ap = argparse.ArgumentParser(description="Benchmark de parsers y OCR")
    ap.add_argument("--out", default="benchmark_results", help="Carpeta de salida (JSON, Markdown y corpus)")
    ap.add_argument("--repeats", type=int, default=3, help="Repeticiones por medición (se reporta la mediana)")
    ap.add_argument("--rapidocr", action="store_true", help="Incluir RapidOCR (requiere pip install rapidocr-onnxruntime)")
    ap.add_argument("--samples-dir", help="Carpeta con tus PDFs/imágenes reales (opcional: <nombre>.gt.txt = texto correcto)")
    ap.add_argument("--max-pages", type=int, default=3, help="Páginas máximas a OCRizar por PDF real")
    ap.add_argument("--skip-synthetic", action="store_true", help="Omite los experimentos 1-3 (solo mide --samples-dir)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    if args.rapidocr:
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except ImportError:
            print("RapidOCR no está instalado; se omite (pip install rapidocr-onnxruntime).")
            args.rapidocr = False

    if args.skip_synthetic and not args.samples_dir:
        ap.error("--skip-synthetic requiere --samples-dir")

    print("Calentando Tesseract...")
    tesseract_ocr(Image.new("RGB", (200, 60), "white"), LANG_ES_EN)

    rows = []
    if not args.skip_synthetic:
        print("Generando corpus sintético con texto conocido...")
        files = build_corpus(os.path.join(args.out, "corpus"))
        print("Experimento 1: extracción de texto de PDF...")
        rows += exp1_pdf_digital(files, args.repeats)
        print("Experimento 2: OCR de imágenes...")
        rows += exp2_images(files, args.repeats, args.rapidocr)
        print("Experimento 3: OCR de PDF escaneado a distintas resoluciones...")
        rows += exp3_scanned_dpi(files, args.repeats)
    if args.samples_dir:
        print("Midiendo documentos reales...")
        rows += samples_mode(args.samples_dir, args.repeats, args.max_pages, args.rapidocr)

    meta = {
        "fecha": time.strftime("%Y-%m-%d %H:%M"), "repeats": args.repeats,
        "tesseract": str(pytesseract.get_tesseract_version()), "pymupdf": fitz.VersionBind, "cpus": os.cpu_count(),
    }
    with open(os.path.join(args.out, "benchmark_results.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "resultados": rows}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(args.out, "benchmark_results.md"), "w", encoding="utf-8") as f:
        f.write(to_markdown(rows, meta))

    print_console(rows)
    print(f"\nListo. Resultados en: {args.out}/benchmark_results.md y .json")


if __name__ == "__main__":
    main()