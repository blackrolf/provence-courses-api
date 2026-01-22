"""
Service pour traiter et sauvegarder les résultats OR-Tools V3
Gère la fusion des stops expandus et la mise à jour Supabase
"""

import structlog
from typing import Dict, List, Any, Tuple
from collections import defaultdict
import re

logger = structlog.get_logger()


class ORToolsResultProcessor:
    """
    Traite les résultats OR-Tools V3 :
    1. Fusionne les stops expandus vers les stops originaux
    2. Reconstruit les shipments avec leurs actions
    3. Met à jour Supabase avec la solution finale
    """
    
    def __init__(self, data_retriever):
        self.data_retriever = data_retriever
        
    async def process_and_save_solution(self, route_id: str, two_phase_result: Dict) -> Dict:
        """
        Traite la solution OR-Tools complète et sauvegarde en base
        
        Args:
            route_id: ID de la route
            two_phase_result: Résultat complet du TwoPhaseOptimizer
            
        Returns:
            Dict: Résultat du traitement et de la sauvegarde
        """
        logger.info("Processing OR-Tools solution for database save", route_id=route_id)
        
        try:
            # 1. Extraire les données de la solution
            phase1_stops = two_phase_result.get("phase1_shared_pickups", {}).get("optimized_stops", [])
            phase2_stops = two_phase_result.get("phase2_or_tools", {}).get("optimized_stops", [])
            
            # 2. Créer la séquence finale fusionnée
            final_sequence = await self._create_final_sequence(phase1_stops, phase2_stops)
            
            # 3. Fusionner les stops expandus
            merged_stops = self._merge_expanded_stops(final_sequence)
            
            # 4. Reconstruire les shipments avec leurs actions
            reconstructed_shipments = await self._reconstruct_shipments(route_id, merged_stops)
            
            # 5. Sauvegarder en base
            save_result = await self._save_to_database(route_id, merged_stops, reconstructed_shipments, two_phase_result)
            
            logger.info("OR-Tools solution processed and saved successfully",
                       route_id=route_id,
                       final_stops=len(merged_stops),
                       shipments_reconstructed=len(reconstructed_shipments))
            
            return {
                "status": "success",
                "route_id": route_id,
                "final_stops": merged_stops,
                "reconstructed_shipments": reconstructed_shipments,
                "save_result": save_result,
                "processing_summary": {
                    "original_stops_phase1": len(phase1_stops),
                    "original_stops_phase2": len(phase2_stops),
                    "final_merged_stops": len(merged_stops),
                    "shipments_reconstructed": len(reconstructed_shipments)
                }
            }
            
        except Exception as e:
            logger.error("Error processing OR-Tools solution", 
                        route_id=route_id, 
                        error=str(e))
            return {
                "status": "error",
                "message": f"Erreur traitement solution: {str(e)}"
            }
    
    async def _create_final_sequence(self, phase1_stops: List[Dict], phase2_stops: List[Dict]) -> List[Dict]:
        """Crée la séquence finale en combinant Phase 1 + Phase 2"""
        final_sequence = []
        
        # Ajouter Phase 1 avec ordre correct
        for stop in phase1_stops:
            stop_with_order = stop.copy()
            stop_with_order["final_order"] = stop["optimized_stop_order"]
            stop_with_order["phase"] = "shared_pickups"
            final_sequence.append(stop_with_order)
        
        # Ajouter Phase 2 avec ordre correct
        for stop in phase2_stops:
            stop_with_order = stop.copy()
            stop_with_order["final_order"] = stop.get("final_stop_order", stop.get("stop_order", 999))
            stop_with_order["phase"] = "or_tools"
            final_sequence.append(stop_with_order)
        
        # Trier par ordre final
        final_sequence.sort(key=lambda x: x["final_order"])
        
        logger.info("Final sequence created",
                   phase1_stops=len(phase1_stops),
                   phase2_stops=len(phase2_stops),
                   total_sequence=len(final_sequence))
        
        return final_sequence
    
    def _merge_expanded_stops(self, final_sequence: List[Dict]) -> List[Dict]:
        """
        Fusionne les stops expandus vers les stops originaux
        
        Les stops expandus ont des IDs comme : original_uuid_expanded_0
        On les groupe par UUID original et on fusionne leurs actions
        """
        logger.info("Merging expanded stops", total_stops=len(final_sequence))
        
        # Grouper par stop original
        original_stops_groups = defaultdict(list)
        
        for stop in final_sequence:
            stop_id = stop["id"]
            
            # Détecter si c'est un stop expandu
            if "_expanded_" in stop_id:
                # Extraire l'UUID original
                original_id = re.match(r"^(.+)_expanded_\d+$", stop_id).group(1)
            else:
                original_id = stop_id
            
            original_stops_groups[original_id].append(stop)
        
        merged_stops = []
        
        for original_id, stops_group in original_stops_groups.items():
            if len(stops_group) == 1:
                # Stop simple (pas expandu)
                merged_stop = stops_group[0].copy()
                merged_stop["expanded_stops_count"] = 1
                merged_stop["shipment_actions"] = [stop.get("shipment_action")] if stop.get("shipment_action") else []
            else:
                # Stops expandus à fusionner
                merged_stop = self._merge_stop_group(stops_group, original_id)
            
            # Nettoyer l'ID pour revenir à l'original
            merged_stop["id"] = original_id
            merged_stops.append(merged_stop)
        
        # Re-trier par ordre final
        merged_stops.sort(key=lambda x: x["final_order"])
        
        # Réajuster les ordres pour être consécutifs
        for i, stop in enumerate(merged_stops):
            stop["final_order"] = i + 1
        
        logger.info("Expanded stops merged successfully",
                   original_stops=len(original_stops_groups),
                   merged_stops=len(merged_stops),
                   expansion_ratio=len(final_sequence)/len(merged_stops))
        
        return merged_stops
    
    def _merge_stop_group(self, stops_group: List[Dict], original_id: str) -> Dict:
        """Fusionne un groupe de stops expandus"""
        # Prendre le premier stop comme base
        merged_stop = stops_group[0].copy()
        
        # Utiliser l'ordre le plus petit (premier dans la séquence)
        merged_stop["final_order"] = min(stop["final_order"] for stop in stops_group)
        
        # Collecter toutes les actions de shipments
        shipment_actions = []
        shipment_refs = []
        
        for stop in stops_group:
            if stop.get("shipment_action"):
                shipment_actions.append(stop["shipment_action"])
            if stop.get("shipment_ref"):
                shipment_refs.append(stop["shipment_ref"])
        
        merged_stop["expanded_stops_count"] = len(stops_group)
        merged_stop["shipment_actions"] = shipment_actions
        merged_stop["shipment_refs"] = shipment_refs
        merged_stop["expanded_from"] = [stop["id"] for stop in stops_group]
        
        logger.debug("Stop group merged",
                    original_id=original_id[:20],
                    expanded_count=len(stops_group),
                    actions_count=len(shipment_actions))
        
        return merged_stop
    
    async def _reconstruct_shipments(self, route_id: str, merged_stops: List[Dict]) -> List[Dict]:
        """
        Reconstruit les shipments avec leurs nouvelles informations d'ordre
        """
        logger.info("Reconstructing shipments with new stop orders", route_id=route_id)
        
        try:
            # Récupérer les shipments originaux
            original_shipments = await self.data_retriever.get_route_shipments(route_id)
            
            # Créer un mapping stop_id → final_order
            stop_order_mapping = {stop["id"]: stop["final_order"] for stop in merged_stops}
            
            reconstructed_shipments = []
            
            for shipment in original_shipments:
                reconstructed_shipment = shipment.copy()
                
                # Mettre à jour les ordres pickup/delivery
                pickup_stop_id = shipment.get("pickup_stop_id")
                delivery_stop_id = shipment.get("delivery_stop_id")
                
                if pickup_stop_id in stop_order_mapping:
                    reconstructed_shipment["pickup_order"] = stop_order_mapping[pickup_stop_id]
                
                if delivery_stop_id in stop_order_mapping:
                    reconstructed_shipment["delivery_order"] = stop_order_mapping[delivery_stop_id]
                
                # Vérifier les contraintes
                pickup_order = reconstructed_shipment.get("pickup_order")
                delivery_order = reconstructed_shipment.get("delivery_order")
                
                if pickup_order and delivery_order:
                    reconstructed_shipment["constraint_respected"] = pickup_order < delivery_order
                else:
                    reconstructed_shipment["constraint_respected"] = None
                
                reconstructed_shipments.append(reconstructed_shipment)
            
            logger.info("Shipments reconstructed successfully",
                       total_shipments=len(reconstructed_shipments),
                       constraints_respected=sum(1 for s in reconstructed_shipments 
                                               if s.get("constraint_respected") is True))
            
            return reconstructed_shipments
            
        except Exception as e:
            logger.error("Error reconstructing shipments", error=str(e))
            return []
    
    async def _save_to_database(self, route_id: str, merged_stops: List[Dict], 
                               reconstructed_shipments: List[Dict], two_phase_result: Dict) -> Dict:
        """Sauvegarde la solution finale en base"""
        logger.info("Saving optimized solution to database", route_id=route_id)
        
        try:
            from app.integrations.supabase.base_client import SupabaseBaseClient
            client = SupabaseBaseClient()
            
            # 1. Mettre à jour les stop_order des stops
            stops_updated = 0
            for stop in merged_stops:
                update_data = {"stop_order": stop["final_order"]}
                
                update_result = client.update(
                    "driver_route_stops",
                    update_data,
                    id=stop["id"]
                )
                
                if update_result.get("status") == "success":
                    stops_updated += 1
            
            # 2. Mettre à jour le statut de la route
            route_metadata = {
                "status": "optimized",
                "total_distance_km": two_phase_result.get("total_distance_km", 0),
                "optimization_method": "OR-Tools V3 + Two-Phase",
                "optimization_timestamp": "now()",
                "constraints_applied": two_phase_result.get("phase2_or_tools", {}).get("or_tools_solution", {}).get("pickup_delivery_pairs_satisfied", 0)
            }
            
            route_result = client.update(
                "driver_routes", 
                route_metadata,
                id=route_id
            )
            
            save_result = {
                "status": "success",
                "stops_updated": stops_updated,
                "route_updated": route_result.get("status") == "success",
                "total_stops": len(merged_stops),
                "constraints_respected": sum(1 for s in reconstructed_shipments 
                                           if s.get("constraint_respected") is True)
            }
            
            logger.info("Solution saved to database successfully",
                       route_id=route_id,
                       stops_updated=stops_updated,
                       constraints_applied=route_metadata["constraints_applied"])
            
            return save_result
            
        except Exception as e:
            logger.error("Error saving to database", route_id=route_id, error=str(e))
            return {
                "status": "error",
                "message": f"Erreur sauvegarde: {str(e)}"
            }