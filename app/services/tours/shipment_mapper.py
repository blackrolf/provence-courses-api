"""
Service de mapping des shipments vers les stops pour les tournées
"""

import structlog
from datetime import datetime
from typing import List, Dict
from app.services.tours.data_retriever import TourDataRetriever
from .exceptions import ShipmentMappingError

logger = structlog.get_logger()


class ShipmentMapper:
    """Service de mapping des shipments vers les driver_route_shipments"""
    
    def __init__(self, data_retriever: TourDataRetriever):
        self.data_retriever = data_retriever
    
    async def create_route_shipments(self, route_id: str, shipments: List[Dict], 
                                   stops_map: Dict[str, str], consolidated_stops: Dict[str, Dict]) -> List[str]:
        """
        Crée tous les driver_route_shipments pour une route
        
        Args:
            route_id: ID de la route
            shipments: Liste des shipments sources
            stops_map: Map {stop_key: stop_id} depuis RouteGenerator
            consolidated_stops: Stops consolidés pour retrouver les relations
            
        Returns:
            List[str]: Liste des IDs des shipments créés
            
        Raises:
            ShipmentMappingError: Si erreur lors du mapping
        """
        logger.info("Creating route shipments", 
                   route_id=route_id, 
                   shipments_count=len(shipments))
        
        try:
            created_shipment_ids = []
            
            for shipment in shipments:
                # Déterminer les stops pickup et delivery pour ce shipment
                stop_mapping = self._map_shipment_to_stops(shipment, stops_map, consolidated_stops)
                
                if not stop_mapping:
                    logger.warning("No stop mapping found for shipment", 
                                 shipment_id=shipment["id"])
                    continue
                
                # Déterminer le type de shipment pour driver_route_shipments
                driver_shipment_type = self._determine_shipment_type(shipment)
                
                # Déterminer si c'est un shared pickup
                is_shared_pickup = self._is_shared_pickup_shipment(shipment, stop_mapping, consolidated_stops)
                
                # Préparer les données du shipment
                shipment_data = {
                    "route_id": route_id,
                    "shipment_ref": self._generate_shipment_reference(shipment),
                    "laboratory_id": shipment["laboratory_id"],
                    "laboratory_client_id": shipment["client_id"],
                    "pickup_stop_id": stop_mapping["pickup_stop_id"],
                    "delivery_stop_id": stop_mapping["delivery_stop_id"],
                    "shipment_type": driver_shipment_type,
                    "pickup_time": None,
                    "delivery_time": None,
                    "pickup_status": "pending",
                    "delivery_status": "pending",
                    "unexpected": False,
                    "is_late_shipment": False,
                    "is_shared_pickup": is_shared_pickup,
                    "issue_type": None,
                    "issue_description": None,
                    "proof_photo_url": None,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat()
                }
                
                # Créer le shipment en base
                shipment_id = await self.data_retriever.create_route_shipment(shipment_data)
                created_shipment_ids.append(shipment_id)
                
                logger.debug("Route shipment created", 
                           shipment_id=shipment_id,
                           original_shipment_id=shipment["id"],
                           type=driver_shipment_type)
            
            logger.info("All route shipments created successfully", 
                       route_id=route_id,
                       total_shipments=len(created_shipment_ids))
            
            return created_shipment_ids
            
        except Exception as e:
            logger.error("Error creating route shipments", 
                        route_id=route_id, 
                        error=str(e))
            raise ShipmentMappingError(f"Erreur lors du mapping des shipments pour la route {route_id}: {str(e)}")
    
    def _transform_shipment_type_for_mika_logic(self, shipment: Dict) -> str:
        """
        Transforme le shipment_type basé sur les flags depot_is_dentist et depot_is_lab
        
        Args:
            shipment: Shipment avec les flags depot_is_dentist et depot_is_lab
            
        Returns:
            str: Le shipment_type transformé
        """
        original_type = shipment.get("shipment_type")
        depot_is_dentist = shipment.get("depot_is_dentist", False)
        depot_is_lab = shipment.get("depot_is_lab", False)
        
        # Si depot_is_dentist = True (Mika is dentist - le dépôt remplace le dentiste)
        if depot_is_dentist:
            if original_type == "lab_to_client":
                # Livraison : Lab → Client devient Lab → Dépôt
                return "lab_to_depot"
            elif original_type == "client_to_lab":
                # Récupération : Client → Lab devient Dépôt → Lab
                return "depot_to_lab"
        
        # Si depot_is_lab = True (Mika is lab - le dépôt remplace le laboratoire)
        if depot_is_lab:
            if original_type == "lab_to_client":
                # Livraison : Lab → Client devient Dépôt → Client
                return "depot_to_client"
            elif original_type == "client_to_lab":
                # Récupération : Client → Lab devient Client → Dépôt
                return "client_to_depot"
        
        # Pas de transformation nécessaire
        return original_type
    
    def _map_shipment_to_stops(self, shipment: Dict, stops_map: Dict[str, str], 
                              consolidated_stops: Dict[str, Dict]) -> Dict:
        """
        Trouve les stops pickup et delivery pour un shipment
        
        Args:
            shipment: Shipment source
            stops_map: Map {stop_key: stop_id}
            consolidated_stops: Stops consolidés
            
        Returns:
            Dict: {pickup_stop_id, delivery_stop_id} ou None si non trouvé
        """
        # Transformer le shipment_type selon la logique Mika
        shipment_type = self._transform_shipment_type_for_mika_logic(shipment)
        from_location_id = shipment["from_location_id"]
        to_location_id = shipment["to_location_id"]
        lab_id = shipment["laboratory_id"]
        
        pickup_stop_id = None
        delivery_stop_id = None
        
        # Mapping selon le type de shipment
        if shipment_type == "depot_to_client":
            # Pickup: depot_pickup, Delivery: client stop delivery
            pickup_stop_id = stops_map.get("depot_pickup")
            delivery_stop_id = self._find_client_stop_id(to_location_id, "delivery", stops_map, lab_id)
            
        elif shipment_type == "depot_to_lab":
            # Pickup: depot_pickup, Delivery: lab_dropoff
            pickup_stop_id = stops_map.get("depot_pickup")
            delivery_stop_id = stops_map.get(f"lab_dropoff_{lab_id}")
            
        elif shipment_type == "lab_to_client":
            # Pickup: lab_pickup, Delivery: client stop delivery
            pickup_stop_id = stops_map.get(f"lab_pickup_{lab_id}")
            delivery_stop_id = self._find_client_stop_id(to_location_id, "delivery", stops_map, lab_id)
            
        elif shipment_type == "lab_to_depot":
            # Pickup: lab_pickup, Delivery: depot_dropoff
            pickup_stop_id = stops_map.get(f"lab_pickup_{lab_id}")
            delivery_stop_id = stops_map.get("depot_dropoff")
            
        elif shipment_type == "client_to_lab":
            # Pickup: client stop pickup, Delivery: lab_dropoff
            pickup_stop_id = self._find_client_stop_id(from_location_id, "pickup", stops_map, lab_id)
            delivery_stop_id = stops_map.get(f"lab_dropoff_{lab_id}")
            
        elif shipment_type == "client_to_depot":
            # Pickup: client stop pickup, Delivery: depot_dropoff
            depot_lab_id = "DEPOT"  # Special lab_id for depot shipments
            pickup_stop_id = self._find_client_stop_id(from_location_id, "pickup", stops_map, depot_lab_id)
            delivery_stop_id = stops_map.get("depot_dropoff")
        
        if not pickup_stop_id or not delivery_stop_id:
            logger.warning("Could not map shipment to stops", 
                          shipment_type=shipment_type,
                          shipment_id=shipment["id"],
                          pickup_found=pickup_stop_id is not None,
                          delivery_found=delivery_stop_id is not None)
            return None
        
        return {
            "pickup_stop_id": pickup_stop_id,
            "delivery_stop_id": delivery_stop_id
        }
    
    def _find_client_stop_id(self, location_id: str, action: str, stops_map: Dict[str, str], lab_id: str = None) -> str:
        """
        Trouve l'ID du stop client pour une location et action données
        
        Args:
            location_id: ID de la location du client
            action: "pickup" ou "delivery"
            stops_map: Map des stops
            lab_id: ID du laboratoire (requis pour le nouveau format)
            
        Returns:
            str: stop_id ou None si non trouvé
        """
        if lab_id:
            # Nouveau format avec lab_id
            stop_key = f"client_{location_id}_{action}_{lab_id}"
        else:
            # Ancien format pour compatibilité (ne devrait plus être utilisé)
            stop_key = f"client_{location_id}_{action}"
        
        return stops_map.get(stop_key)
    
    def _determine_shipment_type(self, shipment: Dict) -> str:
        """
        Détermine le type de shipment pour driver_route_shipments
        
        Args:
            shipment: Shipment source enrichi avec has_pickup/has_delivery
            
        Returns:
            str: "client_pickup" ou "client_delivery"
        """
        # Transformer le shipment_type selon la logique Mika
        shipment_type = self._transform_shipment_type_for_mika_logic(shipment)
        
        # Les shipments qui impliquent directement une livraison client
        if shipment_type in ["depot_to_client", "lab_to_client"]:
            return "client_delivery"
        
        # Les shipments qui impliquent directement une récupération client
        elif shipment_type in ["client_to_depot", "client_to_lab"]:
            return "client_pickup"
        
        # Pour depot_to_lab et lab_to_depot, utiliser les infos du lab_tour_stop
        elif shipment_type in ["depot_to_lab", "lab_to_depot"]:
            has_pickup = shipment.get("has_pickup", False)
            has_delivery = shipment.get("has_delivery", False)
            
            # Logique métier : si le client a un pickup -> récupération, sinon livraison
            if has_pickup and not has_delivery:
                return "client_pickup"
            elif has_delivery and not has_pickup:
                return "client_delivery"
            elif has_pickup and has_delivery:
                # Les deux : prioriser selon le type de shipment
                if shipment_type == "depot_to_lab":
                    return "client_pickup"  # Transport vers labo = récupération
                else:  # lab_to_depot
                    return "client_delivery"  # Transport depuis labo = livraison
            else:
                # Aucun flag : fallback sur l'ancien comportement
                return "client_delivery"
        
        # Fallback pour types non gérés
        else:
            return "client_delivery"
    
    def _is_shared_pickup_shipment(self, shipment: Dict, stop_mapping: Dict, 
                                  consolidated_stops: Dict[str, Dict]) -> bool:
        """
        Détermine si ce shipment utilise un shared pickup
        
        Args:
            shipment: Shipment source
            stop_mapping: Mapping des stops pour ce shipment
            consolidated_stops: Stops consolidés
            
        Returns:
            bool: True si shared pickup
        """
        pickup_stop_id = stop_mapping["pickup_stop_id"]
        
        # Trouver le stop consolidé correspondant
        for stop_key, stop_data in consolidated_stops.items():
            if stop_data.get("related_shipments") and shipment["id"] in stop_data["related_shipments"]:
                return stop_data.get("is_shared_pickup_stop", False)
        
        return False
    
    def _generate_shipment_reference(self, shipment: Dict) -> str:
        """
        Génère une référence lisible pour le shipment
        
        Args:
            shipment: Shipment source
            
        Returns:
            str: Référence du shipment selon la logique métier SIMPLE :
            - "Livraison [Labo] [Client]" si shipment_type = client_delivery  
            - "Récupération [Labo] [Client]" si shipment_type = client_pickup
        """
        client_name = shipment.get("client_name", "Client")
        lab_name = shipment.get("laboratory_name", "Labo")
        
        # Utiliser directement le driver_route_shipment_type déterminé précédemment
        driver_shipment_type = self._determine_shipment_type(shipment)
        
        if driver_shipment_type == "client_delivery":
            return f"Livraison {lab_name} {client_name}"
        elif driver_shipment_type == "client_pickup":
            return f"Récupération {lab_name} {client_name}"
        else:
            # Fallback - ne devrait pas arriver avec la logique actuelle
            return f"Transport {lab_name} {client_name}"