# Resultados del benchmark

- Fecha: 2026-09-21 04:41
- Repeticiones por medición (mediana): 3
- Tesseract: 5.5.0 | PyMuPDF: 1.24.2 | CPUs visibles: 10
- CER = error de caracteres, WER = error de palabras (menor es mejor). Tiempos en segundos (mediana).

## 1. Extracción de texto de PDF - PDF digital (3 páginas)

| Método | Tiempo (s) | Caracteres | CER % | WER % | Conf. OCR |
|---|---:|---:|---:|---:|---:|
| pdfplumber | 0.015 | 1198 | 0.0 | 0.0 | - |
| **PyMuPDF** | 0.001 | 1198 | 0.0 | 0.0 | - |
| pdftotext (poppler) | 0.007 | 1198 | 0.0 | 0.0 | - |

## 1. Extracción de texto de PDF - PDF digital grande (60 páginas)

| Método | Tiempo (s) | Caracteres | CER % | WER % | Conf. OCR |
|---|---:|---:|---:|---:|---:|
| pdfplumber | 0.319 | 23960 | - | 0.0 | - |
| PyMuPDF | 0.016 | 23960 | - | 0.0 | - |
| **pdftotext (poppler)** | 0.009 | 23960 | - | 0.0 | - |

## 1. Extracción de texto de PDF - PDF escaneado (sin capa de texto)

| Método | Tiempo (s) | Caracteres | CER % | WER % | Conf. OCR |
|---|---:|---:|---:|---:|---:|
| pdfplumber | 0.001 | 0 | 100.0 | 100.0 | - |
| PyMuPDF | 0.0 | 0 | 100.0 | 100.0 | - |
| pdftotext (poppler) | 0.006 | 0 | 100.0 | 100.0 | - |

## 2. OCR de imágenes - Imagen limpia (PNG 150 dpi)

| Método | Tiempo (s) | Caracteres | CER % | WER % | Conf. OCR |
|---|---:|---:|---:|---:|---:|
| Tesseract eng / sin preproc. | 0.194 | 418 | 1.91 | 11.94 | 89.1 |
| Tesseract spa+eng / sin preproc. | 0.234 | 418 | 0.0 | 0.0 | 96.1 |
| **Tesseract spa+eng / gris+contraste** | 0.21 | 418 | 0.0 | 0.0 | 96.1 |
| Tesseract spa+eng / gris+contraste+x2 | 0.329 | 418 | 0.0 | 0.0 | 95.9 |
| Tesseract spa+eng / binarizado (Otsu) | 0.43 | 418 | 0.0 | 0.0 | 96.0 |

## 2. OCR de imágenes - Imagen degradada (JPG, promedio de 3 variantes)

| Método | Tiempo (s) | Caracteres | CER % | WER % | Conf. OCR |
|---|---:|---:|---:|---:|---:|
| Tesseract eng / sin preproc. | 0.141 | 226 | 51.51 | 70.15 | 58.83 |
| Tesseract spa+eng / sin preproc. | 0.218 | 229 | 48.25 | 56.72 | 75.23 |
| Tesseract spa+eng / gris+contraste | 0.177 | 230 | 48.25 | 57.21 | 75.5 |
| **Tesseract spa+eng / gris+contraste+x2** | 0.416 | 324 | 26.0 | 35.33 | 82.93 |
| Tesseract spa+eng / binarizado (Otsu) | 0.289 | 228 | 52.47 | 69.65 | 65.63 |

## 3. OCR de PDF escaneado (3 páginas) - PDF escaneado

| Método | Tiempo (s) | Caracteres | CER % | WER % | Conf. OCR |
|---|---:|---:|---:|---:|---:|
| **Tesseract spa+eng / render a 100 dpi** | 0.74 | 1198 | 0.08 | 0.56 | 95.3 |
| Tesseract spa+eng / render a 150 dpi | 0.892 | 1198 | 0.08 | 0.56 | 95.7 |
| Tesseract spa+eng / render a 200 dpi | 1.073 | 1198 | 0.08 | 0.56 | 95.5 |
| Tesseract spa+eng / render a 300 dpi | 1.81 | 1199 | 0.17 | 1.13 | 94.7 |

En negrita: menor error (a igualdad, el más rápido). CER no se calcula en textos de más de 6000 caracteres.