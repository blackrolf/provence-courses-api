"""
Repository pour la gestion des laboratories
"""

import structlog
from typing import Dict, List, Optional, Any
from ..base_client import SupabaseBaseClient

logger = structlog.get_logger()


class LaboratoriesRepository:
    """Repository pour les opérations sur laboratories"""
    
    def __init__(self, client: SupabaseBaseClient):
        self.client = client
    
    def get_all_laboratories(self) -> Dict[str, Any]:
        """Récupère tous les laboratoires"""
        return self.client.select("laboratories", "*")
    
    def get_laboratory_by_id(self, lab_id: str) -> Dict[str, Any]:
        """Récupère un laboratoire par son ID"""
        return self.client.select("laboratories", "*", id=lab_id)
    
    def get_shared_pickup_laboratories(self) -> Dict[str, Any]:
        """Récupère les laboratoires avec shared_pickup = true"""
        return self.client.select("laboratories", "*", shared_pickup="eq.true")