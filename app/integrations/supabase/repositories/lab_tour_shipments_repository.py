"""
Repository pour la gestion des lab_tour_shipments
"""

import structlog
from typing import Dict, List, Optional, Any
from collections import defaultdict
from ..base_client import SupabaseBaseClient

logger = structlog.get_logger()


class LabTourShipmentsRepository:
    """Repository pour les opérations sur lab_tour_shipments"""
    
    def __init__(self, client: SupabaseBaseClient):
        self.client = client
    
    def get_shipments_by_date(self, date: str) -> Dict[str, Any]:
        """
        Récupère tous les shipments d'une date
        
        Args:
            date: Date au format YYYY-MM-DD
            
        Returns:
            Dict: Shipments ou erreur
        """
        logger.debug("Getting lab tour shipments by date", date=date)
        
        return self.client.select(
            "lab_tour_shipments",
            "*",
            scheduled_date=f"eq.{date}"
        )
    
    def get_enriched_shipments_by_date(self, date: str) -> Dict[str, Any]:
        """
        Récupère les shipments enrichis avec données clients et laboratoires
        
        Cette méthode décompose les JOINs complexes en plusieurs requêtes
        
        Args:
            date: Date au format YYYY-MM-DD
            
        Returns:
            Dict: Shipments enrichis
        """
        logger.info("Getting enriched shipments", date=date)
        
        try:
            # 1. Récupérer les shipments de base
            shipments_result = self.get_shipments_by_date(date)
            
            if shipments_result["status"] != "success":
                return shipments_result
            
            shipments = shipments_result["data"]
            
            if not shipments:
                return {
                    "status": "success",
                    "data": []
                }
            
            # 2. Récupérer tous les clients concernés
            client_ids = list(set(ship["client_id"] for ship in shipments if ship.get("client_id")))
            
            if not client_ids:
                logger.warning("No client IDs found in shipments")
                return {
                    "status": "success",
                    "data": []
                }
            
            # Récupérer les clients par batch si nécessaire
            clients_result = self.client.select("laboratory_clients", "*")
            
            if clients_result["status"] != "success":
                return clients_result
            
            # Filtrer les clients concernés
            all_clients = clients_result["data"]
            clients_map = {
                client["id"]: client 
                for client in all_clients
                if client["id"] in client_ids
            }
            
            # 3. Récupérer tous les laboratoires concernés
            lab_ids = list(set(
                client["laboratory_id"] 
                for client in clients_map.values() 
                if client.get("laboratory_id")
            ))
            
            if not lab_ids:
                logger.warning("No laboratory IDs found in clients")
                return {
                    "status": "success", 
                    "data": []
                }
            
            labs_result = self.client.select("laboratories", "*")
            
            if labs_result["status"] != "success":
                return labs_result
            
            # Filtrer les laboratoires concernés
            all_labs = labs_result["data"]
            labs_map = {
                lab["id"]: lab 
                for lab in all_labs
                if lab["id"] in lab_ids
            }
            
            # 4. Récupérer les lab_tour_stops pour déterminer pickup/delivery
            # Récupérer tous les lab_tour_stops pour la date
            stops_result = self.client.select("lab_tour_stops", "*")
            
            if stops_result["status"] == "success":
                # Créer un map des stops par (tour_id, client_id)
                stops_map = {}
                for stop in stops_result["data"]:
                    key = (stop.get("tour_id"), stop.get("client_id"))
                    stops_map[key] = stop
                logger.debug("Lab tour stops loaded", stops_count=len(stops_map))
            else:
                logger.warning("Failed to load lab_tour_stops", error=stops_result.get("message"))
                stops_map = {}
            
            # 5. Enrichir les shipments
            enriched_shipments = []
            
            for shipment in shipments:
                client_id = shipment.get("client_id")
                if not client_id:
                    logger.warning("Shipment without client_id", shipment_id=shipment.get("id"))
                    continue
                
                client = clients_map.get(client_id)
                if not client:
                    logger.warning("Client not found", client_id=client_id)
                    continue
                
                lab_id = client.get("laboratory_id")
                if not lab_id:
                    logger.warning("Client without laboratory_id", client_id=client_id)
                    continue
                
                lab = labs_map.get(lab_id)
                if not lab:
                    logger.warning("Laboratory not found", lab_id=lab_id)
                    continue
                
                # Récupérer les infos de stop pour ce shipment
                lab_tour_id = shipment.get("lab_tour_id")
                stop_key = (lab_tour_id, client_id)
                stop_data = stops_map.get(stop_key, {})
                
                enriched_shipment = {
                    **shipment,
                    "driver_id": client.get("driver_id"),
                    "client_location_id": client.get("location_id"),
                    "laboratory_id": lab_id,
                    "client_name": client.get("name"),
                    "shared_pickup": lab.get("shared_pickup", False),
                    "depot_is_lab": lab.get("depot_is_lab", False),
                    "depot_is_dentist": client.get("depot_is_dentist", False),  # Ajout du flag depot_is_dentist depuis le client
                    "laboratory_name": lab.get("name"),
                    # Nouveaux champs pour déterminer récupération vs livraison
                    "has_pickup": stop_data.get("has_pickup", False),
                    "has_delivery": stop_data.get("has_delivery", False)
                }
                
                enriched_shipments.append(enriched_shipment)
            
            logger.info("Shipments enriched successfully", 
                       original_count=len(shipments),
                       enriched_count=len(enriched_shipments))
            
            return {
                "status": "success",
                "data": enriched_shipments
            }
            
        except Exception as e:
            logger.error("Error enriching shipments", error=str(e))
            return {
                "status": "error",
                "message": f"Erreur lors de l'enrichissement des shipments: {str(e)}"
            }
    
    def get_shipments_by_client_id(self, client_id: str, date: Optional[str] = None) -> Dict[str, Any]:
        """
        Récupère les shipments d'un client
        
        Args:
            client_id: ID du client
            date: Date optionnelle pour filtrer
            
        Returns:
            Dict: Shipments ou erreur
        """
        logger.debug("Getting shipments by client ID", client_id=client_id, date=date)
        
        filters = {"client_id": f"eq.{client_id}"}
        if date:
            filters["scheduled_date"] = f"eq.{date}"
        
        return self.client.select(
            "lab_tour_shipments",
            "*",
            **filters
        )
    
    def get_shipments_by_lab_tour_id(self, lab_tour_id: str) -> Dict[str, Any]:
        """
        Récupère les shipments d'une tournée de laboratoire
        
        Args:
            lab_tour_id: ID de la tournée de laboratoire
            
        Returns:
            Dict: Shipments ou erreur
        """
        logger.debug("Getting shipments by lab tour ID", lab_tour_id=lab_tour_id)
        
        return self.client.select(
            "lab_tour_shipments",
            "*",
            lab_tour_id=f"eq.{lab_tour_id}"
        )
    
    def get_shipments_statistics_by_date(self, date: str) -> Dict[str, Any]:
        """
        Récupère des statistiques sur les shipments d'une date
        
        Args:
            date: Date au format YYYY-MM-DD
            
        Returns:
            Dict: Statistiques ou erreur
        """
        logger.debug("Getting shipments statistics", date=date)
        
        try:
            shipments_result = self.get_shipments_by_date(date)
            
            if shipments_result["status"] != "success":
                return shipments_result
            
            shipments = shipments_result["data"]
            
            # Calculer les statistiques
            stats = {
                "total_shipments": len(shipments),
                "by_type": defaultdict(int),
                "unique_clients": set(),
                "unique_lab_tours": set()
            }
            
            for shipment in shipments:
                # Compter par type
                shipment_type = shipment.get("shipment_type", "unknown")
                stats["by_type"][shipment_type] += 1
                
                # Compter les clients uniques
                if shipment.get("client_id"):
                    stats["unique_clients"].add(shipment["client_id"])
                
                # Compter les tournées de lab uniques
                if shipment.get("lab_tour_id"):
                    stats["unique_lab_tours"].add(shipment["lab_tour_id"])
            
            # Convertir les sets en counts
            stats["unique_clients_count"] = len(stats["unique_clients"])
            stats["unique_lab_tours_count"] = len(stats["unique_lab_tours"])
            del stats["unique_clients"]
            del stats["unique_lab_tours"]
            
            # Convertir defaultdict en dict normal
            stats["by_type"] = dict(stats["by_type"])
            
            return {
                "status": "success",
                "data": stats
            }
            
        except Exception as e:
            logger.error("Error calculating shipments statistics", error=str(e))
            return {
                "status": "error",
                "message": f"Erreur lors du calcul des statistiques: {str(e)}"
            }