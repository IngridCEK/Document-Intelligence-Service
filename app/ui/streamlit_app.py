import os
import requests
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine

st.set_page_config(page_title="Document Intelligence Service", page_icon="📄", layout="wide")

# Configuración de URLs para comunicación en Docker Compose
API_URL = os.getenv("API_URL", "http://api:8000")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://doc_user:doc_password@postgres:5432/doc_db")

st.markdown("""
<style>
    .stApp { background-color: #f8f9fa !important; color: #1a202c !important; }
    h1, h2, h3, h4, h5, h6, p, label, span, div { color: #1a202c !important; }
    
    /* Corregir visibilidad de avisos y contenedores */
    div[data-testid="stFileUploader"] {
        border: 2px dashed #4a5568 !important;
        border-radius: 10px !important;
        padding: 15px !important;
        background-color: #ffffff !important;
    }
    
    /* Historial y tablas legibles */
    .stDataFrame { background-color: #ffffff !important; }
    
    /* Mensajes de error claros */
    .stAlert { border-radius: 8px !important; }
    
    /* Corregir visor JSON */
    div[data-testid="stJson"], div[data-testid="stJson"] * {
        background-color: #ffffff !important;
        color: #1a202c !important;
    }
</style>
""", unsafe_allow_html=True)

st.title(" Document Intelligence Service")
st.caption("Procesamiento asíncrono de documentos con arquitectura Claim-Check")

tab1, tab2, tab3, tab4 = st.tabs([" Subir Documento", " Seguir Job", " Dashboard del Sistema", " Historial Completo"])

# ==========================================
# TAB 1: SUBIR DOCUMENTO
# ==========================================
with tab1:
    st.subheader("Cargar nuevo archivo")
    st.info("Formatos aceptados: PDF, PNG, JPG, TXT. Tamaño máximo: 15 MB.")
    uploaded_file = st.file_uploader("Selecciona un documento", type=["pdf", "png", "jpg", "jpeg", "txt"])
    
    if uploaded_file is not None:
        if st.button("Enviar para Procesamiento", type="primary"):
            files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
            try:
                res = requests.post(f"{API_URL}/api/v1/documents/upload", files=files)
                if res.status_code in [200, 202]:
                    data = res.json()
                    st.success(f"¡Documento subido con éxito! Job ID: `{data['job_id']}`")
                else:
                    detail = res.json().get('detail', 'Error desconocido') if res.headers.get("content-type") == "application/json" else res.text
                    st.error(f"Error ({res.status_code}): {detail}")
            except Exception as e:
                st.error(f"Error conectando con la API: {str(e)}")

# ==========================================
# TAB 2: CONSULTAR ESTADO Y RESULTADO
# ==========================================
with tab2:
    st.subheader("Consultar Estado de un Trabajo")
    job_id_input = st.text_input("Ingresa el Job ID:")
    if job_id_input:
        try:
            res = requests.get(f"{API_URL}/api/v1/jobs/{job_id_input}")
            if res.status_code == 200:
                job_data = res.json()
                status = job_data.get("status")
                
                if status == "COMPLETED":
                    st.success(f"Estado: **{status}**")
                    res_res = requests.get(f"{API_URL}/api/v1/jobs/{job_id_input}/result")
                    if res_res.status_code == 200:
                        result = res_res.json()
                        col1, col2 = st.columns([2, 1])
                        with col1:
                            st.subheader("Texto Extraído")
                            st.text_area("", value=result.get("extracted_text", ""), height=300)
                            
                            # Advertencias e información adicional
                            meta = result.get("metadata") or {}
                            if isinstance(meta, dict):
                                if meta.get("low_text_warning"):
                                    st.warning(" Advertencia: Se detectó muy poco texto extraído. El documento podría estar borroso o escaneado con baja resolución.")
                                if meta.get("duplicate_of_job_id"):
                                    st.info(f" Este documento es un duplicado del Job ID: `{meta['duplicate_of_job_id']}`")
                                if meta.get("pdf_repaired"):
                                    st.warning(" El PDF estaba dañado y se reparó al abrirlo; el texto podría estar incompleto.")
                        with col2:
                            st.subheader("Metadatos")
                            st.json(result.get("metadata") or {})
                elif status == "FAILED":
                    st.error(f"Estado: **{status}**")
                    st.error(f"**Código de Error:** `{job_data.get('error_code', 'DESCONOCIDO')}`")
                    st.error(f"**Detalle del Error:** {job_data.get('error_message', 'Sin detalle')}")
                else:
                    st.info(f"Estado del Trabajo: **{status}**")
            else:
                st.error("Job ID no encontrado.")
        except Exception as e:
            st.error(f"Error consultando la API: {str(e)}")

# ==========================================
# TAB 3: DASHBOARD EN TIEMPO REAL
# ==========================================
with tab3:
    st.subheader(" Métricas y Estado en Tiempo Real (BD)")
    try:
        engine = create_engine(DATABASE_URL)
        # Consulta corregida a document_jobs
        df_jobs = pd.read_sql("SELECT * FROM document_jobs ORDER BY created_at DESC", engine)
        
        if not df_jobs.empty:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total Jobs", len(df_jobs))
            m2.metric("Completados", len(df_jobs[df_jobs['status'] == 'COMPLETED']))
            m3.metric("Fallidos", len(df_jobs[df_jobs['status'] == 'FAILED']))
            m4.metric("En Cola / Procesando", len(df_jobs[df_jobs['status'].isin(['QUEUED', 'PROCESSING'])]))
            
            st.markdown("---")
            st.write("**Distribución por Estado:**")
            st.bar_chart(df_jobs['status'].value_counts())
        else:
            st.write("No hay datos cargados en la base de datos.")
    except Exception as e:
        st.error(f"No se pudo conectar a la base de datos: {str(e)}")

# ==========================================
# TAB 4: HISTORIAL COMPLETO DE JOBS
# ==========================================
with tab4:
    st.subheader("Historial Reciente de Jobs")
    try:
        engine = create_engine(DATABASE_URL)
        # Consulta corregida a document_jobs
        df_jobs = pd.read_sql("SELECT * FROM document_jobs ORDER BY created_at DESC", engine)
        
        if not df_jobs.empty:
            # Seleccionar y reordenar columnas visibles de forma segura
            cols_to_show = [c for c in ['id', 'filename', 'file_type', 'status', 'retry_count', 'created_at', 'updated_at'] if c in df_jobs.columns]
            st.dataframe(df_jobs[cols_to_show], use_container_width=True)
        else:
            st.write("No hay registros disponibles en la base de datos.")
    except Exception as e:
        st.error(f"Error al cargar historial: {str(e)}")