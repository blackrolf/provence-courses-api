"""
Service de consolidation des stops pour la génération de tournées
"""

import structlog
from typing import List, Dict, Set
from collections import defaultdict
from .exceptions import TourGenerationError
from .depot_location_service import get_depot_location_id

logger = structlog.get_logger()


class StopConsolidator:
    """Service de consolidation des stops par type pour un driver"""
    
    def __init__(self):
        pass
    
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
    
    def consolidate_stops_for_driver(self, shipments: List[Dict], locations_map: Dict[str, Dict], lab_location_map: Dict[str, str] = None) -> Dict[str, Dict]:
        """
        Consolide les stops par type pour un driver
        
        Args:
            shipments: Liste des shipments du driver
            locations_map: Map des locations (id -> data)
            lab_location_map: Map laboratory_id -> location_id (pour corriger le mapping)
            
        Returns:
            Dict[str, Dict]: Map des stops consolidés {stop_key: stop_data}
            
        Raises:
            TourGenerationError: Si erreur lors de la consolidation
        """
        logger.info("Consolidating stops for driver", shipments_count=len(shipments))
        
        try:
            consolidated_stops = {}
            
            # Grouper les shipments par type d'action
            depot_pickup_shipments = []
            depot_dropoff_shipments = []
            lab_pickup_groups = defaultdict(list)  # lab_id -> shipments
            lab_dropoff_groups = defaultdict(list)  # lab_id -> shipments
            client_action_groups = defaultdict(list)  # (location_id, action, lab_id) -> shipments
            
            for shipment in shipments:
                # Transformer le shipment_type selon la logique Mika
                original_shipment_type = shipment["shipment_type"]
                shipment_type = self._transform_shipment_type_for_mika_logic(shipment)
                
                # Logger si une transformation a eu lieu
                if shipment_type != original_shipment_type:
                    logger.debug("Shipment type transformed for Mika logic",
                                original_type=original_shipment_type,
                                transformed_type=shipment_type,
                                depot_is_dentist=shipment.get("depot_is_dentist", False),
                                depot_is_lab=shipment.get("depot_is_lab", False),
                                laboratory_id=shipment.get("laboratory_id"))
                
                from_location_id = shipment["from_location_id"]
                to_location_id = shipment["to_location_id"]
                
                # Analyser le type de shipment pour déterminer les stops nécessaires
                if shipment_type == "depot_to_client":
                    depot_pickup_shipments.append(shipment)
                    # Client delivery - pour les shipments directs du dépôt, utiliser "DEPOT" comme lab_id
                    # Si le shipment a un laboratory_id défini, l'utiliser, sinon utiliser "DEPOT"
                    lab_id = shipment.get("laboratory_id") or "DEPOT"
                    client_action_groups[(to_location_id, "delivery", lab_id)].append(shipment)
                    
                elif shipment_type == "depot_to_lab":
                    depot_pickup_shipments.append(shipment)
                    # Lab dropoff
                    lab_dropoff_groups[shipment["laboratory_id"]].append(shipment)
                    
                elif shipment_type == "lab_to_client":
                    # Lab pickup
                    lab_pickup_groups[shipment["laboratory_id"]].append(shipment)
                    # Client delivery - grouper par laboratoire d'origine
                    lab_id = shipment["laboratory_id"]
                    client_action_groups[(to_location_id, "delivery", lab_id)].append(shipment)
                    
                elif shipment_type == "lab_to_depot":
                    # Lab pickup
                    lab_pickup_groups[shipment["laboratory_id"]].append(shipment)
                    depot_dropoff_shipments.append(shipment)
                    
                elif shipment_type == "client_to_lab":
                    # Client pickup - grouper par laboratoire de destination
                    lab_id = shipment["laboratory_id"]
                    client_action_groups[(from_location_id, "pickup", lab_id)].append(shipment)
                    # Lab dropoff
                    lab_dropoff_groups[shipment["laboratory_id"]].append(shipment)
                    
                elif shipment_type == "client_to_depot":
                    # Client pickup - utiliser un lab_id spécial pour le dépôt
                    depot_lab_id = "DEPOT"
                    client_action_groups[(from_location_id, "pickup", depot_lab_id)].append(shipment)
                    depot_dropoff_shipments.append(shipment)
            
            # Créer les stops consolidés
            
            # 1. Depot pickup (1 seul par tournée)
            if depot_pickup_shipments:
                stop_data = self._create_depot_pickup_stop(depot_pickup_shipments, locations_map)
                consolidated_stops["depot_pickup"] = stop_data
            
            # 2. Depot dropoff (1 seul par tournée)
            if depot_dropoff_shipments:
                stop_data = self._create_depot_dropoff_stop(depot_dropoff_shipments, locations_map)
                consolidated_stops["depot_dropoff"] = stop_data
            
            # 3. Lab pickups (1 par laboratoire)
            for lab_id, lab_shipments in lab_pickup_groups.items():
                logger.debug("Creating lab_pickup stop", 
                           lab_id=lab_id,
                           shipments_count=len(lab_shipments),
                           stop_key=f"lab_pickup_{lab_id}")
                stop_data = self._create_lab_pickup_stop(lab_id, lab_shipments, locations_map, lab_location_map)
                consolidated_stops[f"lab_pickup_{lab_id}"] = stop_data
            
            # 4. Lab dropoffs (1 par laboratoire)
            for lab_id, lab_shipments in lab_dropoff_groups.items():
                stop_data = self._create_lab_dropoff_stop(lab_id, lab_shipments, locations_map, lab_location_map)
                consolidated_stops[f"lab_dropoff_{lab_id}"] = stop_data
            
            # 5. Client stops (1 par location par action par laboratoire)
            for (location_id, action, lab_id), client_shipments in client_action_groups.items():
                stop_data = self._create_client_stop(location_id, action, client_shipments, locations_map, lab_id)
                consolidated_stops[f"client_{location_id}_{action}_{lab_id}"] = stop_data
            
            logger.info("Stops consolidated successfully", 
                       total_stops=len(consolidated_stops),
                       depot_pickup=1 if depot_pickup_shipments else 0,
                       depot_dropoff=1 if depot_dropoff_shipments else 0,
                       lab_pickups=len(lab_pickup_groups),
                       lab_dropoffs=len(lab_dropoff_groups),
                       client_stops=len(client_action_groups))
            
            return consolidated_stops
            
        except Exception as e:
            logger.error("Error consolidating stops", error=str(e))
            raise TourGenerationError(f"Erreur lors de la consolidation des stops: {str(e)}")
    
    def _create_depot_pickup_stop(self, shipments: List[Dict], locations_map: Dict[str, Dict]) -> Dict:
        """
        Crée un stop depot_pickup consolidé
        
        Args:
            shipments: Shipments partant du dépôt
            locations_map: Map des locations
            
        Returns:
            Dict: Stop data
        """
        # NOUVELLE LOGIQUE ROBUSTE pour trouver la location du dépôt
        depot_location_id = None
        
        # Méthode 1: Utiliser le service centralisé (NOUVEAU)
        try:
            depot_location_id = get_depot_location_id()
            logger.info("Depot location found via centralized service", 
                       location_id=depot_location_id,
                       method="depot_location_service")
        except Exception as e:
            logger.warning("Failed to get depot location from service, trying fallback", 
                          error=str(e))
        
        # Méthode 2: Fallback - ancienne logique mais améliorée (SÉCURITÉ)
        if not depot_location_id:
            # Chercher dans les shipments avec shipment_type original OU transformé
            for shipment in shipments:
                original_type = shipment.get("original_shipment_type", shipment["shipment_type"])
                current_type = shipment["shipment_type"]
                
                # Vérifier les deux types pour robustesse
                if (original_type.startswith("depot_") or 
                    current_type.startswith("depot_") or
                    original_type.endswith("_to_client") or
                    current_type.endswith("_to_client")):
                    depot_location_id = shipment["from_location_id"]
                    logger.info("Depot location found via shipment fallback", 
                               location_id=depot_location_id,
                               method="shipment_fallback",
                               original_type=original_type,
                               current_type=current_type)
                    break
        
        # Méthode 3: Fallback ultime - UUID connu en production (DERNIÈRE CHANCE)
        if not depot_location_id:
            # UUID actuellement utilisé en production selon les logs
            depot_location_id = "00d378f4-6589-48b9-8d1e-be8c1ac4bfdf"
            logger.warning("Using hardcoded depot location as ultimate fallback", 
                          location_id=depot_location_id,
                          method="hardcoded_fallback")
        
        if not depot_location_id:
            raise TourGenerationError("Impossible de déterminer la location du dépôt après tous les fallbacks")
        
        location_data = locations_map.get(depot_location_id, {})
        
        return {
            "location_id": depot_location_id,
            "stop_type": "depot_pickup",
            "client_actions": None,
            "is_shared_pickup_stop": True,  # Le dépôt est TOUJOURS un shared pickup
            "shipments_count": len(shipments),
            "location_name": location_data.get("name", "Dépôt"),
            "related_shipments": [s["id"] for s in shipments]
        }
    
    def _create_depot_dropoff_stop(self, shipments: List[Dict], locations_map: Dict[str, Dict]) -> Dict:
        """
        Crée un stop depot_dropoff consolidé
        
        Args:
            shipments: Shipments arrivant au dépôt
            locations_map: Map des locations
            
        Returns:
            Dict: Stop data
        """
        # NOUVELLE LOGIQUE ROBUSTE pour trouver la location du dépôt (même que pickup)
        depot_location_id = None
        
        # Méthode 1: Utiliser le service centralisé (NOUVEAU)
        try:
            depot_location_id = get_depot_location_id()
            logger.info("Depot location found via centralized service for dropoff", 
                       location_id=depot_location_id,
                       method="depot_location_service")
        except Exception as e:
            logger.warning("Failed to get depot location from service for dropoff, trying fallback", 
                          error=str(e))
        
        # Méthode 2: Fallback - ancienne logique mais améliorée (SÉCURITÉ)
        if not depot_location_id:
            # Chercher dans les shipments avec shipment_type original OU transformé
            for shipment in shipments:
                original_type = shipment.get("original_shipment_type", shipment["shipment_type"])
                current_type = shipment["shipment_type"]
                
                # Vérifier les deux types pour robustesse
                if (original_type.endswith("_to_depot") or 
                    current_type.endswith("_to_depot") or
                    original_type.startswith("client_") or
                    current_type.startswith("client_")):
                    depot_location_id = shipment["to_location_id"]
                    logger.info("Depot location found via shipment fallback for dropoff", 
                               location_id=depot_location_id,
                               method="shipment_fallback",
                               original_type=original_type,
                               current_type=current_type)
                    break
        
        # Méthode 3: Fallback ultime - UUID connu en production (DERNIÈRE CHANCE)
        if not depot_location_id:
            # UUID actuellement utilisé en production selon les logs
            depot_location_id = "00d378f4-6589-48b9-8d1e-be8c1ac4bfdf"
            logger.warning("Using hardcoded depot location as ultimate fallback for dropoff", 
                          location_id=depot_location_id,
                          method="hardcoded_fallback")
        
        if not depot_location_id:
            raise TourGenerationError("Impossible de déterminer la location du dépôt pour dropoff après tous les fallbacks")
        
        location_data = locations_map.get(depot_location_id, {})
        
        return {
            "location_id": depot_location_id,
            "stop_type": "depot_dropoff",
            "client_actions": None,
            "is_shared_pickup_stop": False,
            "shipments_count": len(shipments),
            "location_name": location_data.get("name", "Dépôt"),
            "related_shipments": [s["id"] for s in shipments]
        }
    
    def _create_lab_pickup_stop(self, lab_id: str, shipments: List[Dict], locations_map: Dict[str, Dict], lab_location_map: Dict[str, str] = None) -> Dict:
        """
        Crée un stop lab_pickup pour un laboratoire
        
        Args:
            lab_id: ID du laboratoire
            shipments: Shipments partant de ce laboratoire
            locations_map: Map des locations
            
        Returns:
            Dict: Stop data
        """
        # Utiliser le mapping laboratory_id -> location_id si disponible
        lab_location_id = None
        
        if lab_location_map and lab_id in lab_location_map:
            lab_location_id = lab_location_map[lab_id]
            logger.debug("Using laboratory location mapping", 
                        lab_id=lab_id, 
                        location_id=lab_location_id,
                        method="laboratory_mapping")
        else:
            # Fallback : utiliser l'ancienne logique (pour compatibilité)
            for shipment in shipments:
                if shipment["shipment_type"].startswith("lab_"):
                    lab_location_id = shipment["from_location_id"]
                    break
            logger.warning("Using fallback location mapping from shipment", 
                          lab_id=lab_id, 
                          location_id=lab_location_id,
                          method="fallback_shipment")
        
        if not lab_location_id:
            raise TourGenerationError(f"Impossible de déterminer la location du laboratoire {lab_id}")
        
        location_data = locations_map.get(lab_location_id, {})
        
        # Déterminer si c'est un shared pickup depuis les données enrichies du laboratoire
        is_shared_pickup = any(s.get("shared_pickup", False) for s in shipments)
        
        # Debug logging pour comprendre le shared pickup
        logger.debug("Lab pickup stop analysis", 
                    lab_id=lab_id,
                    shipments_count=len(shipments),
                    is_shared_pickup=is_shared_pickup,
                    shared_flags=[s.get("shared_pickup", False) for s in shipments])
        
        return {
            "location_id": lab_location_id,
            "stop_type": "lab_pickup",
            "client_actions": None,
            "is_shared_pickup_stop": is_shared_pickup,
            "shipments_count": len(shipments),
            "location_name": location_data.get("name", f"Laboratoire {lab_id}"),
            "laboratory_id": lab_id,
            "related_shipments": [s["id"] for s in shipments]
        }
    
    def _create_lab_dropoff_stop(self, lab_id: str, shipments: List[Dict], locations_map: Dict[str, Dict], lab_location_map: Dict[str, str] = None) -> Dict:
        """
        Crée un stop lab_dropoff pour un laboratoire
        
        Args:
            lab_id: ID du laboratoire
            shipments: Shipments arrivant à ce laboratoire
            locations_map: Map des locations
            
        Returns:
            Dict: Stop data
        """
        # Utiliser le mapping laboratory_id -> location_id si disponible
        lab_location_id = None
        
        if lab_location_map and lab_id in lab_location_map:
            lab_location_id = lab_location_map[lab_id]
            logger.debug("Using laboratory location mapping for dropoff", 
                        lab_id=lab_id, 
                        location_id=lab_location_id,
                        method="laboratory_mapping")
        else:
            # Fallback : utiliser l'ancienne logique (pour compatibilité)
            for shipment in shipments:
                if shipment["shipment_type"].endswith("_to_lab"):
                    lab_location_id = shipment["to_location_id"]
                    break
            logger.warning("Using fallback location mapping from shipment for dropoff", 
                          lab_id=lab_id, 
                          location_id=lab_location_id,
                          method="fallback_shipment")
        
        if not lab_location_id:
            raise TourGenerationError(f"Impossible de déterminer la location du laboratoire {lab_id} pour dropoff")
        
        location_data = locations_map.get(lab_location_id, {})
        
        return {
            "location_id": lab_location_id,
            "stop_type": "lab_dropoff",
            "client_actions": None,
            "is_shared_pickup_stop": False,  # Dropoff n'est jamais shared
            "shipments_count": len(shipments),
            "location_name": location_data.get("name", f"Laboratoire {lab_id}"),
            "laboratory_id": lab_id,
            "related_shipments": [s["id"] for s in shipments]
        }
    
    def _create_client_stop(self, location_id: str, action: str, shipments: List[Dict], locations_map: Dict[str, Dict], lab_id: str) -> Dict:
        """
        Crée un stop client (pickup ou delivery) pour un laboratoire spécifique
        
        Args:
            location_id: ID de la location du client
            action: "pickup" ou "delivery"
            shipments: Shipments concernés
            locations_map: Map des locations
            lab_id: ID du laboratoire concerné (ou "DEPOT")
            
        Returns:
            Dict: Stop data
        """
        location_data = locations_map.get(location_id, {})
        
        # Récupérer le nom du client depuis le premier shipment
        client_name = shipments[0].get("client_name", "Client inconnu") if shipments else "Client inconnu"
        
        # Récupérer le nom du laboratoire depuis le premier shipment
        lab_name = shipments[0].get("laboratory_name", "Laboratoire") if shipments else "Laboratoire"
        if lab_id == "DEPOT":
            lab_name = "Dépôt"
        
        return {
            "location_id": location_id,
            "stop_type": "client",
            "client_actions": action,
            "is_shared_pickup_stop": False,  # Les clients ne sont jamais shared pickup
            "shipments_count": len(shipments),
            "location_name": location_data.get("name", location_data.get("address", f"Client {location_id}")),
            "client_name": client_name,
            "laboratory_id": lab_id,
            "laboratory_name": lab_name,
            "related_shipments": [s["id"] for s in shipments]
        }