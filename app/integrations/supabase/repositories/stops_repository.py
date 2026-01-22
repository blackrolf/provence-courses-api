"""
Repository pour la gestion des driver_route_stops
"""

import structlog
from typing import Dict, List, Optional, Any
from datetime import datetime
from ..base_client import SupabaseBaseClient

logger = structlog.get_logger()


class StopsRepository:
    """Repository pour les opérations sur driver_route_stops"""
    
    def __init__(self, client: SupabaseBaseClient):
        self.client = client
    
    def get_stops_by_route_id(self, route_id: str) -> Dict[str, Any]:
        """
        Récupère tous les stops d'une route
        
        Args:
            route_id: ID de la route
            
        Returns:
            Dict: Stops ordonnés ou erreur
        """
        logger.debug("Getting stops by route ID", route_id=route_id)
        
        # Récupérer avec ordre par stop_order
        result = self.client.select(
            "driver_route_stops",
            "*",
            route_id=f"eq.{route_id}"
        )
        
        # Trier par stop_order côté client si nécessaire
        if result["status"] == "success":
            stops = result["data"]
            stops.sort(key=lambda x: x.get("stop_order", 0))
            result["data"] = stops
        
        return result
    
    def get_stop_by_id(self, stop_id: str) -> Dict[str, Any]:
        """
        Récupère un stop par son ID
        
        Args:
            stop_id: ID du stop
            
        Returns:
            Dict: Stop ou erreur
        """
        logger.debug("Getting stop by ID", stop_id=stop_id)
        
        return self.client.select(
            "driver_route_stops",
            "*",
            id=stop_id
        )
    
    def create_stop(self, stop_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Crée un nouveau stop
        
        Args:
            stop_data: Données du stop
            
        Returns:
            Dict: Stop créé ou erreur
        """
        logger.debug("Creating new stop", 
                    route_id=stop_data.get("route_id"),
                    stop_type=stop_data.get("stop_type"))
        
        # Ajouter timestamp si pas présent
        if "created_at" not in stop_data:
            stop_data["created_at"] = datetime.now().isoformat()
        
        return self.client.insert("driver_route_stops", stop_data)
    
    def create_multiple_stops(self, stops_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Crée plusieurs stops en une fois
        
        Args:
            stops_data: Liste des données de stops
            
        Returns:
            Dict: Résultat de la création
        """
        logger.info("Creating multiple stops", count=len(stops_data))
        
        try:
            created_stops = []
            failed_stops = []
            
            for stop_data in stops_data:
                result = self.create_stop(stop_data)
                if result["status"] == "success":
                    created_stops.extend(result["data"])
                else:
                    failed_stops.append({
                        "stop_data": stop_data,
                        "error": result["message"]
                    })
            
            if failed_stops:
                logger.warning("Some stops failed to create", 
                             failed_count=len(failed_stops))
                return {
                    "status": "partial_success",
                    "message": f"{len(created_stops)} stops créés, {len(failed_stops)} échecs",
                    "data": created_stops,
                    "failed": failed_stops
                }
            
            return {
                "status": "success",
                "message": f"{len(created_stops)} stops créés",
                "data": created_stops
            }
            
        except Exception as e:
            logger.error("Error creating multiple stops", error=str(e))
            return {
                "status": "error",
                "message": f"Erreur lors de la création des stops: {str(e)}"
            }
    
    def update_stop_completion(self, stop_id: str, completion_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Met à jour les données de completion d'un stop
        
        Args:
            stop_id: ID du stop
            completion_data: Données de completion (completed, arrival_time, etc.)
            
        Returns:
            Dict: Stop mis à jour ou erreur
        """
        logger.info("Updating stop completion", stop_id=stop_id)
        
        return self.client.update(
            "driver_route_stops",
            completion_data,
            id=stop_id
        )
    
    def update_stop_optimization_data(self, stop_id: str, optimization_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Met à jour les données d'optimisation d'un stop
        
        Args:
            stop_id: ID du stop
            optimization_data: Données d'optimisation (times, distances, etc.)
            
        Returns:
            Dict: Stop mis à jour ou erreur
        """
        logger.debug("Updating stop optimization data", stop_id=stop_id)
        
        return self.client.update(
            "driver_route_stops",
            optimization_data,
            id=stop_id
        )
    
    def update_stop(self, stop_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Met à jour un stop avec des données quelconques
        
        Args:
            stop_id: ID du stop
            update_data: Données à mettre à jour
            
        Returns:
            Dict: Stop mis à jour ou erreur
        """
        logger.debug("Updating stop", stop_id=stop_id, fields=list(update_data.keys()))
        
        return self.client.update(
            "driver_route_stops",
            update_data,
            id=stop_id
        )
    
    def get_stops_by_location(self, location_id: str, date: Optional[str] = None) -> Dict[str, Any]:
        """
        Récupère tous les stops pour une location donnée
        
        Args:
            location_id: ID de la location
            date: Date optionnelle pour filtrer
            
        Returns:
            Dict: Stops ou erreur
        """
        logger.debug("Getting stops by location", location_id=location_id, date=date)
        
        filters = {"location_id": f"eq.{location_id}"}
        
        # Si date fournie, joindre avec driver_routes pour filtrer
        # Pour simplifier, on récupère tous les stops et on filtre côté client
        return self.client.select(
            "driver_route_stops",
            "*",
            **filters
        )
    
    def delete_stops_by_route_id(self, route_id: str) -> Dict[str, Any]:
        """
        Supprime tous les stops d'une route
        
        Args:
            route_id: ID de la route
            
        Returns:
            Dict: Résultat de la suppression
        """
        logger.info("Deleting stops by route ID", route_id=route_id)
        
        return self.client.delete(
            "driver_route_stops",
            route_id=route_id
        )