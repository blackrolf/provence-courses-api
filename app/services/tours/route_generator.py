"""
Service de génération des routes et stops dans Supabase
"""

import structlog
import random
from datetime import datetime
from typing import List, Dict
from app.services.tours.data_retriever import TourDataRetriever
from .exceptions import RouteCreationError

logger = structlog.get_logger()


class RouteGenerator:
    """Service de génération des routes dans Supabase"""
    
    def __init__(self, data_retriever: TourDataRetriever):
        self.data_retriever = data_retriever
    
    async def create_driver_route(self, driver_id: str, target_date: str, 
                                stops_count: int = 0) -> str:
        """
        Crée une nouvelle driver_route en base
        
        Args:
            driver_id: ID du chauffeur
            target_date: Date de la tournée (format YYYY-MM-DD)
            stops_count: Nombre de stops (pour logs)
            
        Returns:
            str: ID de la route créée
            
        Raises:
            RouteCreationError: Si erreur lors de la création
        """
        logger.info("Creating driver route", 
                   driver_id=driver_id, 
                   date=target_date,
                   stops_count=stops_count)
        
        try:
            route_data = {
                "driver_id": driver_id,
                "date": target_date,
                "status": "pending",  # Statut initial
                "estimated_duration": None,  # Calculé après optimisation
                "total_distance_km": None,   # Calculé après optimisation
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "polyline": ""  # Vide initialement
            }
            
            route_id = await self.data_retriever.create_driver_route(route_data)
            
            logger.info("Driver route created successfully", 
                       route_id=route_id,
                       driver_id=driver_id)
            
            return route_id
            
        except Exception as e:
            logger.error("Error creating driver route", 
                        driver_id=driver_id, 
                        error=str(e))
            raise RouteCreationError(f"Erreur lors de la création de la route pour le chauffeur {driver_id}: {str(e)}")
    
    async def create_route_stops(self, route_id: str, consolidated_stops: Dict[str, Dict]) -> Dict[str, str]:
        """
        Crée tous les driver_route_stops pour une route
        
        Args:
            route_id: ID de la route
            consolidated_stops: Stops consolidés depuis StopConsolidator
            
        Returns:
            Dict[str, str]: Map {stop_key: stop_id} pour les shipments
            
        Raises:
            RouteCreationError: Si erreur lors de la création
        """
        logger.info("Creating route stops", 
                   route_id=route_id, 
                   stops_count=len(consolidated_stops))
        
        try:
            # Convertir les stops en liste et mélanger l'ordre (ordre aléatoire)
            stops_list = list(consolidated_stops.items())
            randomized_stops = self._randomize_stop_order(stops_list)
            
            stops_map = {}  # stop_key -> stop_id
            
            for order, (stop_key, stop_data) in enumerate(randomized_stops, 1):
                # Préparer les données du stop
                stop_record = {
                    "route_id": route_id,
                    "location_id": stop_data["location_id"],
                    "stop_order": order,
                    "stop_type": stop_data["stop_type"],
                    "client_actions": stop_data.get("client_actions"),
                    "is_shared_pickup_stop": stop_data.get("is_shared_pickup_stop", False),
                    "estimated_arrival_time": None,    # Calculé après optimisation
                    "estimated_departure_time": None,  # Calculé après optimisation
                    "distance_from_previous": None,    # Calculé après optimisation
                    "duration_from_previous": None,    # Calculé après optimisation
                    "completed": False,
                    "arrival_time": None,
                    "is_late_stop": False,
                    "created_at": datetime.now().isoformat()
                }
                
                # Créer le stop en base
                stop_id = await self.data_retriever.create_route_stop(stop_record)
                stops_map[stop_key] = stop_id
                
                # Debug pour les lab stops
                if stop_data["stop_type"] in ["lab_pickup", "lab_dropoff"]:
                    logger.debug("Lab stop mapping created", 
                               stop_key=stop_key,
                               stop_id=stop_id,
                               stop_type=stop_data["stop_type"],
                               location_id=stop_data["location_id"])
                
                logger.debug("Route stop created", 
                           stop_id=stop_id,
                           stop_type=stop_data["stop_type"],
                           location_id=stop_data["location_id"],
                           order=order)
            
            logger.info("All route stops created successfully", 
                       route_id=route_id,
                       total_stops=len(stops_map))
            
            return stops_map
            
        except Exception as e:
            logger.error("Error creating route stops", 
                        route_id=route_id, 
                        error=str(e))
            raise RouteCreationError(f"Erreur lors de la création des stops pour la route {route_id}: {str(e)}")
    
    def _randomize_stop_order(self, stops_list: List[tuple]) -> List[tuple]:
        """
        Mélange l'ordre des stops (ordre aléatoire pour génération non-optimisée)
        
        Args:
            stops_list: Liste des (stop_key, stop_data)
            
        Returns:
            List[tuple]: Stops dans un ordre aléatoire
        """
        logger.debug("Randomizing stop order", original_count=len(stops_list))
        
        # Créer une copie pour éviter de modifier l'original
        randomized = stops_list.copy()
        random.shuffle(randomized)
        
        logger.debug("Stop order randomized", 
                    first_stop_type=randomized[0][1]["stop_type"] if randomized else None)
        
        return randomized
    
    async def update_route_status(self, route_id: str, status: str) -> bool:
        """
        Met à jour le statut d'une route
        
        Args:
            route_id: ID de la route
            status: Nouveau statut ("pending", "optimized", etc.)
            
        Returns:
            bool: True si succès
            
        Raises:
            RouteCreationError: Si erreur lors de la mise à jour
        """
        logger.info("Updating route status", route_id=route_id, status=status)
        
        try:
            update_data = {
                "status": status,
                "updated_at": datetime.now().isoformat()
            }
            
            # Utiliser la méthode update du data_retriever
            # Note: Il faudra l'implémenter si elle n'existe pas
            result = self.data_retriever.supabase.update(
                "driver_routes", 
                update_data, 
                id=route_id
            )
            
            if result["status"] != "success":
                raise RouteCreationError(f"Erreur lors de la mise à jour du statut: {result['message']}")
            
            logger.info("Route status updated successfully", 
                       route_id=route_id, 
                       new_status=status)
            
            return True
            
        except Exception as e:
            logger.error("Error updating route status", 
                        route_id=route_id, 
                        status=status,
                        error=str(e))
            raise RouteCreationError(f"Erreur lors de la mise à jour du statut de la route {route_id}: {str(e)}")
    
    def get_route_summary(self, route_id: str, driver_name: str, stops_count: int) -> Dict:
        """
        Génère un résumé de la route créée
        
        Args:
            route_id: ID de la route
            driver_name: Nom du chauffeur
            stops_count: Nombre de stops
            
        Returns:
            Dict: Résumé de la route pour la réponse API
        """
        return {
            "tour_id": route_id,
            "status": "pending",
            "stops_count": stops_count,
            "driver_name": driver_name,
            "estimated_duration": None  # Sera calculé après optimisation
        }