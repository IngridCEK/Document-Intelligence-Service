import requests
import time
import subprocess

API_URL = "http://localhost:8000"

def test_chaos():
    print("=== TEST DE RESILIENCIA Y RECUPERACIÓN ANTE FALLOS ===")
    
    # 1. Subir documento
    print("1. Subiendo documento de prueba...")
    with open("test.pdf", "wb") as f:
        f.write(b"%PDF-1.4 Fake PDF Content for Chaos Test")
    
    with open("test.pdf", "rb") as f:
        res = requests.post(f"{API_URL}/api/v1/documents/upload", files={"file": ("test.pdf", f, "application/pdf")})
    
    job_id = res.json()["job_id"]
    print(f"Job subido correctamente. ID: {job_id}")

    # 2. Matar worker con kill -9
    print("2. Simulando caída drástica del worker (kill -9 doc_intel_worker)...")
    subprocess.run(["docker", "kill", "-s", "SIGKILL", "doc_intel_worker"])
    
    print("3. Reiniciando contenedor del worker...")
    time.sleep(3)
    subprocess.run(["docker", "start", "doc_intel_worker"])

    # 4. Verificar re-procesamiento
    print("4. Esperando a que el sistema re-procese y resuelva el job...")
    time.sleep(15)
    
    res_status = requests.get(f"{API_URL}/api/v1/jobs/{job_id}")
    print(f"Estado del Job tras la recuperación: {res_status.json()['status']}")

if __name__ == "__main__":
    test_chaos()