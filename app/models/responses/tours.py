"""
Modèles de réponses pour les endpoints tours
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from enum import Enum


class TourStatus(str, Enum):
    """Statuts possibles d'une tournée"""
    PENDING = "pending"
    OPTIMIZED = "optimized"
    VALIDATED = "validated"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class ProcessedTour(BaseModel):
    """Détails d'une tournée traitée"""
    tour_id: str = Field(description="ID de la tournée")
    status: TourStatus = Field(description="Nouveau statut après traitement")
    stops_count: int = Field(description="Nombre d'arrêts dans la tournée")
    driver_name: Optional[str] = Field(default=None, description="Nom du chauffeur assigné")
    estimated_duration: Optional[str] = Field(default=None, description="Durée estimée (format HH:MM)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "tour_id": "123e4567-e89b-12d3-a456-426614174000",
                "status": "optimized",
                "stops_count": 8,
                "driver_name": "Jean Dupont",
                "estimated_duration": "04:30"
            }
        }


class DailyProcessResponse(BaseModel):
    """Réponse pour le traitement quotidien"""
    status: str = Field(description="Statut de l'opération")
    message: str = Field(description="Message descriptif")
    processed_tours: List[ProcessedTour] = Field(description="Liste des tournées traitées")
    processing_time: str = Field(description="Temps de traitement")
    date: str = Field(description="Date traitée (YYYY-MM-DD)")
    generation_enabled: bool = Field(description="Génération activée")
    optimization_enabled: bool = Field(description="Optimisation activée")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "message": "Traitement quotidien terminé avec succès",
                "processed_tours": [
                    {
                        "tour_id": "123e4567-e89b-12d3-a456-426614174000",
                        "status": "optimized",
                        "stops_count": 8,
                        "driver_name": "Jean Dupont",
                        "estimated_duration": "04:30"
                    }
                ],
                "processing_time": "1m 23s",
                "date": "2025-08-03",
                "generation_enabled": True,
                "optimization_enabled": True
            }
        }


class OptimizeTourResponse(BaseModel):
    """Réponse pour l'optimisation d'une tournée unique"""
    status: str = Field(description="Statut de l'opération")
    message: str = Field(description="Message descriptif")
    processed_tours: List[ProcessedTour] = Field(description="Tournée optimisée (liste avec 1 élément)")
    processing_time: str = Field(description="Temps de traitement")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "message": "Tournée optimisée avec succès",
                "processed_tours": [
                    {
                        "tour_id": "123e4567-e89b-12d3-a456-426614174000",
                        "status": "optimized",
                        "stops_count": 8,
                        "driver_name": "Jean Dupont",
                        "estimated_duration": "04:15"
                    }
                ],
                "processing_time": "32s"
            }
        }


class ApiErrorResponse(BaseModel):
    """Réponse d'erreur standardisée"""
    status: str = Field(default="error", description="Statut de l'opération")
    message: str = Field(description="Message d'erreur")
    error_code: Optional[str] = Field(default=None, description="Code d'erreur spécifique")
    details: Optional[dict] = Field(default=None, description="Détails additionnels")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "error",
                "message": "Tournée non trouvée ou statut incorrect",
                "error_code": "TOUR_NOT_FOUND",
                "details": {
                    "tour_id": "123e4567-e89b-12d3-a456-426614174000",
                    "current_status": "completed"
                }
            }
        }