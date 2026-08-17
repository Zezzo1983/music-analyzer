import os
import json
import threading
import time
import pandas as pd
import requests
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse

app = FastAPI()

# ---------------------------
# FUNZIONE AI CORRETTA + RETRY HF_TOKEN
# ---------------------------
def call_ai_service(titolo, autore):
    try:
        # Retry automatico per HF_TOKEN
        HF_TOKEN = None
        for _ in range(5):
            HF_TOKEN = os.environ.get("HF_TOKEN")
            if HF_TOKEN:
                break
            time.sleep(1)

        if HF_TOKEN is None:
            return {"errore": "HF_TOKEN non disponibile nel container dopo 5 tentativi"}

        url = "https://api-inference.huggingface.co/models/mistralai/Mixtral-8x7B-Instruct-v0.1"

        headers = {
            "Authorization": f"Bearer {HF_TOKEN}",
            "Content-Type": "application/json"
        }

        prompt = f"""
Sei un esperto mondiale di musica, rarità, collezionismo e mercato dei dischi.
Analizza questo disco e restituisci SOLO un JSON con queste chiavi:

- rarita
- genere
- cluster
- prezzo_min
- prezzo_max

Disco:
Titolo: {titolo}
Autore: {autore}

Rispondi SOLO con JSON valido.
"""

        payload = {"inputs": prompt}

        response = requests.post(url, headers=headers, json=payload, timeout=60)

        if response.status_code != 200:
            return {"errore": f"Errore HuggingFace: {response.status_code} - {response.text}"}

        data = response.json()

        if isinstance(data, list) and "generated_text" in data[0]:
            raw = data[0]["generated_text"]
        else:
            return {"errore": f"Formato risposta inatteso: {data}"}

        try:
            parsed = json.loads(raw)
            return parsed
        except Exception as e:
            return {"errore": f"JSON non valido: {e} - RAW: {raw}"}

    except Exception as e:
        return {"errore": f"Errore AI interno: {e}"}


# ---------------------------
# JOB ASINCRONO
# ---------------------------
def process_file_async(df):
    total = len(df)
    progress_step = max(1, int(total * 0.025))  # 2.5%

    next_intermediate = progress_step
    current_index = 0

    with open("job_running.flag", "w") as f:
        f.write("1")

    while current_index < total:
        if not os.path.exists("job_running.flag"):
            break

        row = df.iloc[current_index]
        titolo = str(row["Titolo"])
        autore = str(row["Autore"])

        risultato = call_ai_service(titolo, autore)

        if "errore" in risultato:
            df.at[current_index, "Cluster_Assegnato"] = risultato["errore"]
        else:
            df.at[current_index, "Rarita"] = risultato.get("rarita")
            df.at[current_index, "Genere"] = risultato.get("genere")
            df.at[current_index, "Cluster_Assegnato"] = risultato.get("cluster")
            df.at[current_index, "PrezzoMin"] = risultato.get("prezzo_min")
            df.at[current_index, "PrezzoMax"] = risultato.get("prezzo_max")

        with open("job_state.json", "w") as f:
            json.dump({
                "current": current_index + 1,
                "total": total,
                "percent": round((current_index + 1) / total * 100, 2),
                "running": True
            }, f)

        if current_index + 1 >= next_intermediate:
            filename = f"intermedio_{current_index+1}.xlsx"
            df.to_excel(filename, index=False)
            next_intermediate += progress_step

        current_index += 1
        time.sleep(0.1)

    df.to_excel("finale.xlsx", index=False)

    with open("job_state.json", "w") as f:
        json.dump({
            "current": min(current_index, total),
            "total": total,
            "percent": 100 if current_index >= total else round(current_index / total * 100, 2),
            "running": False
        }, f)


# ---------------------------
# ENDPOINT FASTAPI
# ---------------------------

@app.post("/start-job")
async def start_job(file: UploadFile = File(...)):
    for f in os.listdir("."):
        if f.startswith("intermedio_") or f in ["finale.xlsx", "job_state.json", "input.xlsx", "job_running.flag"]:
            try:
                os.remove(f)
            except:
                pass

    with open("input.xlsx", "wb") as f:
        f.write(await file.read())

    df = pd.read_excel("input.xlsx")

    for col in ["Rarita", "Genere", "Cluster_Assegnato", "PrezzoMin", "PrezzoMax"]:
        if col not in df.columns:
            df[col] = None

    thread = threading.Thread(target=process_file_async, args=(df,))
    thread.start()

    return {"status": "Job avviato"}


@app.get("/job-status")
def job_status():
    if not os.path.exists("job_state.json"):
        return {"running": False, "percent": 0}
    with open("job_state.json", "r") as f:
        return json.load(f)


@app.get("/list-intermedi")
def list_intermedi():
    files = [f for f in os.listdir(".") if f.startswith("intermedio_")]
    return {"intermedi": files}


@app.get("/download-intermedio")
def download_intermedio(name: str):
    return FileResponse(
        name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.get("/download-finale")
def download_finale():
    return FileResponse(
        "finale.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ---------------------------
# STOP JOB
# ---------------------------
@app.post("/stop-job")
def stop_job(clean_intermedi: bool = False):
    if os.path.exists("job_state.json"):
        try:
            with open("job_state.json", "r") as f:
                state = json.load(f)
        except:
            state = {"current": 0, "total": 0, "percent": 0}

        state["running"] = False

        with open("job_state.json", "w") as f:
            json.dump(state, f)

    if os.path.exists("job_running.flag"):
        os.remove("job_running.flag")

    if clean_intermedi:
        for f in os.listdir("."):
            if f.startswith("intermedio_"):
                try:
                    os.remove(f)
                except:
                    pass

    return {
        "status": "Job fermato",
        "intermedi_cancellati": clean_intermedi
    }


@app.get("/")
def home():
    return {"status": "ok", "message": "music-analyzer attivo"}

@app.get("/")
def home():
    return {"status": "ok", "message": "music-analyzer attivo"}
