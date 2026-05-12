from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
import os
try:
    # When launched as a package: `python -m uvicorn backend.main:app`
    from .database import get_db, engine, ensure_performance_indexes
    from .models import Base
    from .routes import router
except ImportError:
    # When launched from within `backend/`: `python -m uvicorn main:app`
    from database import get_db, engine, ensure_performance_indexes
    from models import Base
    from routes import router

Base.metadata.create_all(bind=engine)
ensure_performance_indexes()

app = FastAPI(title="Traffic Intelligence API", version="1.0.0")

allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "")
if allowed_origins_raw:
    allowed_origins = [origin.strip() for origin in allowed_origins_raw.split(",") if origin.strip()]
else:
    # Fallback to allow all for easier initial cloud deployment, 
    # but still include localhost for development.
    allowed_origins = ["*"]

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

@app.get("/")
async def root():
    return {"message": "Traffic Intelligence Backend API"}

@app.get("/health")
async def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}
