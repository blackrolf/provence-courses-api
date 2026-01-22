"""
Repository pour la gestion des driver_routes
"""

import structlog
from typing import Dict, List, Optional, Any
from datetime import datetime
from ..base_client import SupabaseBaseClient

logger = structlog.get_logger()


class RoutesRepository:
    """Repository pour les opérations sur driver_routes"""
    
    def __init__(self, client: SupabaseBaseClient):
        self.client = client
    
    def get_route_by_id(self, route_id: str) -> Dict[str, Any]:
        """
        Récupère une route par son ID
        
        Args:
            route_id: ID de la route
            
        Returns:
            Dict: Route ou erreur
        """
        logger.debug("Getting route by ID", route_id=route_id)
        
        return self.client.select(
            "driver_routes",
            "*",
            id=route_id
        )
    
    def get_routes_by_date(self, date: str, driver_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Récupère les routes d'une date donnée
        
        Args:
            date: Date au format YYYY-MM-DD
            driver_id: ID du driver (optionnel)
            
        Returns:
            Dict: Routes ou erreur
        """
        logger.debug("Getting routes by date", date=date, driver_id=driver_id)
        
        filters = {"date": f"eq.{date}"}
        if driver_id:
            filters["driver_id"] = f"eq.{driver_id}"
        
        return self.client.select(
            "driver_routes",
            "*",
            **filters
        )
    
    def get_routes_by_status(self, date: str, statuses: List[str]) -> Dict[str, Any]:
        """
        Récupère les routes par statut pour une date
        
        Args:
            date: Date au format YYYY-MM-DD
            statuses: Liste des statuts
            
        Returns:
            Dict: Routes ou erreur
        """
        logger.debug("Getting routes by status", date=date, statuses=statuses)
        
        # Pour PostgREST, on utilise in.() pour les listes
        status_filter = f"in.({','.join(statuses)})"
        
        return self.client.select(
            "driver_routes",
            "*",
            date=f"eq.{date}",
            status=status_filter
        )
    
    def create_driver_route(self, route_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Crée une nouvelle driver_route (alias pour create_route)
        
        Args:
            route_data: Données de la route
            
        Returns:
            Dict: Route créée ou erreur
        """
        return self.create_route(route_data)
    
    def create_route(self, route_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Crée une nouvelle route
        
        Args:
            route_data: Données de la route
            
        Returns:
            Dict: Route créée ou erreur
        """
        logger.info("Creating new route", driver_id=route_data.get("driver_id"))
        
        # Ajouter les timestamps si pas présents
        if "created_at" not in route_data:
            route_data["created_at"] = datetime.now().isoformat()
        if "updated_at" not in route_data:
            route_data["updated_at"] = datetime.now().isoformat()
        
        return self.client.insert("driver_routes", route_data)
    
    def update_route_status(self, route_id: str, status: str) -> Dict[str, Any]:
        """
        Met à jour le statut d'une route
        
        Args:
            route_id: ID de la route
            status: Nouveau statut
            
        Returns:
            Dict: Route mise à jour ou erreur
        """
        logger.info("Updating route status", route_id=route_id, status=status)
        
        update_data = {
            "status": status,
            "updated_at": datetime.now().isoformat()
        }
        
        return self.client.update(
            "driver_routes",
            update_data,
            id=route_id
        )
    
    def update_route_optimization_data(self, route_id: str, optimization_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Met à jour les données d'optimisation d'une route
        
        Args:
            route_id: ID de la route
            optimization_data: Données d'optimisation (duration, distance, polyline)
            
        Returns:
            Dict: Route mise à jour ou erreur
        """
        logger.info("Updating route optimization data", route_id=route_id)
        
        update_data = {
            **optimization_data,
            "updated_at": datetime.now().isoformat()
        }
        
        return self.client.update(
            "driver_routes",
            update_data,
            id=route_id
        )
    
    def delete_routes_by_conditions(self, date: str, statuses: List[str]) -> Dict[str, Any]:
        """
        Supprime les routes selon des conditions
        
        Args:
            date: Date cible (YYYY-MM-DD)
            statuses: Liste des statuts à supprimer
            
        Returns:
            Dict: Résultat de la suppression avec compteur
        """
        logger.info("Deleting routes by conditions", date=date, statuses=statuses)
        
        try:
            # D'abord, récupérer les routes à supprimer pour les logs
            routes_result = self.get_routes_by_status(date, statuses)
            
            if routes_result["status"] != "success":
                return routes_result
            
            routes_to_delete = routes_result["data"]
            
            if not routes_to_delete:
                return {
                    "status": "success",
                    "message": "Aucune route à supprimer",
                    "deleted_count": 0,
                    "deleted_routes": []
                }
            
            # Supprimer chaque route individuellement
            # Note: Les stops et shipments seront supprimés en cascade si configuré
            deleted_count = 0
            deleted_routes = []
            
            for route in routes_to_delete:
                delete_result = self.client.delete("driver_routes", id=route["id"])
                if delete_result["status"] == "success":
                    deleted_count += 1
                    deleted_routes.append(route["id"])
                else:
                    logger.warning("Failed to delete route", 
                                 route_id=route["id"], 
                                 error=delete_result.get("message"))
            
            logger.info("Routes deletion completed", 
                       total_found=len(routes_to_delete),
                       deleted_count=deleted_count)
            
            return {
                "status": "success",
                "message": f"{deleted_count}/{len(routes_to_delete)} routes supprimées",
                "deleted_count": deleted_count,
                "deleted_routes": deleted_routes
            }
            
        except Exception as e:
            logger.error("Error deleting routes by conditions", error=str(e))
            return {
                "status": "error",
                "message": f"Erreur lors de la suppression des routes: {str(e)}"
            }
    
    def delete_route_by_id(self, route_id: str) -> Dict[str, Any]:
        """
        Supprime une route par son ID
        
        Args:
            route_id: ID de la route
            
        Returns:
            Dict: Résultat de la suppression
        """
        logger.info("Deleting route by ID", route_id=route_id)
        
        return self.client.delete("driver_routes", id=route_id)