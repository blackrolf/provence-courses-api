"""
Repository pour la gestion des drivers
"""

import structlog
from typing import Dict, List, Optional, Any
from ..base_client import SupabaseBaseClient

logger = structlog.get_logger()


class DriversRepository:
    """Repository pour les opérations sur drivers"""
    
    def __init__(self, client: SupabaseBaseClient):
        self.client = client
    
    def get_all_drivers(self) -> Dict[str, Any]:
        """Récupère tous les drivers"""
        return self.client.select("drivers", "*")
    
    def get_driver_by_id(self, driver_id: str) -> Dict[str, Any]:
        """Récupère un driver par son ID"""
        return self.client.select("drivers", "*", id=driver_id)
    
    def get_active_drivers(self) -> Dict[str, Any]:
        """Récupère les drivers actifs"""
        # Supposer qu'il y a un champ 'active' ou similaire
        return self.client.select("drivers", "*")  # À adapter selon le schéma
    
    def get_driver_with_start_info(self, driver_id: str) -> Dict[str, Any]:
        """
        Récupère un driver avec ses informations de départ (start_time)
        
        Args:
            driver_id: ID du driver
            
        Returns:
            Dict: Données du driver incluant start_time
        """
        logger.info("Retrieving driver with start info", driver_id=driver_id)
        
        result = self.client.select("drivers", "id, full_name, start_time", id=f"eq.{driver_id}")
        
        if result["status"] == "success" and result["data"]:
            driver_data = result["data"][0]
            logger.info("Driver start info retrieved", 
                       driver_id=driver_id,
                       start_time=driver_data.get("start_time"))
            return result
        
        logger.warning("Driver not found or no start_time", driver_id=driver_id)
        return result