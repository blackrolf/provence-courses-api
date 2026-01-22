"""
Service d'expansion des shipments pour OR-Tools
Transforme les shipments en nœuds + contraintes pickup/delivery AVANT OR-Tools

Logique :
1. Shipments is_shared_pickup=true → 1 nœud delivery_only 
2. Shipments is_shared_pickup=false → 2 nœuds + 1 contrainte pickup/delivery
3. Plusieurs shipments même pickup → Plusieurs nœuds pickup distincts
"""

import structlog
from typing import Dict, List, Any, Tuple
from collections import defaultdict
import uuid

logger = structlog.get_logger()


class ShipmentExpander:
    """
    Service d'expansion des shipments pour OR-Tools V3.0
    
    Transforme la structure logique des shipments en structure physique
    pour OR-Tools avec contraintes pickup/delivery correctes.
    """
    
    def __init__(self):
        pass
    
    def expand_shipments_for_ortools(self, shipments: List[Dict], 
                                   original_stops: List[Dict]) -> Dict:
        """
        Expand les shipments en nœuds OR-Tools + contraintes pickup/delivery
        
        Args:
            shipments: Shipments filtrés (non-shared seulement)
            original_stops: Stops originaux pour récupérer les infos
            
        Returns:
            Dict: Structure expandue pour OR-Tools
            {
                "expanded_stops": [...],           # Stops dupliqués selon shipments
                "pickup_delivery_constraints": [...], # Contraintes OR-Tools
                "expansion_metadata": {...}
            }
        """
        logger.info("Starting shipment expansion for OR-Tools", 
                   shipments_count=len(shipments))
        
        # 1. Analyser les shipments par type
        expansion_analysis = self._analyze_shipments_for_expansion(shipments)
        
        # 2. Créer les stops expandus
        expanded_stops = self._create_expanded_stops(shipments, original_stops, expansion_analysis)
        
        # 3. Créer les contraintes pickup/delivery
        pickup_delivery_constraints = self._create_pickup_delivery_constraints(
            shipments, expanded_stops, expansion_analysis
        )
        
        # 4. Métadonnées d'expansion
        expansion_metadata = {
            "original_shipments": len(shipments),
            "expanded_stops": len(expanded_stops),
            "pickup_delivery_constraints": len(pickup_delivery_constraints),
            "shared_deliveries": expansion_analysis["shared_deliveries"],
            "pickup_delivery_pairs": expansion_analysis["pickup_delivery_pairs"],
            "stop_multiplications": expansion_analysis["stop_multiplications"]
        }
        
        result = {
            "expanded_stops": expanded_stops,
            "pickup_delivery_constraints": pickup_delivery_constraints,
            "expansion_metadata": expansion_metadata
        }
        
        logger.info("Shipment expansion completed",
                   original_shipments=len(shipments),
                   expanded_stops=len(expanded_stops),
                   constraints=len(pickup_delivery_constraints))
        
        return result
    
    def _analyze_shipments_for_expansion(self, shipments: List[Dict]) -> Dict:
        """
        Analyse les shipments pour déterminer l'expansion nécessaire
        
        Args:
            shipments: Liste des shipments
            
        Returns:
            Dict: Analyse de l'expansion nécessaire
        """
        logger.info("Analyzing shipments for expansion")
        
        shared_deliveries = []
        pickup_delivery_pairs = []
        
        # Regrouper par pickup_stop_id pour identifier les multiplications
        pickups_by_stop = defaultdict(list)
        deliveries_by_stop = defaultdict(list)
        
        for shipment in shipments:
            is_shared = shipment.get("is_shared_pickup", False)
            pickup_stop_id = shipment.get("pickup_stop_id")
            delivery_stop_id = shipment.get("delivery_stop_id")
            
            if is_shared:
                # Shared pickup → Delivery only
                shared_deliveries.append({
                    "shipment": shipment,
                    "delivery_stop_id": delivery_stop_id,
                    "shipment_ref": shipment.get("shipment_ref")
                })
                
                # Compter les deliveries par stop
                if delivery_stop_id:
                    deliveries_by_stop[delivery_stop_id].append(shipment)
            else:
                # Non-shared → Pickup + Delivery avec contrainte
                pickup_delivery_pairs.append({
                    "shipment": shipment,
                    "pickup_stop_id": pickup_stop_id,
                    "delivery_stop_id": delivery_stop_id,
                    "shipment_ref": shipment.get("shipment_ref")
                })
                
                # Compter les pickups et deliveries par stop
                if pickup_stop_id:
                    pickups_by_stop[pickup_stop_id].append(shipment)
                if delivery_stop_id:
                    deliveries_by_stop[delivery_stop_id].append(shipment)
        
        # Identifier les stops qui nécessitent une multiplication
        stop_multiplications = {}
        
        # Pickups multiples
        for stop_id, pickup_shipments in pickups_by_stop.items():
            if len(pickup_shipments) > 1:
                stop_multiplications[stop_id] = {
                    "type": "pickup",
                    "multiplier": len(pickup_shipments),
                    "shipments": pickup_shipments
                }
        
        # Deliveries multiples
        for stop_id, delivery_shipments in deliveries_by_stop.items():
            if len(delivery_shipments) > 1:
                if stop_id in stop_multiplications:
                    # Stop déjà multiplié pour pickup, ajouter info delivery
                    stop_multiplications[stop_id]["delivery_multiplier"] = len(delivery_shipments)
                    stop_multiplications[stop_id]["delivery_shipments"] = delivery_shipments
                else:
                    stop_multiplications[stop_id] = {
                        "type": "delivery",
                        "multiplier": len(delivery_shipments),
                        "shipments": delivery_shipments
                    }
        
        analysis = {
            "shared_deliveries": shared_deliveries,
            "pickup_delivery_pairs": pickup_delivery_pairs,
            "pickups_by_stop": dict(pickups_by_stop),
            "deliveries_by_stop": dict(deliveries_by_stop),
            "stop_multiplications": stop_multiplications
        }
        
        logger.info("Shipment expansion analysis completed",
                   shared_deliveries=len(shared_deliveries),
                   pickup_delivery_pairs=len(pickup_delivery_pairs),
                   stops_to_multiply=len(stop_multiplications))
        
        return analysis
    
    def _create_expanded_stops(self, shipments: List[Dict], 
                              original_stops: List[Dict], 
                              analysis: Dict) -> List[Dict]:
        """
        Crée les stops expandus selon l'analyse des shipments
        
        Args:
            shipments: Shipments originaux
            original_stops: Stops originaux
            analysis: Analyse d'expansion
            
        Returns:
            List[Dict]: Stops expandus avec nœuds dupliqués
        """
        logger.info("Creating expanded stops")
        
        # Créer mapping stop_id → stop original
        stops_by_id = {stop["id"]: stop for stop in original_stops}
        
        expanded_stops = []
        stop_expansion_map = {}  # stop_id → [expanded_stop_ids]
        
        # 1. Traiter tous les stops nécessaires
        required_stop_ids = set()
        
        # Stops des shared deliveries
        for shared_delivery in analysis["shared_deliveries"]:
            delivery_stop_id = shared_delivery["delivery_stop_id"]
            if delivery_stop_id:
                required_stop_ids.add(delivery_stop_id)
        
        # Stops des pickup/delivery pairs
        for pair in analysis["pickup_delivery_pairs"]:
            pickup_stop_id = pair["pickup_stop_id"]
            delivery_stop_id = pair["delivery_stop_id"]
            if pickup_stop_id:
                required_stop_ids.add(pickup_stop_id)
            if delivery_stop_id:
                required_stop_ids.add(delivery_stop_id)
        
        # 2. Créer les stops expandus
        for stop_id in required_stop_ids:
            original_stop = stops_by_id.get(stop_id)
            if not original_stop:
                logger.warning("Original stop not found", stop_id=stop_id)
                continue
            
            multiplication_info = analysis["stop_multiplications"].get(stop_id)
            
            if multiplication_info:
                # Stop à multiplier
                multiplier = multiplication_info["multiplier"]
                shipments_for_stop = multiplication_info["shipments"]
                
                logger.debug("Multiplying stop", 
                           stop_id=stop_id, 
                           multiplier=multiplier,
                           type=multiplication_info["type"])
                
                expanded_stop_ids = []
                
                for i, shipment in enumerate(shipments_for_stop):
                    # Créer un stop expandu unique pour ce shipment
                    expanded_stop = original_stop.copy()
                    expanded_stop["id"] = f"{stop_id}_expanded_{i}"
                    expanded_stop["original_stop_id"] = stop_id
                    expanded_stop["expansion_index"] = i
                    expanded_stop["shipment_ref"] = shipment.get("shipment_ref")
                    expanded_stop["shipment_id"] = shipment.get("id")
                    expanded_stop["expansion_reason"] = f"multiple_{multiplication_info['type']}"
                    
                    expanded_stops.append(expanded_stop)
                    expanded_stop_ids.append(expanded_stop["id"])
                
                stop_expansion_map[stop_id] = expanded_stop_ids
            else:
                # Stop simple (pas de multiplication)
                expanded_stop = original_stop.copy()
                expanded_stop["original_stop_id"] = stop_id
                expanded_stop["expansion_index"] = 0
                expanded_stop["expansion_reason"] = "single"
                
                expanded_stops.append(expanded_stop)
                stop_expansion_map[stop_id] = [stop_id]
        
        logger.info("Expanded stops created",
                   original_stops_needed=len(required_stop_ids),
                   expanded_stops_created=len(expanded_stops),
                   multiplications=len([k for k, v in analysis["stop_multiplications"].items()]))
        
        # Sauvegarder le mapping pour les contraintes
        self._stop_expansion_map = stop_expansion_map
        
        return expanded_stops
    
    def _create_pickup_delivery_constraints(self, shipments: List[Dict],
                                          expanded_stops: List[Dict],
                                          analysis: Dict) -> List[Dict]:
        """
        Crée les contraintes pickup/delivery pour OR-Tools
        
        Args:
            shipments: Shipments originaux
            expanded_stops: Stops expandus
            analysis: Analyse d'expansion
            
        Returns:
            List[Dict]: Contraintes pickup/delivery pour OR-Tools
        """
        logger.info("Creating pickup/delivery constraints")
        
        # Créer mapping expanded_stop_id → stop info
        expanded_stops_map = {stop["id"]: stop for stop in expanded_stops}
        
        constraints = []
        
        # Traiter les pickup/delivery pairs (non-shared)
        for pair in analysis["pickup_delivery_pairs"]:
            shipment = pair["shipment"]
            pickup_stop_id = pair["pickup_stop_id"]
            delivery_stop_id = pair["delivery_stop_id"]
            shipment_ref = pair["shipment_ref"]
            
            # Trouver les stops expandus correspondants
            pickup_expanded_ids = self._stop_expansion_map.get(pickup_stop_id, [])
            delivery_expanded_ids = self._stop_expansion_map.get(delivery_stop_id, [])
            
            # Trouver le bon stop expandu selon le shipment
            pickup_expanded_id = self._find_expanded_stop_for_shipment(
                pickup_expanded_ids, shipment, expanded_stops_map
            )
            delivery_expanded_id = self._find_expanded_stop_for_shipment(
                delivery_expanded_ids, shipment, expanded_stops_map
            )
            
            if pickup_expanded_id and delivery_expanded_id:
                constraint = {
                    "constraint_type": "pickup_delivery",
                    "pickup_stop_id": pickup_expanded_id,
                    "delivery_stop_id": delivery_expanded_id,
                    "shipment_ref": shipment_ref,
                    "shipment_id": shipment.get("id"),
                    "original_pickup_stop_id": pickup_stop_id,
                    "original_delivery_stop_id": delivery_stop_id
                }
                
                constraints.append(constraint)
                
                logger.debug("Pickup/delivery constraint created",
                           shipment_ref=shipment_ref,
                           pickup=pickup_expanded_id,
                           delivery=delivery_expanded_id)
            else:
                logger.warning("Could not create constraint - missing stops",
                             shipment_ref=shipment_ref,
                             pickup_found=pickup_expanded_id is not None,
                             delivery_found=delivery_expanded_id is not None)
        
        logger.info("Pickup/delivery constraints created", count=len(constraints))
        
        return constraints
    
    def _find_expanded_stop_for_shipment(self, expanded_stop_ids: List[str],
                                       shipment: Dict,
                                       expanded_stops_map: Dict) -> str:
        """
        Trouve le stop expandu correspondant à un shipment spécifique
        
        Args:
            expanded_stop_ids: IDs des stops expandus possibles
            shipment: Shipment à matcher
            expanded_stops_map: Map des stops expandus
            
        Returns:
            str: ID du stop expandu correspondant
        """
        shipment_id = shipment.get("id")
        shipment_ref = shipment.get("shipment_ref")
        
        # Si un seul stop expandu, c'est celui-là
        if len(expanded_stop_ids) == 1:
            return expanded_stop_ids[0]
        
        # Chercher le stop avec le bon shipment_id
        for expanded_id in expanded_stop_ids:
            expanded_stop = expanded_stops_map.get(expanded_id)
            if expanded_stop:
                if (expanded_stop.get("shipment_id") == shipment_id or
                    expanded_stop.get("shipment_ref") == shipment_ref):
                    return expanded_id
        
        # Fallback : prendre le premier
        logger.warning("Could not match shipment to expanded stop, using first",
                     shipment_ref=shipment_ref,
                     expanded_stops=len(expanded_stop_ids))
        
        return expanded_stop_ids[0] if expanded_stop_ids else None


class ShipmentExpanderError(Exception):
    """Exception levée lors d'erreurs d'expansion des shipments"""
    pass