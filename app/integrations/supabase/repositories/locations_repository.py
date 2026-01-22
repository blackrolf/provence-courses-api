"""
Repository pour la gestion des locations
"""

import structlog
from typing import Dict, List, Optional, Any
from ..base_client import SupabaseBaseClient

logger = structlog.get_logger()


class LocationsRepository:
    """Repository pour les opérations sur locations"""
    
    def __init__(self, client: SupabaseBaseClient):
        self.client = client
    
    def get_all_locations(self) -> Dict[str, Any]:
        """Récupère toutes les locations"""
        return self.client.select("locations", "*")
    
    def get_location_by_id(self, location_id: str) -> Dict[str, Any]:
        """Récupère une location par son ID"""
        return self.client.select("locations", "*", id=location_id)
    
    def get_locations_map(self) -> Dict[str, Dict]:
        """
        Récupère toutes les locations sous forme de map
        
        Returns:
            Dict[str, Dict]: Map location_id -> location_data
        """
        result = self.get_all_locations()
        
        if result["status"] != "success":
            return {}
        
        return {loc["id"]: loc for loc in result["data"]}