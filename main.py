from fastapi import FastAPI, UploadFile
import pandas as pd
import uvicorn

app = FastAPI()

@app.post("/process")
async def process_excel(file: UploadFile):
    df = pd.read_excel(file.file)

    # Qui metterai la tua logica vera
    result = {
        "righe": len(df),
        "colonne": list(df.columns)
    }

    return result

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
