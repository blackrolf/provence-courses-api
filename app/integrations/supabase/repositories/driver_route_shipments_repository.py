"""
Repository pour la gestion des driver_route_shipments
"""

import structlog
from typing import Dict, List, Optional, Any
from datetime import datetime
from ..base_client import SupabaseBaseClient

logger = structlog.get_logger()


class DriverRouteShipmentsRepository:
    """Repository pour les opérations sur driver_route_shipments"""
    
    def __init__(self, client: SupabaseBaseClient):
        self.client = client
    
    def get_shipments_by_route_id(self, route_id: str) -> Dict[str, Any]:
        """
        Récupère tous les shipments d'une route
        
        Args:
            route_id: ID de la route
            
        Returns:
            Dict: Shipments ou erreur
        """
        logger.debug("Getting driver route shipments by route ID", route_id=route_id)
        
        return self.client.select(
            "driver_route_shipments",
            "*",
            route_id=f"eq.{route_id}"
        )
    
    def get_shipment_by_id(self, shipment_id: str) -> Dict[str, Any]:
        """
        Récupère un shipment par son ID
        
        Args:
            shipment_id: ID du shipment
            
        Returns:
            Dict: Shipment ou erreur
        """
        logger.debug("Getting driver route shipment by ID", shipment_id=shipment_id)
        
        return self.client.select(
            "driver_route_shipments",
            "*",
            id=shipment_id
        )
    
    def create_shipment(self, shipment_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Crée un nouveau shipment de route
        
        Args:
            shipment_data: Données du shipment
            
        Returns:
            Dict: Shipment créé ou erreur
        """
        logger.debug("Creating driver route shipment", 
                    route_id=shipment_data.get("route_id"),
                    shipment_type=shipment_data.get("shipment_type"))
        
        # Ajouter les timestamps si pas présents
        if "created_at" not in shipment_data:
            shipment_data["created_at"] = datetime.now().isoformat()
        if "updated_at" not in shipment_data:
            shipment_data["updated_at"] = datetime.now().isoformat()
        
        return self.client.insert("driver_route_shipments", shipment_data)
    
    def create_multiple_shipments(self, shipments_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Crée plusieurs shipments en une fois
        
        Args:
            shipments_data: Liste des données de shipments
            
        Returns:
            Dict: Résultat de la création
        """
        logger.info("Creating multiple driver route shipments", count=len(shipments_data))
        
        try:
            created_shipments = []
            failed_shipments = []
            
            for shipment_data in shipments_data:
                result = self.create_shipment(shipment_data)
                if result["status"] == "success":
                    created_shipments.extend(result["data"])
                else:
                    failed_shipments.append({
                        "shipment_data": shipment_data,
                        "error": result["message"]
                    })
            
            if failed_shipments:
                logger.warning("Some shipments failed to create", 
                             failed_count=len(failed_shipments))
                return {
                    "status": "partial_success",
                    "message": f"{len(created_shipments)} shipments créés, {len(failed_shipments)} échecs",
                    "data": created_shipments,
                    "failed": failed_shipments
                }
            
            return {
                "status": "success",
                "message": f"{len(created_shipments)} shipments créés",
                "data": created_shipments
            }
            
        except Exception as e:
            logger.error("Error creating multiple shipments", error=str(e))
            return {
                "status": "error",
                "message": f"Erreur lors de la création des shipments: {str(e)}"
            }
    
    def update_shipment_pickup_status(self, shipment_id: str, pickup_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Met à jour le statut de pickup d'un shipment
        
        Args:
            shipment_id: ID du shipment
            pickup_data: Données de pickup (status, time, proof, etc.)
            
        Returns:
            Dict: Shipment mis à jour ou erreur
        """
        logger.info("Updating shipment pickup status", shipment_id=shipment_id)
        
        update_data = {
            **pickup_data,
            "updated_at": datetime.now().isoformat()
        }
        
        return self.client.update(
            "driver_route_shipments",
            update_data,
            id=shipment_id
        )
    
    def update_shipment_delivery_status(self, shipment_id: str, delivery_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Met à jour le statut de delivery d'un shipment
        
        Args:
            shipment_id: ID du shipment
            delivery_data: Données de delivery (status, time, proof, etc.)
            
        Returns:
            Dict: Shipment mis à jour ou erreur
        """
        logger.info("Updating shipment delivery status", shipment_id=shipment_id)
        
        update_data = {
            **delivery_data,
            "updated_at": datetime.now().isoformat()
        }
        
        return self.client.update(
            "driver_route_shipments",
            update_data,
            id=shipment_id
        )
    
    def get_shipments_by_stop_id(self, stop_id: str, pickup_or_delivery: str = "both") -> Dict[str, Any]:
        """
        Récupère les shipments associés à un stop
        
        Args:
            stop_id: ID du stop
            pickup_or_delivery: "pickup", "delivery", ou "both"
            
        Returns:
            Dict: Shipments ou erreur
        """
        logger.debug("Getting shipments by stop ID", 
                    stop_id=stop_id, 
                    pickup_or_delivery=pickup_or_delivery)
        
        try:
            if pickup_or_delivery == "pickup":
                return self.client.select(
                    "driver_route_shipments",
                    "*",
                    pickup_stop_id=f"eq.{stop_id}"
                )
            elif pickup_or_delivery == "delivery":
                return self.client.select(
                    "driver_route_shipments",
                    "*",
                    delivery_stop_id=f"eq.{stop_id}"
                )
            else:  # both
                # Récupérer les deux et les combiner
                pickup_result = self.client.select(
                    "driver_route_shipments",
                    "*",
                    pickup_stop_id=f"eq.{stop_id}"
                )
                
                delivery_result = self.client.select(
                    "driver_route_shipments",
                    "*",
                    delivery_stop_id=f"eq.{stop_id}"
                )
                
                if pickup_result["status"] != "success":
                    return pickup_result
                
                if delivery_result["status"] != "success":
                    return delivery_result
                
                # Combiner et dédupliquer
                all_shipments = pickup_result["data"] + delivery_result["data"]
                unique_shipments = []
                seen_ids = set()
                
                for shipment in all_shipments:
                    if shipment["id"] not in seen_ids:
                        unique_shipments.append(shipment)
                        seen_ids.add(shipment["id"])
                
                return {
                    "status": "success",
                    "data": unique_shipments
                }
                
        except Exception as e:
            logger.error("Error getting shipments by stop ID", error=str(e))
            return {
                "status": "error",
                "message": f"Erreur lors de la récupération des shipments: {str(e)}"
            }
    
    def get_shipments_by_laboratory_client_id(self, lab_client_id: str) -> Dict[str, Any]:
        """
        Récupère les shipments d'un client de laboratoire
        
        Args:
            lab_client_id: ID du client de laboratoire
            
        Returns:
            Dict: Shipments ou erreur
        """
        logger.debug("Getting shipments by laboratory client ID", lab_client_id=lab_client_id)
        
        return self.client.select(
            "driver_route_shipments",
            "*",
            laboratory_client_id=f"eq.{lab_client_id}"
        )
    
    def mark_shipment_as_unexpected(self, shipment_id: str, issue_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Marque un shipment comme inattendu/problématique
        
        Args:
            shipment_id: ID du shipment
            issue_data: Données sur le problème (optionnel)
            
        Returns:
            Dict: Shipment mis à jour ou erreur
        """
        logger.info("Marking shipment as unexpected", shipment_id=shipment_id)
        
        update_data = {
            "unexpected": True,
            "updated_at": datetime.now().isoformat()
        }
        
        if issue_data:
            update_data.update(issue_data)
        
        return self.client.update(
            "driver_route_shipments",
            update_data,
            id=shipment_id
        )
    
    def update_shipment_stop_references(self, shipment_id: str, stop_references: Dict[str, Any]) -> Dict[str, Any]:
        """
        Met à jour les références de stops d'un shipment (pickup_stop_id, delivery_stop_id)
        
        Args:
            shipment_id: ID du shipment
            stop_references: Nouvelles références de stops
            
        Returns:
            Dict: Shipment mis à jour ou erreur
        """
        logger.debug("Updating shipment stop references", 
                    shipment_id=shipment_id,
                    references=stop_references)
        
        update_data = {
            **stop_references,
            "updated_at": datetime.now().isoformat()
        }
        
        return self.client.update(
            "driver_route_shipments",
            update_data,
            id=shipment_id
        )