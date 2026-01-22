"""
Application FastAPI principale
"""

import structlog
from fastapi import FastAPI
from app.api.v1.routes import tours
from app.core.config import settings

# Configuration du logging
logger = structlog.get_logger()

def create_app() -> FastAPI:
    """Crée l'application FastAPI"""
    
    app = FastAPI(
        title="Provence Courses API",
        description="API centralisée pour la gestion des tournées",
        version="1.0.0"
    )
    
    # Inclure les routes
    app.include_router(tours.router, prefix="/api/v1")
    
    return app

# Créer l'instance de l'app
app = create_app()

@app.get("/")
async def root():
    """Endpoint de santé"""
    return {"message": "Provence Courses API is running"}

@app.get("/health")
async def health():
    """Endpoint de vérification de santé"""
    return {"status": "healthy"}

