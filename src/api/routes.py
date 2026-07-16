from fastapi import APIRouter

from src.api.v1.ingest import router as ingest_router
api_router = APIRouter()

api_router.include_router(ingest_router)