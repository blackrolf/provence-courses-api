"""
Service de fusion des stops CLIENT successifs après optimisation OR-Tools
"""

import structlog
from typing import Dict, List, Any

logger = structlog.get_logger()


class StopFusionService:
    """Service de fusion des stops CLIENT successifs à la même localisation"""
    
    def __init__(self):
        pass
    
    def analyze_and_merge_successive_client_stops(self, 
                                                 or_tools_sequence: List[str],
                                                 stops_map: Dict[str, Dict]) -> Dict:
        """
        Analyse la séquence OR-Tools et fusionne UNIQUEMENT les stops CLIENT successifs 
        à la même localisation
        
        Args:
            or_tools_sequence: Séquence des stop_ids retournée par OR-Tools
            stops_map: Map des stops actuels {stop_id: stop_data}
            
        Returns:
            Dict: Résultat de la fusion
            {
                "merged_stops": List[Dict],        # Stops après fusion
                "fusion_count": int,               # Nombre de stops fusionnés
                "fusion_summary": List[Dict],      # Détail des fusions
                "stop_id_mapping": Dict[str, str]  # Mapping old_id -> new_id
            }
        """
        logger.info("Analyzing OR-Tools sequence for successive client stop fusion",
                   sequence_length=len(or_tools_sequence))
        
        merged_stops = []
        fusion_summary = []
        fusion_count = 0
        stop_id_mapping = {}
        i = 0
        
        while i < len(or_tools_sequence):
            current_stop_id = or_tools_sequence[i]
            current_stop = stops_map.get(current_stop_id)
            
            if not current_stop:
                logger.warning("Stop not found in stops_map", stop_id=current_stop_id)
                i += 1
                continue
            
            current_location_id = current_stop["location_id"]
            current_stop_type = current_stop["stop_type"]
            
            # Traitement spécifique pour les stops CLIENT
            if current_stop_type == "client":
                # Chercher les stops CLIENT successifs à la même localisation
                consecutive_client_stops = [current_stop]
                j = i + 1
                
                # Vérifier les stops successifs
                while j < len(or_tools_sequence):
                    next_stop_id = or_tools_sequence[j]
                    next_stop = stops_map.get(next_stop_id)
                    
                    # Conditions de fusion strictes :
                    # 1. Stop existe
                    # 2. Même localisation
                    # 3. Type CLIENT
                    # 4. Position successive dans la séquence (j = i + len(consecutive))
                    if (next_stop and 
                        next_stop["location_id"] == current_location_id and
                        next_stop["stop_type"] == "client"):
                        consecutive_client_stops.append(next_stop)
                        j += 1
                    else:
                        # Dès qu'on a un stop différent, on s'arrête
                        break
                
                # Fusionner si plusieurs stops CLIENT successifs à la même localisation
                if len(consecutive_client_stops) > 1:
                    merged_stop = self._merge_successive_client_stops(
                        consecutive_client_stops,
                        len(merged_stops) + 1  # Nouvel ordre
                    )
                    
                    # Créer le mapping pour mise à jour des shipments
                    for stop in consecutive_client_stops:
                        stop_id_mapping[stop["id"]] = merged_stop["id"]
                    
                    # Documenter la fusion
                    fusion_summary.append({
                        "location_id": current_location_id,
                        "address": current_stop.get("formatted_address", ""),
                        "original_stops_count": len(consecutive_client_stops),
                        "original_stop_ids": [s["id"] for s in consecutive_client_stops],
                        "merged_stop_id": merged_stop["id"],
                        "fusion_type": "successive_client_stops",
                        "client_actions": merged_stop["client_actions"]
                    })
                    
                    fusion_count += len(consecutive_client_stops) - 1
                    logger.debug("Merged successive client stops",
                               location_id=current_location_id,
                               original_count=len(consecutive_client_stops),
                               merged_stop_id=merged_stop["id"])
                else:
                    # Stop CLIENT unique - pas de fusion
                    merged_stop = current_stop.copy()
                    merged_stop["stop_order"] = len(merged_stops) + 1
                    stop_id_mapping[current_stop["id"]] = merged_stop["id"]
                
                merged_stops.append(merged_stop)
                i = j  # Passer aux stops suivants
                
            else:
                # Stop LAB ou DEPOT - traitement individuel, pas de fusion
                merged_stop = current_stop.copy()
                merged_stop["stop_order"] = len(merged_stops) + 1
                stop_id_mapping[current_stop["id"]] = merged_stop["id"]
                
                merged_stops.append(merged_stop)
                i += 1
        
        logger.info("Stop fusion analysis completed",
                   original_stops=len(or_tools_sequence),
                   final_stops=len(merged_stops),
                   fusions_performed=len(fusion_summary),
                   stops_merged=fusion_count)
        
        return {
            "merged_stops": merged_stops,
            "fusion_count": fusion_count,
            "fusion_summary": fusion_summary,
            "stop_id_mapping": stop_id_mapping
        }
    
    def _merge_successive_client_stops(self, consecutive_stops: List[Dict], new_order: int) -> Dict:
        """
        Fusionne plusieurs stops CLIENT successifs à la même localisation
        
        Args:
            consecutive_stops: Liste des stops CLIENT successifs à fusionner
            new_order: Nouvel ordre du stop fusionné
            
        Returns:
            Dict: Stop CLIENT fusionné
        """
        # Utiliser le premier stop comme base
        base_stop = consecutive_stops[0].copy()
        base_stop["stop_order"] = new_order
        
        # Analyser les actions client pour déterminer l'action combinée
        client_actions = [stop.get("client_actions") for stop in consecutive_stops]
        unique_actions = set(filter(None, client_actions))  # Enlever les None
        
        # Déterminer l'action combinée
        if "pickup" in unique_actions and "delivery" in unique_actions:
            base_stop["client_actions"] = "both"
        elif "pickup" in unique_actions:
            base_stop["client_actions"] = "pickup"
        elif "delivery" in unique_actions:
            base_stop["client_actions"] = "delivery"
        else:
            # Garder l'action du premier stop par défaut
            base_stop["client_actions"] = consecutive_stops[0].get("client_actions")
        
        # Métadonnées pour traçabilité
        base_stop["fusion_metadata"] = {
            "is_merged_stop": True,
            "original_stop_count": len(consecutive_stops),
            "original_stop_ids": [stop["id"] for stop in consecutive_stops],
            "merged_actions": list(unique_actions)
        }
        
        logger.debug("Client stops merged successfully",
                   merged_stop_id=base_stop["id"],
                   original_count=len(consecutive_stops),
                   final_action=base_stop["client_actions"])
        
        return base_stop
    
    def validate_fusion_rules(self, stops_sequence: List[Dict]) -> Dict:
        """
        Valide que les règles de fusion sont respectées
        
        Args:
            stops_sequence: Séquence de stops après fusion
            
        Returns:
            Dict: Résultat de validation
        """
        validation_results = {
            "is_valid": True,
            "issues": [],
            "stats": {
                "total_stops": len(stops_sequence),
                "client_stops": 0,
                "lab_stops": 0,
                "depot_stops": 0,
                "merged_stops": 0
            }
        }
        
        for stop in stops_sequence:
            stop_type = stop.get("stop_type", "unknown")
            
            # Comptage par type
            if stop_type == "client":
                validation_results["stats"]["client_stops"] += 1
            elif stop_type.startswith("lab"):
                validation_results["stats"]["lab_stops"] += 1
            elif stop_type.startswith("depot"):
                validation_results["stats"]["depot_stops"] += 1
            
            # Vérifier les stops fusionnés
            if stop.get("fusion_metadata", {}).get("is_merged_stop"):
                validation_results["stats"]["merged_stops"] += 1
                
                # Valider que seuls les stops CLIENT sont fusionnés
                if stop_type != "client":
                    validation_results["is_valid"] = False
                    validation_results["issues"].append({
                        "type": "invalid_fusion",
                        "stop_id": stop["id"],
                        "message": f"Stop de type '{stop_type}' ne devrait pas être fusionné"
                    })
        
        logger.info("Fusion validation completed",
                   is_valid=validation_results["is_valid"],
                   issues_count=len(validation_results["issues"]),
                   stats=validation_results["stats"])
        
        return validation_results