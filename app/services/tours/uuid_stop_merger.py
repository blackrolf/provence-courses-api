"""
Service de fusion simple des stops par UUID d'origine
Logique simplifiée : fusionne les stops expandus qui ont le même UUID original
"""

import structlog
from typing import Dict, List, Any
from collections import defaultdict

logger = structlog.get_logger()


class UUIDStopMerger:
    """
    Service de fusion simple des stops par UUID d'origine
    
    Règles de fusion :
    - Lab pickup : garder le PREMIER (ordre le plus bas)
    - Lab dropoff : garder le DERNIER (ordre le plus haut)
    - Depot dropoff : garder le DERNIER (ordre le plus haut)
    - Client : garder le stop unique (pas de duplication normalement)
    """
    
    def __init__(self):
        pass
    
    def merge_stops_by_uuid(self, optimized_stops: List[Dict]) -> Dict:
        """
        Fusionne les stops qui ont le même UUID d'origine
        
        Args:
            optimized_stops: Liste des stops optimisés par OR-Tools (avec original_stop_id)
            
        Returns:
            Dict: Résultat de la fusion
            {
                "merged_stops": List[Dict],      # Stops après fusion
                "merge_summary": Dict,           # Résumé des fusions
                "uuid_mapping": Dict            # Mapping pour traçabilité
            }
        """
        logger.info("Starting UUID-based stop merging", 
                   total_stops=len(optimized_stops))
        
        # 1. Grouper les stops par UUID d'origine
        stops_by_uuid = self._group_stops_by_uuid(optimized_stops)
        
        # 2. Appliquer la logique de fusion selon le type
        merged_stops = []
        merge_details = []
        uuid_mapping = {}
        
        for original_uuid, stop_group in stops_by_uuid.items():
            if len(stop_group) == 1:
                # Stop unique - pas de fusion nécessaire
                stop = stop_group[0]
                merged_stops.append(stop)
                uuid_mapping[stop["id"]] = original_uuid
            else:
                # Plusieurs stops avec même UUID - fusion nécessaire
                selected_stop = self._select_stop_from_group(stop_group)
                merged_stops.append(selected_stop)
                
                # Documenter la fusion
                merge_details.append({
                    "original_uuid": original_uuid,
                    "stop_type": selected_stop["stop_type"],
                    "expanded_count": len(stop_group),
                    "selected_position": selected_stop["stop_order"],
                    "all_positions": [s["stop_order"] for s in stop_group],
                    "selection_rule": self._get_selection_rule(selected_stop["stop_type"])
                })
                
                # Mapping pour tous les stops du groupe
                for stop in stop_group:
                    uuid_mapping[stop["id"]] = original_uuid
        
        # 3. ⚠️ PRÉSERVER L'ORDRE DE LA RECONSTRUCTION - PAS DE TRI !
        # La reconstruction Phase1+Phase2 a défini l'ordre optimal, ne pas le casser !
        # Trier par final_stop_order (défini par la reconstruction) au lieu de stop_order
        merged_stops.sort(key=lambda x: x.get("final_stop_order", x.get("stop_order", 999)))
        
        # Réassigner les stop_order pour garantir la continuité 1, 2, 3...
        for idx, stop in enumerate(merged_stops):
            stop["final_stop_order"] = idx + 1
            stop["stop_order"] = idx + 1  # Synchroniser aussi stop_order
        
        # 4. Créer le résumé
        merge_summary = {
            "original_stops": len(optimized_stops),
            "merged_stops": len(merged_stops),
            "stops_merged": len(optimized_stops) - len(merged_stops),
            "merge_groups": len([g for g in stops_by_uuid.values() if len(g) > 1]),
            "merge_details": merge_details
        }
        
        logger.info("UUID-based merging completed",
                   original_stops=merge_summary["original_stops"],
                   merged_stops=merge_summary["merged_stops"],
                   stops_merged=merge_summary["stops_merged"])
        
        return {
            "merged_stops": merged_stops,
            "merge_summary": merge_summary,
            "uuid_mapping": uuid_mapping
        }
    
    def _group_stops_by_uuid(self, stops: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Groupe les stops par leur UUID d'origine
        
        Args:
            stops: Liste des stops avec original_stop_id
            
        Returns:
            Dict[str, List[Dict]]: Stops groupés par UUID
        """
        stops_by_uuid = defaultdict(list)
        
        for stop in stops:
            # Récupérer l'UUID d'origine
            original_uuid = stop.get("original_stop_id", stop.get("id"))
            
            # S'assurer qu'on a bien un UUID
            if original_uuid:
                stops_by_uuid[original_uuid].append(stop)
            else:
                logger.warning("Stop without original UUID", stop_id=stop.get("id"))
                # Utiliser l'ID actuel comme fallback
                stops_by_uuid[stop["id"]].append(stop)
        
        logger.info("Stops grouped by UUID",
                   unique_uuids=len(stops_by_uuid),
                   groups_with_multiples=len([g for g in stops_by_uuid.values() if len(g) > 1]))
        
        return dict(stops_by_uuid)
    
    def _select_stop_from_group(self, stop_group: List[Dict]) -> Dict:
        """
        Sélectionne le stop à garder selon les règles métier
        
        Règles :
        - lab_pickup : PREMIER (ordre le plus bas)
        - lab_dropoff : DERNIER (ordre le plus haut)
        - depot_dropoff : DERNIER (ordre le plus haut)
        - autres : PREMIER par défaut
        
        Args:
            stop_group: Groupe de stops avec même UUID
            
        Returns:
            Dict: Stop sélectionné
        """
        # Trier par stop_order
        sorted_stops = sorted(stop_group, key=lambda x: x.get("stop_order", 999))
        
        # Récupérer le type du premier stop (tous devraient avoir le même type)
        stop_type = sorted_stops[0].get("stop_type", "unknown")
        
        # Appliquer la règle de sélection
        if stop_type == "lab_pickup":
            # Garder le PREMIER
            selected = sorted_stops[0]
            logger.debug("Selected first stop for lab_pickup",
                       uuid=selected.get("original_stop_id"),
                       position=selected.get("stop_order"))
        
        elif stop_type in ["lab_dropoff", "depot_dropoff"]:
            # Garder le DERNIER
            selected = sorted_stops[-1]
            logger.debug(f"Selected last stop for {stop_type}",
                       uuid=selected.get("original_stop_id"),
                       position=selected.get("stop_order"))
        
        else:
            # Par défaut : garder le premier
            selected = sorted_stops[0]
            logger.debug(f"Selected first stop by default for {stop_type}",
                       uuid=selected.get("original_stop_id"),
                       position=selected.get("stop_order"))
        
        # Ajouter des métadonnées de fusion
        selected["merger_metadata"] = {
            "was_merged": True,
            "group_size": len(stop_group),
            "selection_rule": self._get_selection_rule(stop_type),
            "all_positions": [s.get("stop_order") for s in sorted_stops]
        }
        
        return selected
    
    def _get_selection_rule(self, stop_type: str) -> str:
        """
        Retourne la règle de sélection pour un type de stop
        
        Args:
            stop_type: Type du stop
            
        Returns:
            str: Description de la règle appliquée
        """
        rules = {
            "lab_pickup": "keep_first",
            "lab_dropoff": "keep_last",
            "depot_dropoff": "keep_last",
            "client": "keep_single"
        }
        
        return rules.get(stop_type, "keep_first_default")
    
    def validate_merge_result(self, merge_result: Dict) -> Dict:
        """
        Valide le résultat de la fusion
        
        Args:
            merge_result: Résultat de la fusion
            
        Returns:
            Dict: Résultat de validation
        """
        validation = {
            "is_valid": True,
            "warnings": [],
            "errors": []
        }
        
        merged_stops = merge_result["merged_stops"]
        
        # Vérifier l'ordre des stops
        for i, stop in enumerate(merged_stops):
            expected_order = i + 1
            if stop["final_stop_order"] != expected_order:
                validation["errors"].append({
                    "type": "order_mismatch",
                    "stop_id": stop["id"],
                    "expected": expected_order,
                    "actual": stop["final_stop_order"]
                })
                validation["is_valid"] = False
        
        # Vérifier les UUID uniques
        seen_uuids = set()
        for stop in merged_stops:
            uuid = stop.get("original_stop_id", stop["id"])
            if uuid in seen_uuids:
                validation["errors"].append({
                    "type": "duplicate_uuid",
                    "uuid": uuid,
                    "stop_id": stop["id"]
                })
                validation["is_valid"] = False
            seen_uuids.add(uuid)
        
        # Avertissements pour les fusions importantes
        for detail in merge_result["merge_summary"]["merge_details"]:
            if detail["expanded_count"] > 3:
                validation["warnings"].append({
                    "type": "large_merge_group",
                    "uuid": detail["original_uuid"],
                    "count": detail["expanded_count"],
                    "stop_type": detail["stop_type"]
                })
        
        logger.info("Merge validation completed",
                   is_valid=validation["is_valid"],
                   warnings=len(validation["warnings"]),
                   errors=len(validation["errors"]))
        
        return validation


class UUIDStopMergerError(Exception):
    """Exception levée lors d'erreurs de fusion par UUID"""
    pass