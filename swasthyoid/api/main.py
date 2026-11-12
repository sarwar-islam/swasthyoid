import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from swasthyoid import db
from swasthyoid.api import caregivers, m1
from swasthyoid.api.deps import ApiError, check_config


@asynccontextmanager
async def lifespan(app):
    check_config()
    if "DATABASE_URL" in os.environ:
        with db.connect() as conn:
            db.apply_schema(conn)
    yield


app = FastAPI(title="SwasthyoID", lifespan=lifespan)
app.include_router(m1.router, prefix="/api/v1")
app.include_router(caregivers.router, prefix="/api/v1")


@app.exception_handler(ApiError)
async def api_error(request, exc: ApiError):
    return JSONResponse({"code": exc.code, "message": exc.message, "details": exc.details}, status_code=exc.status)


@app.get("/health")
def health():
    return {"status": "ok"}
