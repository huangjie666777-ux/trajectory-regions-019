from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .analysis import InputError, analyze
from .models import AnalyzeRequest, AnalyzeResponse

app = FastAPI(
    title="Trajectory Region Analysis",
    version="1.0.0",
    description="设备轨迹穿越区域分析：平面米制坐标，直线匀速插值，边界不计入区域。",
)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request, exc):
    errors = [
        {"loc": list(error.get("loc", ())), "msg": error.get("msg", ""), "type": error.get("type", "")}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.post("/api/v1/analyze", response_model=AnalyzeResponse)
def analyze_endpoint(request: AnalyzeRequest):
    try:
        details, summaries = analyze(request)
    except InputError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return AnalyzeResponse(details=details, region_summaries=summaries)
