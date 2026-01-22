"""
Service de filtrage des données pour OR-Tools en fonction des shared pickups
"""

import structlog
from typing import Dict, List, Tuple, Any

logger = structlog.get_logger()


class ORToolsDataFilter:
    """
    Filtre les données stops/shipments pour OR-Tools selon la logique shared pickups
    
    Logique :
    - Stops avec is_shared_pickup_stop=true : EXCLUS d'OR-Tools (déjà optimisés)
    - Shipments avec is_shared_pickup=true : PAS de contrainte pickup/delivery
    - OR-Tools commence à start_location avec les colis déjà récupérés
    """
    
    def __init__(self):
        pass
    
    def filter_data_for_or_tools(self, optimization_data: Dict, shared_pickup_result: Dict) -> Dict:
        """
        Filtre les données d'optimisation pour OR-Tools
        
        Args:
            optimization_data: Package complet d'optimisation
            shared_pickup_result: Résultat de l'optimisation shared pickups
            
        Returns:
            Dict: Données filtrées pour OR-Tools
        """
        logger.info("Filtering optimization data for OR-Tools")
        
        # 1. Filtrer les stops (exclure shared pickups)
        or_tools_stops = self._filter_stops_for_or_tools(
            optimization_data["stops"],
            shared_pickup_result
        )
        
        # 2. Filtrer les shipments (gérer shared pickups) - CORRIGÉ
        or_tools_shipments = self._filter_shipments_for_or_tools(
            optimization_data["shipments"],
            or_tools_stops,
            optimization_data["stops"]  # Ajouter tous les stops pour analyser les pickup types
        )
        
        # 2b. 🔥 NOUVEAU : Expansion des stops pour OR-Tools (1 shipment = 2 nœuds)
        expanded_or_tools_stops = self._expand_stops_for_shipments(
            or_tools_stops,
            or_tools_shipments,
            optimization_data["stops"]
        )
        
        # 3. Ajuster les contraintes
        or_tools_constraints = self._adjust_constraints_for_or_tools(
            optimization_data["constraints"],
            expanded_or_tools_stops
        )
        
        # 4. Metadata mise à jour
        or_tools_metadata = self._update_metadata_for_or_tools(
            optimization_data["metadata"],
            expanded_or_tools_stops,
            or_tools_shipments,
            shared_pickup_result
        )
        
        # Préparer les pickup_delivery_pairs pour debug et visibilité
        pickup_delivery_pairs = []
        for shipment in or_tools_shipments:
            if shipment.get("or_tools_constraint_type") == "pickup_delivery":
                pickup_stop_id = shipment.get("pickup_stop_id")
                delivery_stop_id = shipment.get("delivery_stop_id")
                if pickup_stop_id and delivery_stop_id:
                    pickup_delivery_pairs.append({
                        "shipment_ref": shipment.get("shipment_ref"),
                        "pickup_stop_id": pickup_stop_id,
                        "delivery_stop_id": delivery_stop_id
                    })

        filtered_data = {
            "route": optimization_data["route"],
            "driver": optimization_data["driver"],
            "start_location": optimization_data["start_location"],
            "stops": expanded_or_tools_stops,
            "shipments": or_tools_shipments,
            "constraints": or_tools_constraints,
            "metadata": or_tools_metadata,
            "pickup_delivery_pairs": pickup_delivery_pairs,
            "shared_pickup_summary": {
                "total_shared_stops": len(shared_pickup_result.get("optimized_stops", [])),
                "shared_distance_km": shared_pickup_result.get("total_distance_km", 0),
                "excluded_from_or_tools": True
            }
        }
        
        logger.info("Data filtered for OR-Tools",
                   original_stops=len(optimization_data["stops"]),
                   filtered_stops=len(or_tools_stops),
                   expanded_stops=len(expanded_or_tools_stops),
                   original_shipments=len(optimization_data["shipments"]),
                   or_tools_shipments=len(or_tools_shipments))
        
        return filtered_data
    
    def _filter_stops_for_or_tools(self, all_stops: List[Dict], shared_pickup_result: Dict) -> List[Dict]:
        """
        Filtre les stops pour OR-Tools : exclure ceux avec is_shared_pickup_stop=true
        
        Args:
            all_stops: Tous les stops de la route
            shared_pickup_result: Résultat de l'optimisation shared pickups
            
        Returns:
            List[Dict]: Stops pour OR-Tools (sans shared pickups)
        """
        # IDs des stops déjà optimisés dans shared pickups
        shared_pickup_ids = set(
            stop["id"] for stop in shared_pickup_result.get("optimized_stops", [])
        )
        
        # Filtrer les stops
        or_tools_stops = []
        for stop in all_stops:
            stop_type = stop.get("stop_type")
            is_shared = stop.get("is_shared_pickup_stop", False)
            
            # RÈGLES DE FILTRAGE CORRIGÉES :
            
            # 1. Exclure TOUS les depot_pickup (shared ou non, ils sont gérés au départ)
            if stop_type == "depot_pickup":
                logger.debug("Excluding depot_pickup from OR-Tools (handled at start)",
                           stop_id=stop["id"],
                           is_shared=is_shared)
                continue
            
            # 2. Exclure SEULEMENT les lab_pickup SHARED (les non-shared restent dans OR-Tools)
            if stop_type == "lab_pickup" and is_shared:
                logger.debug("Excluding shared lab_pickup from OR-Tools",
                           stop_id=stop["id"],
                           stop_type=stop_type)
                continue
            
            # 3. Exclure les stops déjà dans shared pickups (double vérification)
            if stop["id"] in shared_pickup_ids:
                logger.debug("Excluding stop already in shared pickups",
                           stop_id=stop["id"])
                continue
            
            # 4. GARDER : lab_pickup non-shared, client, lab_dropoff, etc.
            or_tools_stops.append(stop)
            
            if stop_type == "lab_pickup" and not is_shared:
                logger.debug("Keeping lab_pickup non-shared for OR-Tools",
                           stop_id=stop["id"],
                           stop_type=stop_type)
        
        logger.info("Stops filtered for OR-Tools",
                   total_stops=len(all_stops),
                   shared_pickup_stops=len(shared_pickup_ids),
                   or_tools_stops=len(or_tools_stops))
        
        return or_tools_stops
    
    def _filter_shipments_for_or_tools(self, all_shipments: List[Dict], or_tools_stops: List[Dict], 
                                      all_stops: List[Dict]) -> List[Dict]:
        """
        Filtre les shipments pour OR-Tools selon la logique shared pickups CORRIGÉE
        
        Nouvelle logique :
        1. DEPOT PICKUP : Tous les shipments du depot → PAS de contrainte pickup/delivery (peu importe le flag)
        2. LAB PICKUP SHARED : Shipments avec lab_pickup shared → PAS de contrainte pickup/delivery  
        3. LAB PICKUP NON-SHARED : Contrainte pickup/delivery normale dans OR-Tools
        4. CLIENT PICKUP : Contrainte pickup/delivery normale
        
        Args:
            all_shipments: Tous les shipments de la route
            or_tools_stops: Stops qui seront dans OR-Tools
            all_stops: Tous les stops (pour analyser les pickup_stop_type)
            
        Returns:
            List[Dict]: Shipments avec contraintes ajustées pour OR-Tools
        """
        # IDs des stops qui seront dans OR-Tools
        or_tools_stop_ids = set(stop["id"] for stop in or_tools_stops)
        
        # Créer un mapping stop_id -> stop_data pour analyser les types
        stops_map = {stop["id"]: stop for stop in all_stops}
        
        or_tools_shipments = []
        
        for shipment in all_shipments:
            pickup_stop_id = shipment.get("pickup_stop_id")
            delivery_stop_id = shipment.get("delivery_stop_id")
            
            # Analyser le type de pickup stop
            pickup_stop = stops_map.get(pickup_stop_id)
            pickup_stop_type = pickup_stop.get("stop_type") if pickup_stop else None
            pickup_is_shared = pickup_stop.get("is_shared_pickup_stop", False) if pickup_stop else False
            
            # 🔥 CORRECTION : Vérifier AUSSI le flag dans le shipment (Option C - double vérification)
            shipment_is_shared = shipment.get("is_shared_pickup_stop", False)
            
            # La logique finale : shared si le stop OU le shipment l'indique
            is_shared_pickup = pickup_is_shared or shipment_is_shared
            
            # Vérifier si les stops du shipment sont dans OR-Tools
            pickup_in_or_tools = pickup_stop_id in or_tools_stop_ids
            delivery_in_or_tools = delivery_stop_id in or_tools_stop_ids
            
            # NOUVELLE LOGIQUE CORRIGÉE
            if pickup_stop_type == "depot_pickup":
                # RÈGLE 1 : DEPOT PICKUP → Toujours delivery only (colis déjà dans le véhicule)
                if delivery_in_or_tools:
                    filtered_shipment = shipment.copy()
                    filtered_shipment["or_tools_constraint_type"] = "delivery_only"
                    filtered_shipment["pickup_stop_id"] = None  # Pas de pickup dans OR-Tools
                    filtered_shipment["constraint_note"] = "Depot pickup: items already in vehicle at start_location"
                    or_tools_shipments.append(filtered_shipment)
                    
                    logger.debug("Depot pickup shipment: delivery only",
                               shipment_ref=shipment.get("shipment_ref"),
                               pickup_stop_type=pickup_stop_type,
                               is_shared_pickup=is_shared_pickup)
                else:
                    logger.debug("Depot pickup shipment: delivery not in OR-Tools scope",
                               shipment_ref=shipment.get("shipment_ref"))
                    
            elif pickup_stop_type == "lab_pickup" and is_shared_pickup:
                # RÈGLE 2 : LAB PICKUP SHARED → Delivery only (récupération faite en Phase 1)
                if delivery_in_or_tools:
                    filtered_shipment = shipment.copy()
                    filtered_shipment["or_tools_constraint_type"] = "delivery_only"
                    filtered_shipment["pickup_stop_id"] = None  # Pas de pickup dans OR-Tools
                    filtered_shipment["constraint_note"] = "Lab pickup shared: items already collected in Phase 1"
                    or_tools_shipments.append(filtered_shipment)
                    
                    logger.debug("Lab pickup shared shipment: delivery only",
                               shipment_ref=shipment.get("shipment_ref"),
                               pickup_stop_type=pickup_stop_type)
                else:
                    logger.debug("Lab pickup shared shipment: delivery not in OR-Tools scope",
                               shipment_ref=shipment.get("shipment_ref"))
                    
            elif pickup_stop_type == "lab_pickup" and not is_shared_pickup:
                # RÈGLE 3 : LAB PICKUP NON-SHARED → Contrainte pickup/delivery normale
                if pickup_in_or_tools and delivery_in_or_tools:
                    filtered_shipment = shipment.copy()
                    filtered_shipment["or_tools_constraint_type"] = "pickup_delivery"
                    filtered_shipment["constraint_note"] = "Lab pickup non-shared: standard pickup/delivery constraint"
                    or_tools_shipments.append(filtered_shipment)
                    
                    logger.debug("Lab pickup non-shared shipment: pickup and delivery",
                               shipment_ref=shipment.get("shipment_ref"),
                               pickup_stop_id=pickup_stop_id,
                               delivery_stop_id=delivery_stop_id)
                else:
                    logger.debug("Lab pickup non-shared shipment: stops not in OR-Tools scope",
                               shipment_ref=shipment.get("shipment_ref"),
                               pickup_in_or_tools=pickup_in_or_tools,
                               delivery_in_or_tools=delivery_in_or_tools)
                    
            elif pickup_stop_type == "client":
                # RÈGLE 4 : CLIENT PICKUP → Contrainte pickup/delivery normale
                if pickup_in_or_tools and delivery_in_or_tools:
                    filtered_shipment = shipment.copy()
                    filtered_shipment["or_tools_constraint_type"] = "pickup_delivery"
                    filtered_shipment["constraint_note"] = "Client pickup: standard pickup/delivery constraint"
                    or_tools_shipments.append(filtered_shipment)
                    
                    logger.debug("Client pickup shipment: pickup and delivery",
                               shipment_ref=shipment.get("shipment_ref"),
                               pickup_stop_id=pickup_stop_id,
                               delivery_stop_id=delivery_stop_id)
                else:
                    logger.debug("Client pickup shipment: stops not in OR-Tools scope",
                               shipment_ref=shipment.get("shipment_ref"),
                               pickup_in_or_tools=pickup_in_or_tools,
                               delivery_in_or_tools=delivery_in_or_tools)
            elif pickup_stop_id is None and delivery_in_or_tools:
                # RÈGLE 5 : SHIPMENT DELIVERY ONLY (shared ou normal) → Delivery only
                filtered_shipment = shipment.copy()
                filtered_shipment["or_tools_constraint_type"] = "delivery_only"
                
                if shipment_is_shared:
                    filtered_shipment["constraint_note"] = "Shared pickup: items already collected in Phase 1"
                    logger.debug("Shared shipment without pickup: delivery only",
                               shipment_ref=shipment.get("shipment_ref"),
                               delivery_stop_id=delivery_stop_id)
                else:
                    filtered_shipment["constraint_note"] = "Delivery only: no pickup required"
                    logger.debug("Delivery only shipment",
                               shipment_ref=shipment.get("shipment_ref"),
                               delivery_stop_id=delivery_stop_id)
                
                or_tools_shipments.append(filtered_shipment)
            else:
                logger.warning("Unknown pickup configuration",
                             shipment_ref=shipment.get("shipment_ref"),
                             pickup_stop_type=pickup_stop_type,
                             pickup_stop_id=pickup_stop_id,
                             is_shared_pickup=is_shared_pickup)
        
        logger.info("Shipments filtered for OR-Tools",
                   total_shipments=len(all_shipments),
                   or_tools_shipments=len(or_tools_shipments),
                   shared_pickup_shipments=sum(1 for s in all_shipments if s.get("is_shared_pickup_stop", False)))
        
        return or_tools_shipments
    
    def _adjust_constraints_for_or_tools(self, original_constraints: Dict, or_tools_stops: List[Dict]) -> Dict:
        """
        Ajuste les contraintes pour OR-Tools
        
        Args:
            original_constraints: Contraintes originales
            or_tools_stops: Stops qui seront dans OR-Tools
            
        Returns:
            Dict: Contraintes ajustées
        """
        # IDs des stops dans OR-Tools
        or_tools_stop_ids = set(stop["id"] for stop in or_tools_stops)
        
        adjusted_constraints = original_constraints.copy()
        
        # Filtrer les restrictions géographiques
        original_restrictions = original_constraints.get("geographic_restrictions", [])
        filtered_restrictions = [
            restriction for restriction in original_restrictions
            if restriction.get("stop_id") in or_tools_stop_ids
        ]
        
        adjusted_constraints["geographic_restrictions"] = filtered_restrictions
        
        # Ajouter des metadata sur les ajustements
        adjusted_constraints["or_tools_adjustments"] = {
            "original_geographic_restrictions": len(original_restrictions),
            "filtered_geographic_restrictions": len(filtered_restrictions),
            "shared_pickups_excluded": True,
            "constraint_note": "Contraintes ajustées pour exclure shared pickups"
        }
        
        logger.info("Constraints adjusted for OR-Tools",
                   original_restrictions=len(original_restrictions),
                   filtered_restrictions=len(filtered_restrictions))
        
        return adjusted_constraints
    
    def _update_metadata_for_or_tools(self, original_metadata: Dict, or_tools_stops: List[Dict],
                                     or_tools_shipments: List[Dict], shared_pickup_result: Dict) -> Dict:
        """
        Met à jour les metadata pour OR-Tools
        
        Args:
            original_metadata: Metadata originales
            or_tools_stops: Stops OR-Tools
            or_tools_shipments: Shipments OR-Tools
            shared_pickup_result: Résultat shared pickups
            
        Returns:
            Dict: Metadata mises à jour
        """
        updated_metadata = original_metadata.copy()
        
        # Statistiques OR-Tools
        updated_metadata.update({
            "or_tools_stops": len(or_tools_stops),
            "or_tools_shipments": len(or_tools_shipments),
            "shared_pickup_stops": len(shared_pickup_result.get("optimized_stops", [])),
            "total_optimization_phases": 2,
            "phase_1_shared_pickups": {
                "completed": True,
                "stops_optimized": len(shared_pickup_result.get("optimized_stops", [])),
                "total_distance_km": shared_pickup_result.get("total_distance_km", 0)
            },
            "phase_2_or_tools": {
                "pending": True,
                "stops_to_optimize": len(or_tools_stops),
                "shipments_to_optimize": len(or_tools_shipments)
            }
        })
        
        # Recalculer le score de qualité pour OR-Tools
        or_tools_quality_score = self._calculate_or_tools_quality_score(
            or_tools_stops, or_tools_shipments
        )
        updated_metadata["or_tools_data_quality_score"] = or_tools_quality_score
        updated_metadata["ready_for_or_tools"] = or_tools_quality_score >= 0.8
        
        return updated_metadata
    
    def _calculate_or_tools_quality_score(self, stops: List[Dict], shipments: List[Dict]) -> float:
        """
        Calcule le score de qualité des données pour OR-Tools
        
        Args:
            stops: Stops OR-Tools
            shipments: Shipments OR-Tools
            
        Returns:
            float: Score de qualité (0-1)
        """
        if not stops and not shipments:
            return 0.0
        
        quality_factors = []
        
        # GPS coverage des stops
        if stops:
            stops_with_gps = sum(1 for s in stops if s.get("latitude") and s.get("longitude"))
            gps_coverage = stops_with_gps / len(stops)
            quality_factors.append(gps_coverage)
        
        # Complétude des shipments
        if shipments:
            complete_shipments = sum(1 for s in shipments 
                                   if s.get("or_tools_constraint_type") in ["pickup_delivery", "delivery_only"])
            shipment_completeness = complete_shipments / len(shipments)
            quality_factors.append(shipment_completeness)
        
        # Score moyen
        return sum(quality_factors) / len(quality_factors) if quality_factors else 0.0
    
    def get_stop_order_offset(self, shared_pickup_result: Dict) -> int:
        """
        Calcule l'offset de stop_order pour OR-Tools
        
        Les stops OR-Tools doivent commencer après les shared pickups.
        
        Args:
            shared_pickup_result: Résultat de l'optimisation shared pickups
            
        Returns:
            int: Offset pour les stop_order OR-Tools
        """
        shared_stops_count = len(shared_pickup_result.get("optimized_stops", []))
        
        # OR-Tools commence après les shared pickups
        # +1 pour start_location si nécessaire
        offset = shared_stops_count + 1
        
        logger.info("Calculated stop_order offset for OR-Tools",
                   shared_stops=shared_stops_count,
                   or_tools_offset=offset)
        
        return offset


    def _expand_stops_for_shipments(self, or_tools_stops: List[Dict], 
                                  or_tools_shipments: List[Dict], 
                                  all_stops: List[Dict]) -> List[Dict]:
        """
        🔥 NOUVEAU : Expansion des stops pour OR-Tools (1 shipment = 2 nœuds distincts)
        
        Logique :
        - Pour chaque shipment avec contrainte pickup_delivery → créer 2 stops uniques
        - Pour chaque shipment delivery_only → créer 1 stop unique  
        - Maintenir les stops "normaux" (depot, etc.)
        
        Args:
            or_tools_stops: Stops filtrés de base
            or_tools_shipments: Shipments avec contraintes
            all_stops: Tous les stops originaux pour copier les données
            
        Returns:
            List[Dict]: Stops expandus pour OR-Tools
        """
        import uuid
        logger.info("Expanding stops for OR-Tools shipments", 
                   base_stops=len(or_tools_stops),
                   shipments_to_expand=len(or_tools_shipments))
        
        # Créer mapping stop_id -> stop_data pour récupérer les infos complètes
        all_stops_map = {stop["id"]: stop for stop in all_stops}
        
        # Identifier les stops qui sont utilisés par des shipments
        shipment_stop_ids = set()
        for shipment in or_tools_shipments:
            pickup_stop_id = shipment.get("pickup_stop_id")
            delivery_stop_id = shipment.get("delivery_stop_id")
            if pickup_stop_id:
                shipment_stop_ids.add(pickup_stop_id)
            if delivery_stop_id:
                shipment_stop_ids.add(delivery_stop_id)
        
        expanded_stops = []
        
        # 1. Garder les stops qui ne sont PAS liés à des shipments (depot, etc.)
        for stop in or_tools_stops:
            if stop["id"] not in shipment_stop_ids:
                expanded_stops.append(stop.copy())
                logger.debug("Keeping non-shipment stop",
                           stop_id=stop["id"],
                           stop_type=stop.get("stop_type"))
        
        # 2. Pour chaque shipment, créer des stops spécifiques
        shipment_counter = 0
        for shipment in or_tools_shipments:
            shipment_counter += 1
            constraint_type = shipment.get("or_tools_constraint_type")
            shipment_ref = shipment.get("shipment_ref", f"shipment_{shipment_counter}")
            
            pickup_stop_id = shipment.get("pickup_stop_id")
            delivery_stop_id = shipment.get("delivery_stop_id")
            
            if constraint_type == "pickup_delivery" and pickup_stop_id and delivery_stop_id:
                # Créer 2 stops : pickup + delivery
                
                # Stop pickup
                original_pickup = all_stops_map.get(pickup_stop_id)
                if original_pickup:
                    expanded_pickup = original_pickup.copy()
                    expanded_pickup["id"] = str(uuid.uuid4())  # Nouvel UUID
                    expanded_pickup["shipment_ref"] = shipment_ref
                    expanded_pickup["shipment_action"] = "pickup"
                    expanded_pickup["original_stop_id"] = pickup_stop_id
                    expanded_pickup["expansion_note"] = f"Pickup for {shipment_ref}"
                    expanded_stops.append(expanded_pickup)
                    
                    # Mettre à jour l'ID dans le shipment
                    shipment["pickup_stop_id"] = expanded_pickup["id"]
                
                # Stop delivery
                original_delivery = all_stops_map.get(delivery_stop_id)
                if original_delivery:
                    expanded_delivery = original_delivery.copy()
                    expanded_delivery["id"] = str(uuid.uuid4())  # Nouvel UUID
                    expanded_delivery["shipment_ref"] = shipment_ref
                    expanded_delivery["shipment_action"] = "delivery"
                    expanded_delivery["original_stop_id"] = delivery_stop_id
                    expanded_delivery["expansion_note"] = f"Delivery for {shipment_ref}"
                    expanded_stops.append(expanded_delivery)
                    
                    # Mettre à jour l'ID dans le shipment
                    shipment["delivery_stop_id"] = expanded_delivery["id"]
                
                logger.debug("Expanded pickup_delivery shipment",
                           shipment_ref=shipment_ref,
                           pickup_created=original_pickup is not None,
                           delivery_created=original_delivery is not None)
                
            elif constraint_type == "delivery_only" and delivery_stop_id:
                # Créer 1 stop : delivery seulement
                
                original_delivery = all_stops_map.get(delivery_stop_id)
                if original_delivery:
                    expanded_delivery = original_delivery.copy()
                    expanded_delivery["id"] = str(uuid.uuid4())  # Nouvel UUID
                    expanded_delivery["shipment_ref"] = shipment_ref
                    expanded_delivery["shipment_action"] = "delivery"
                    expanded_delivery["original_stop_id"] = delivery_stop_id
                    expanded_delivery["expansion_note"] = f"Delivery only for {shipment_ref}"
                    expanded_stops.append(expanded_delivery)
                    
                    # Mettre à jour l'ID dans le shipment
                    shipment["delivery_stop_id"] = expanded_delivery["id"]
                
                logger.debug("Expanded delivery_only shipment",
                           shipment_ref=shipment_ref,
                           delivery_created=original_delivery is not None)
            else:
                logger.warning("Shipment not expanded - invalid configuration",
                             shipment_ref=shipment_ref,
                             constraint_type=constraint_type,
                             pickup_stop_id=pickup_stop_id,
                             delivery_stop_id=delivery_stop_id)
        
        logger.info("Stops expansion completed",
                   original_stops=len(or_tools_stops),
                   expanded_stops=len(expanded_stops),
                   expansion_ratio=round(len(expanded_stops) / len(or_tools_stops), 2) if or_tools_stops else 0)
        
        return expanded_stops


class ORToolsDataFilterError(Exception):
    """Exception levée lors d'erreurs de filtrage pour OR-Tools"""
    pass