from fastapi import FastAPI, UploadFile
from fastapi.responses import StreamingResponse
import pandas as pd
import requests
import os
import io
import math

app = FastAPI()

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

    url = "https://api-inference.huggingface.co/models/meta-llama/Meta-Llama-3-8B-Instruct"
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
# Endpoint principale con export finale + export intermedi
# -----------------------------

@app.post("/process-and-export")
async def process_and_export(file: UploadFile):
    df = pd.read_excel(file.file)

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
    step = max(1, totale // 20)  # 5% del totale

    # Trova la prima riga NON lavorata
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

        # Export intermedi ogni 5%
        if idx % step == 0 and idx > start_index:
            buffer = io.BytesIO()
            df.to_excel(buffer, index=False)
            buffer.seek(0)
            # Salva file intermedio
            with open(f"intermedio_{idx}.xlsx", "wb") as f:
                f.write(buffer.read())

    # Export finale
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return StreamingResponse(
    output,
    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    headers={"Content-Disposition": 'attachment; filename="dischi_analizzati_finale.xlsx"'},
)

