from fastapi import FastAPI

app = FastAPI(title="SwasthyoID")


@app.get("/health")
def health():
    return {"status": "ok"}
