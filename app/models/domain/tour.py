"""
Modèles de domaine pour les tournées
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, date
from enum import Enum


class TourStatus(str, Enum):
    """Statuts possibles d'une tournée"""
    PENDING = "pending"
    OPTIMIZED = "optimized"
    VALIDATED = "validated"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class Location(BaseModel):
    """Modèle pour une localisation"""
    id: str
    name: str
    address: str
    latitude: float
    longitude: float
    type: str  # "laboratory", "depot", etc.


class TourStop(BaseModel):
    """Modèle pour un arrêt dans une tournée"""
    id: str
    tour_id: str
    location_id: str
    location: Optional[Location] = None
    stop_order: int
    estimated_arrival: Optional[datetime] = None
    estimated_departure: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    status: str = "pending"


class Tour(BaseModel):
    """Modèle principal pour une tournée"""
    id: str
    date: date
    driver_id: Optional[str] = None
    driver_name: Optional[str] = None
    status: TourStatus
    estimated_start_time: Optional[datetime] = None
    estimated_end_time: Optional[datetime] = None
    estimated_duration_minutes: Optional[int] = None
    total_distance_km: Optional[float] = None
    stops: List[TourStop] = []
    created_at: datetime
    updated_at: datetime
    
    class Config:
        use_enum_values = True


class DailyTourData(BaseModel):
    """Données pour la génération quotidienne de tournées"""
    date: date
    available_drivers: List[dict]
    pending_shipments: List[dict]
    laboratories: List[Location]
    depots: List[Location]