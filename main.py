from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
import pandas as pd
import requests
import os
import io
import math
import threading
import json
import time

app = FastAPI()

# -----------------------------
# Configurazione job asincrono
# -----------------------------
JOB_STATE_FILE = "job_state.json"
JOB_RUNNING_FLAG = "job_running.flag"


# -----------------------------
# Funzione AI (HuggingFace Llama 3)
# -----------------------------
def ai_esperto_mondiale(titolo, autore, stato, dettagli, supporto):
    prompt = f"""
Sei un esperto mondiale di collezionismo di dischi e CD musicali.
Analizza questo articolo:
- Titolo: {titolo}
- Autore/Artista: {autore}
- Stato d'usura: {stato}
- Dettagli aggiuntivi: {dettagli}
- Supporto/Formato: {supporto}

Genera un'analisi dettagliata rispondendo RIGOROSAMENTE compilando questo schema, senza testi discorsivi:

RARITA: [Bassa, Media, Alta, Molto Alta]
GENERE: [Es. Rock, Jazz, Pop, Metal, Hip-Hop]
CLUSTER: [Gemma Storica, Mainstream Economico, Box di Valore, Oggetto di Nicchia]
NOTA: [Una frase sul perché ha valore o se ci sono varianti note]
MULTIVERSIONI: [SI/NO]
PREZZOMIN: [Prezzo in Euro]
PREZZOMAX: [Prezzo in Euro]
"""

    url = "https://api.huggingface.co/models/meta-llama/Meta-Llama-3-8B-Instruct"
    headers = {
        "Authorization": f"Bearer {os.environ['HF_TOKEN']}",
        "Content-Type": "application/json"
    }

    payload = {
        "inputs": prompt,
        "parameters": {"temperature": 0.0}
    }

    r = requests.post(url, json=payload, headers=headers)
    r.raise_for_status()

    return r.json()[0]["generated_text"]


# -----------------------------
# Gestione stato job
# -----------------------------
def save_job_state(state):
    with open(JOB_STATE_FILE, "w") as f:
        json.dump(state, f)


def load_job_state():
    if not os.path.exists(JOB_STATE_FILE):
        return {"status": "idle", "progress": 0, "current_row": 0, "total": 0}
    with open(JOB_STATE_FILE, "r") as f:
        return json.load(f)


# -----------------------------
# JOB ASINCRONO
# -----------------------------
def background_job(filename):
    df = pd.read_excel(filename)

    # Colonne AI
    colonne_ai = [
        "Rarita", "Genere_Musicale", "Cluster_Assegnato",
        "Nota_Mercato_Critica", "Presenza_Versioni_Multiple",
        "Prezzo_Min_Assoluto", "Prezzo_Max_Assoluto"
    ]
    for col in colonne_ai:
        if col not in df.columns:
            df[col] = ""

    totale = len(df)
    step = max(1, totale // 20)  # 5%

    # Stato iniziale
    state = {
        "status": "running",
        "progress": 0,
        "current_row": 0,
        "total": totale
    }
    save_job_state(state)

    # Trova prima riga non lavorata
    start_index = df[df["Cluster_Assegnato"].isna() | (df["Cluster_Assegnato"] == "")].index.min()
    if math.isnan(start_index):
        start_index = 0

    # Elaborazione
    for idx in range(int(start_index), totale):
        row = df.loc[idx]

        titolo = str(row["Titolo"])
        autore = str(row["Autore"])
        stato = str(row["Stato"])
        dettagli = str(row.get("Dettagli", ""))
        supporto = str(row["Supporto"])

        try:
            risposta = ai_esperto_mondiale(titolo, autore, stato, dettagli, supporto)

            for linea in risposta.split("\n"):
                if "RARITA:" in linea: df.at[idx, "Rarita"] = linea.split("RARITA:")[1].strip()
                if "GENERE:" in linea: df.at[idx, "Genere_Musicale"] = linea.split("GENERE:")[1].strip()
                if "CLUSTER:" in linea: df.at[idx, "Cluster_Assegnato"] = linea.split("CLUSTER:")[1].strip()
                if "NOTA:" in linea: df.at[idx, "Nota_Mercato_Critica"] = linea.split("NOTA:")[1].strip()
                if "MULTIVERSIONI:" in linea: df.at[idx, "Presenza_Versioni_Multiple"] = linea.split("MULTIVERSIONI:")[1].strip()
                if "PREZZOMIN:" in linea: df.at[idx, "Prezzo_Min_Assoluto"] = linea.split("PREZZOMIN:")[1].strip()
                if "PREZZOMAX:" in linea: df.at[idx, "Prezzo_Max_Assoluto"] = linea.split("PREZZOMAX:")[1].strip()

        except Exception as e:
            df.at[idx, "Cluster_Assegnato"] = f"Errore AI: {e}"

        # Aggiorna stato
        state["current_row"] = idx
        state["progress"] = round((idx / totale) * 100, 2)
        save_job_state(state)

        # Export intermedi
        if idx % step == 0 and idx > start_index:
            df.to_excel(f"intermedio_{idx}.xlsx", index=False)

        time.sleep(0.1)  # evita overload API

    # Export finale
    df.to_excel("finale.xlsx", index=False)

    # Stato finale
    state["status"] = "completed"
    save_job_state(state)

    # Rimuovi flag
    if os.path.exists(JOB_RUNNING_FLAG):
        os.remove(JOB_RUNNING_FLAG)


# -----------------------------
# Endpoint: avvia job
# -----------------------------
@app.post("/start-job")
async def start_job(file: UploadFile):
    filename = "input.xlsx"
    with open(filename, "wb") as f:
        f.write(await file.read())

    with open(JOB_RUNNING_FLAG, "w") as f:
        f.write("running")

    thread = threading.Thread(target=background_job, args=(filename,))
    thread.start()

    return {"message": "Job avviato", "file": filename}


# -----------------------------
# Endpoint: stato job
# -----------------------------
@app.get("/job-status")
async def job_status():
    return load_job_state()


# -----------------------------
# Endpoint: download finale
# -----------------------------
@app.get("/download-final")
async def download_final():
    if not os.path.exists("finale.xlsx"):
        raise HTTPException(status_code=404, detail="File finale non trovato")

    output = open("finale.xlsx", "rb")
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="finale.xlsx"'},
    )


# -----------------------------
# Endpoint: lista intermedi
# -----------------------------
@app.get("/list-intermedi")
async def list_intermedi():
    files = [f for f in os.listdir(".") if f.startswith("intermedio_") and f.endswith(".xlsx")]
    return {"files": files}


# -----------------------------
# Endpoint: download intermedi
# -----------------------------
@app.get("/download-intermedio")
async def download_intermedio(file: str):
    if not os.path.exists(file):
        raise HTTPException(status_code=404, detail="File non trovato")

    output = open(file, "rb")
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{file}"'},
    )

