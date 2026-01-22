"""
Service centralisé pour la gestion de la location du dépôt
"""

import structlog
from typing import Dict, Optional
from app.integrations.supabase.base_client import supabase_base_client
from .exceptions import DataRetrievalError

logger = structlog.get_logger()


class DepotLocationService:
    """Service centralisé pour récupérer la location du dépôt de manière robuste"""
    
    def __init__(self):
        self.supabase = supabase_base_client
        self._cached_depot_location_id: Optional[str] = None
    
    def get_depot_location_id(self) -> str:
        """
        Récupère la location_id du dépôt actif selon la logique métier
        
        Logique:
        1. Chercher dans locations avec type='depot'
        2. Si plusieurs entrées, prendre la plus récente (created_at DESC)
        3. Cache le résultat pour éviter les requêtes répétées
        
        Returns:
            str: UUID de la location du dépôt
            
        Raises:
            DataRetrievalError: Si aucun dépôt trouvé
        """
        # Utiliser le cache si disponible
        if self._cached_depot_location_id:
            logger.debug("Using cached depot location", location_id=self._cached_depot_location_id)
            return self._cached_depot_location_id
        
        logger.info("Retrieving depot location from database")
        
        try:
            # Chercher les locations de type 'depot', triées par created_at DESC
            result = self.supabase.select(
                "locations",
                "id, formatted_address, created_at",
                type="depot",
                order="created_at.desc"
            )
            
            if result["status"] != "success":
                raise DataRetrievalError(f"Erreur lors de la récupération des locations dépôt: {result['message']}")
            
            depot_locations = result["data"]
            
            if not depot_locations:
                raise DataRetrievalError("Aucune location de type 'depot' trouvée dans la base")
            
            # Prendre la plus récente (première dans la liste triée DESC)
            latest_depot = depot_locations[0]
            depot_location_id = latest_depot["id"]
            
            # Mettre en cache
            self._cached_depot_location_id = depot_location_id
            
            logger.info("Depot location retrieved successfully",
                       location_id=depot_location_id,
                       address=latest_depot.get("formatted_address", ""),
                       created_at=latest_depot.get("created_at", ""),
                       total_depots_found=len(depot_locations))
            
            if len(depot_locations) > 1:
                logger.warning("Multiple depot locations found, using most recent",
                             total_depots=len(depot_locations),
                             selected_depot=depot_location_id)
            
            return depot_location_id
            
        except Exception as e:
            logger.error("Error retrieving depot location", error=str(e))
            raise DataRetrievalError(f"Impossible de récupérer la location du dépôt: {str(e)}")
    
    def get_depot_location_data(self) -> Dict:
        """
        Récupère les données complètes de la location du dépôt
        
        Returns:
            Dict: Données complètes de la location (coordonnées, adresse, etc.)
        """
        depot_location_id = self.get_depot_location_id()
        
        try:
            result = self.supabase.select(
                "locations",
                "*",
                id=depot_location_id
            )
            
            if result["status"] != "success" or not result["data"]:
                raise DataRetrievalError(f"Données de la location dépôt introuvables: {depot_location_id}")
            
            depot_data = result["data"][0]
            
            logger.debug("Depot location data retrieved",
                        location_id=depot_location_id,
                        has_coordinates=bool(depot_data.get("latitude") and depot_data.get("longitude")))
            
            return depot_data
            
        except Exception as e:
            logger.error("Error retrieving depot location data", 
                        location_id=depot_location_id, 
                        error=str(e))
            raise DataRetrievalError(f"Erreur lors de la récupération des données du dépôt: {str(e)}")
    
    def clear_cache(self):
        """Vide le cache de la location du dépôt (utile pour les tests ou changements)"""
        logger.debug("Clearing depot location cache")
        self._cached_depot_location_id = None
    
    def validate_depot_location(self) -> Dict:
        """
        Valide que la location du dépôt a toutes les données nécessaires
        
        Returns:
            Dict: Rapport de validation
        """
        try:
            depot_data = self.get_depot_location_data()
            
            validation_report = {
                "is_valid": True,
                "location_id": depot_data["id"],
                "issues": []
            }
            
            # Vérifications essentielles
            if not depot_data.get("latitude"):
                validation_report["issues"].append("Latitude manquante")
                validation_report["is_valid"] = False
            
            if not depot_data.get("longitude"):
                validation_report["issues"].append("Longitude manquante")
                validation_report["is_valid"] = False
            
            if not depot_data.get("formatted_address"):
                validation_report["issues"].append("Adresse formatée manquante")
            
            if not depot_data.get("type") == "depot":
                validation_report["issues"].append(f"Type incorrect: {depot_data.get('type')} au lieu de 'depot'")
                validation_report["is_valid"] = False
            
            validation_report["depot_data"] = depot_data
            
            if validation_report["is_valid"]:
                logger.info("Depot location validation passed", location_id=depot_data["id"])
            else:
                logger.warning("Depot location validation failed", 
                             location_id=depot_data["id"],
                             issues=validation_report["issues"])
            
            return validation_report
            
        except Exception as e:
            logger.error("Error during depot location validation", error=str(e))
            return {
                "is_valid": False,
                "location_id": None,
                "issues": [f"Erreur de validation: {str(e)}"],
                "depot_data": None
            }


# Instance globale pour réutilisation
depot_location_service = DepotLocationService()


def get_depot_location_id() -> str:
    """
    Fonction utilitaire pour récupérer rapidement la location_id du dépôt
    
    Returns:
        str: UUID de la location du dépôt
    """
    return depot_location_service.get_depot_location_id()


def get_depot_location_data() -> Dict:
    """
    Fonction utilitaire pour récupérer les données complètes du dépôt
    
    Returns:
        Dict: Données complètes de la location du dépôt
    """
    return depot_location_service.get_depot_location_data()