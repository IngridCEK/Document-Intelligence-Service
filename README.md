# Document Intelligence Service

Servicio asíncrono para extraer texto plano y metadatos de documentos (**PDF**, **PNG**, **JPG** y **TXT**). El usuario sube el archivo, recibe un `job_id` de inmediato y consulta el progreso y el resultado cuando quiera. Implementa el patrón **Claim-Check**: el archivo se guarda una sola vez y por la cola solo viaja su identificador.

Todo el procesamiento es local (on-device) y con tecnologías open source. Todo el sistema se levanta con un único comando de Docker Compose.

---


### Componentes

| Servicio | Contenedor | Puerto | Función |
|---|---|---|---|
| **FastAPI** | `doc_intel_api` | 8000 | Ingesta de archivos y consulta de jobs |
| **Celery Worker** | `doc_intel_worker` | – | Extracción de texto, OCR y metadatos (2 procesos) |
| **Celery Beat** | `doc_intel_beat` | – | Programa la tarea de limpieza de jobs atascados (reaper) |
| **Redis** | `doc_intel_redis` | 6379 | Broker de la cola, con persistencia AOF |
| **PostgreSQL** | `doc_intel_postgres` | 5432 | Ciclo de vida de los jobs, texto extraído y metadatos |
| **Flower** | `doc_intel_flower` | 5555 | Monitoreo de workers y tareas de Celery |
| **Streamlit** | `doc_intel_ui` | 8501 | Interfaz para subir documentos y ver resultados |

### Tecnologías de extracción

**PyMuPDF:** lectura del texto de PDFs digitales (página por página), validación del PDF (corrupto o con contraseña), metadatos y renderizado de las páginas escaneadas para OCR.
* **Tesseract OCR (pytesseract):** OCR de imágenes y de páginas de PDF sin texto digital (idiomas spa+eng).
* **python-magic:** detección del tipo real del archivo por su contenido.

---

## Requisitos previos

