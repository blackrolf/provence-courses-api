"""
Modèles de requêtes pour les endpoints tours
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import date


class DailyProcessRequest(BaseModel):
    """
    Requête pour le traitement quotidien (génération + optimisation optionnelle)
    """
    date: str = Field(
        description="Date pour laquelle générer les tournées (format YYYY-MM-DD)"
    )
    optimize: bool = Field(
        default=False,
        description="Active l'optimisation après la génération (true) ou génération seule (false)"
    )
    include_pending_returns: bool = Field(
        default=True,
        description="Inclut les retours en attente dans le processus (false pour optimisation seule)"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "date": "2025-08-03",
                "optimize": False
            }
        }


class OptimizeTourRequest(BaseModel):
    """
    Requête pour l'optimisation d'une tournée unique
    Note: L'ID de la tournée est passé dans l'URL, pas dans le body
    """
    force_optimization: Optional[bool] = Field(
        default=False,
        description="Force l'optimisation même si la tournée a déjà été optimisée"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "force_optimization": False
            }
        }