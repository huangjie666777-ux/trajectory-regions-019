from fastapi import FastAPI

app = FastAPI(title="Trajectory Region Analysis")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