* [Docker Desktop](https://www.docker.com/products/docker-desktop/) (incluye Docker Engine y Docker Compose).
* Puertos libres en tu máquina: `8000`, `8501`, `5555`, `5432` y `6379`.

---

## Despliegue

1. Ubícate en la carpeta raíz del proyecto (la que contiene `docker-compose.yml`):
   ```bash
   cd <task2>
   ```

2. Construye y levanta todos los servicios:
   ```bash
   docker compose up --build
   ```
   Este comando deja la terminal mostrando los logs. Si prefieres ejecutarlo en segundo plano, agrega `-d`.

3. Cuando termine de arrancar, abre:

   * **Interfaz de usuario (Streamlit):** <http://localhost:8501>
   * **Documentación interactiva de la API (Swagger):** <http://localhost:8000/docs>
   * **Monitoreo de Celery (Flower):** <http://localhost:5555>

---

## Uso de la interfaz

La UI tiene cuatro pestañas:

1. **Subir Documento:** selecciona un archivo (PDF, PNG, JPG o TXT, máximo 15 MB) y presiona **Enviar para Procesamiento**. La API responde de inmediato con el `job_id`.
2. **Seguir Job:** pega el `job_id` para ver su estado (`QUEUED`, `PROCESSING`, `COMPLETED` o `FAILED`). Para refrescar el estado presiona la tecla `R` (Rerun de Streamlit). Si el job terminó:
   * `COMPLETED`: se muestran el texto extraído, los metadatos y las advertencias (poco texto detectado, documento duplicado).
   * `FAILED`: se muestran el código de error y el detalle.
3. **Dashboard del Sistema:** métricas leídas directamente de la base de datos (total de jobs, completados, fallidos, en cola o procesando y distribución por estado).
4. **Historial Completo:** tabla con todos los jobs, su estado y el número de reintentos.

---

## API REST

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/documents/upload` | Recibe el archivo, lo valida, lo guarda y encola el job. Responde `202 Accepted` con el `job_id`. |
| `GET` | `/api/v1/jobs/{job_id}` | Estado del job: `status`, `error_code`, `error_message`, `retry_count`, `file_hash` y marcas de tiempo. |
| `GET` | `/api/v1/jobs/{job_id}/result` | Texto extraído y metadatos si el job está `COMPLETED`; si no, su estado actual o el error. |
| `GET` | `/api/v1/jobs?limit=20` | Los jobs más recientes. |

### Validación en la ingesta

* El tipo de archivo se detecta por su **contenido real** (python-magic), no por la extensión: un ejecutable renombrado a `.pdf` se rechaza.
* Los archivos `text/*` solo se aceptan si el nombre termina en `.txt`.
* Se rechazan los archivos vacíos y los que superan **15 MB** (el conteo se hace por bloques mientras se guarda; si se excede, se borra lo escrito).
* El archivo se guarda con un nombre sanitizado `{job_id}.{ext}`; el nombre original solo se conserva en la base de datos.
* Todos los rechazos devuelven `400` con un mensaje explicativo.

---

## Extracción y metadatos

**PDF:** se revisa cada página con PyMuPDF. Si una página trae menos de 40 caracteres de texto, se renderiza a 150 DPI y se le aplica OCR solo a esa página, de modo que los PDFs mixtos (páginas digitales y escaneadas) se procesan correctamente.

**Imagen:** se verifica su integridad y se aplica OCR con Tesseract.

**TXT:** se lee probando las codificaciones `utf-8`, `latin-1` y `cp1252`.

El texto extraído se guarda en la columna `extracted_text` (`Text`) de la tabla `document_jobs`, y los metadatos en `metadata_json` (`JSON`), ambos en PostgreSQL.

| Origen | Metadatos |
|---|---|
| Todos | `parser_used`, `character_count`, `word_count`, `processing_time_seconds`, `sha256_hash`, `low_text_warning` `ocr_language` |
| PDF | `total_pages`, `scanned_pages_detected`, `average_ocr_confidence`, `pdf_title`, `pdf_author`  `pdf_repaired`|
| Imagen | `image_format`, `image_size_px`, `ocr_confidence` `pdf_repaired`|
| TXT | `encoding` |
| Duplicados | `duplicate_of_job_id`, cuando otro job completado tiene el mismo SHA-256. El documento se procesa igualmente y solo se avisa. |

---

## Manejo de fallos y resiliencia

| Mecanismo | Configuración |
|---|---|
| Confirmación tardía (`acks_late`) y `reject_on_worker_lost` | Si el worker muere a mitad de una tarea, el mensaje no se pierde y se reentrega. |
| Persistencia de Redis | AOF activado (`--appendonly yes`) con volumen propio. |
| Reentrega tras caída del worker | `visibility_timeout` de 120 s. |
| Límites de tiempo por tarea | Soft limit de 240 s y límite duro de 300 s. |
| Reintentos | Errores transitorios: hasta 3 reintentos con 10 s de espera. |
| Reaper (Celery Beat, cada 2 min) | Re-encola los jobs `QUEUED` con más de 5 min, y marca como `FAILED` los `PROCESSING` sin actividad por más de 10 min. |
| Reinicio automático | `restart: unless-stopped` en todos los servicios. |
| Idempotencia | Si llega un mensaje de un job que ya terminó, el worker lo ignora. |

Si la cola no está disponible al subir un archivo, el job igualmente queda guardado como `QUEUED` y el reaper lo re-encola.

### Códigos de error (`error_code`)

| Código | Significado | ¿Se reintenta? |
|---|---|---|
| `CorruptedFileError` | Archivo corrupto, ilegible o inexistente en disco | No |
| `EncryptedPDFError` | PDF protegido con contraseña | No |
| `UnsupportedFormatError` | Formato no soportado por el worker | No |
| `MAX_RETRIES_EXCEEDED` | Error inesperado que persistió tras los 3 reintentos | Ya agotó los reintentos |
| `WORKER_CRASH_OR_TIMEOUT` | El job se quedó en `PROCESSING` sin respuesta del worker | Lo marca el reaper |

### Cómo probar los escenarios de fallo

Desde una segunda terminal, con el stack levantado:

* **Formato falso:** sube un `.exe` renombrado a `.pdf`. La API responde `400`.
* **Archivo corrupto:** sube un `.txt` renombrado a `.pdf`. El job termina en `FAILED` con `CorruptedFileError`, sin reintentos.
* **Worker caído:**
  ```bash
  docker stop doc_intel_worker     # sube un archivo: queda en QUEUED
  docker start doc_intel_worker    # el job pasa a COMPLETED
  ```
* **Redis reiniciado:** sube varios archivos y ejecuta `docker compose restart redis`.
* **Worker muerto a mitad de una tarea:** `docker kill doc_intel_worker` mientras procesa un PDF grande. El job se recupera cuando vence el `visibility_timeout`.

También hay un script automatizado en `scripts/test_resilience.py` (requiere `pip install requests` en tu máquina).

---

## Estructura del proyecto

```
.
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── scripts/
│   ├── benchmark_parsers.py      # Comparación de parsers
│   └── test_resilience.py        # Prueba de caída y recuperación del worker
└── app/
    ├── main.py                   # FastAPI: seguimiento y resultados de jobs
    ├── config.py                 # Configuración (variables de entorno)
    ├── api/endpoints.py          # Ingesta de documentos (upload)
    ├── core/celery_app.py        # Configuración de Celery y Beat
    ├── db/                       # Conexión y modelo DocumentJob
    ├── services/parser.py        # Extracción de texto y metadatos
    ├── tasks/
    │   ├── worker.py             # Tarea de procesamiento
    │   └── cleanup.py            # Reaper de jobs atascados
    └── ui/streamlit_app.py       # Interfaz de usuario
```

---

## Detener la aplicación

```bash
docker compose down        # detiene y elimina los contenedores; conserva los datos
docker compose down -v     # además BORRA los volúmenes (base de datos, Redis y archivos subidos)
```

## Solución de problemas

* **`Conflict. The container name "/doc_intel_..." is already in use`:** quedó un contenedor de una ejecución anterior. Elimínalo con `docker rm -f <nombre>` y vuelve a levantar.
* **`column "..." does not exist` en los logs de la API:** el volumen de PostgreSQL es de una versión anterior del esquema. Ejecuta `docker compose down -v` y luego `docker compose up --build`.
* **Un servicio no responde:** revisa `docker compose ps` y `docker compose logs <servicio> --tail 50` (por ejemplo `api` o `worker`).