"""
Repository pour la gestion des laboratory_clients
"""

import structlog
from typing import Dict, List, Optional, Any
from ..base_client import SupabaseBaseClient

logger = structlog.get_logger()


class ClientsRepository:
    """Repository pour les opérations sur laboratory_clients"""
    
    def __init__(self, client: SupabaseBaseClient):
        self.client = client
    
    def get_all_clients(self) -> Dict[str, Any]:
        """Récupère tous les clients"""
        return self.client.select("laboratory_clients", "*")
    
    def get_client_by_id(self, client_id: str) -> Dict[str, Any]:
        """Récupère un client par son ID"""
        return self.client.select("laboratory_clients", "*", id=client_id)
    
    def get_clients_by_driver_id(self, driver_id: str) -> Dict[str, Any]:
        """Récupère les clients d'un driver"""
        return self.client.select("laboratory_clients", "*", driver_id=driver_id)