"""
Orchestrateur pour le processus complet d'optimisation OR-Tools
"""

import structlog
from typing import Dict, List, Any
from .data_retriever import TourDataRetriever
from .uuid_stop_merger import UUIDStopMerger
from .directions_enricher import DirectionsEnricher
from .two_phase_optimizer import TwoPhaseOptimizer

logger = structlog.get_logger()


class OptimizationOrchestrator:
    """
    Orchestrateur principal pour le processus d'optimisation complet :
    1. OR-Tools optimization (à implémenter)
    2. Stop fusion (CLIENT successifs uniquement)
    3. Google Directions enrichment
    4. Supabase update (via repositories existants)
    """
    
    def __init__(self):
        self.data_retriever = TourDataRetriever()
        self.uuid_stop_merger = UUIDStopMerger()
        self.directions_enricher = DirectionsEnricher()
        self.two_phase_optimizer = TwoPhaseOptimizer()
    
    async def process_full_optimization(self, route_id: str) -> Dict:
        """
        Processus complet d'optimisation d'une tournée
        
        Args:
            route_id: ID de la route à optimiser
            
        Returns:
            Dict: Résultat complet du processus d'optimisation
            {
                "status": "success",
                "route_id": str,
                "optimization_applied": bool,
                "fusion_applied": bool,
                "enrichment_applied": bool,
                "supabase_updated": bool,
                "final_stops_count": int,
                "processing_summary": {
                    "or_tools_time": float,
                    "fusion_time": float,
                    "enrichment_time": float,
                    "supabase_time": float
                }
            }
        """
        logger.info("Starting full optimization process", route_id=route_id)
        
        try:
            # 1. Récupérer les données complètes pour OR-Tools
            optimization_data = await self.data_retriever.get_tour_optimization_data(route_id)
            
            if not optimization_data["metadata"]["ready_for_optimization"]:
                return {
                    "status": "error",
                    "message": "Route pas prête pour optimisation",
                    "issues": optimization_data["metadata"]["issues"]
                }
            
            # 2. OR-Tools optimization avec TwoPhaseOptimizer + V3
            logger.info("Launching Two-Phase optimization with OR-Tools V3")
            or_tools_result = await self.two_phase_optimizer.optimize_route_two_phases(route_id)
            
            # 3. Extraire les stops optimisés complets (avec UUID)
            optimized_stops = self._extract_optimized_stops(or_tools_result)
            
            # 4. Fusion simple par UUID d'origine
            fusion_result = self.uuid_stop_merger.merge_stops_by_uuid(optimized_stops)
            
            # 5. Enrichissement Google Directions avec infos driver
            route_data_with_driver = optimization_data["route"].copy()
            route_data_with_driver["driver"] = optimization_data["driver"]
            
            enrichment_result = await self.directions_enricher.enrich_optimized_route(
                route_data_with_driver,
                fusion_result["merged_stops"]
            )
            
            # 6. Mise à jour Supabase (via les repositories existants)
            supabase_result = await self._update_supabase_with_results(
                route_id,
                fusion_result,
                enrichment_result
            )
            
            logger.info("Full optimization process completed successfully",
                       route_id=route_id,
                       final_stops=len(fusion_result["merged_stops"]),
                       stops_merged=fusion_result["merge_summary"]["stops_merged"])
            
            return {
                "status": "success",
                "route_id": route_id,
                "optimization_applied": True,
                "fusion_applied": fusion_result["merge_summary"]["stops_merged"] > 0,
                "enrichment_applied": enrichment_result.get("route_polyline") != "",
                "supabase_updated": supabase_result["success"],
                "final_stops_count": len(fusion_result["merged_stops"]),
                "optimization_summary": {
                    "original_stops": len(optimization_data["stops"]),
                    "or_tools_stops_count": len(optimized_stops),
                    "final_stops_after_fusion": len(fusion_result["merged_stops"]),
                    "stops_merged": fusion_result["merge_summary"]["stops_merged"],
                    "total_distance_km": enrichment_result["total_distance_km"],
                    "estimated_duration_minutes": enrichment_result["estimated_duration_minutes"]
                }
            }
            
        except Exception as e:
            logger.error("Error during full optimization process", 
                        route_id=route_id, 
                        error=str(e))
            return {
                "status": "error",
                "message": f"Erreur lors de l'optimisation: {str(e)}"
            }
    
    async def _simulate_or_tools_optimization(self, optimization_data: Dict) -> Dict:
        """
        Simulation d'optimisation OR-Tools (à remplacer par vraie implémentation)
        
        Args:
            optimization_data: Données complètes pour OR-Tools
            
        Returns:
            Dict: Résultat simulé d'OR-Tools
        """
        logger.info("Simulating OR-Tools optimization", 
                   stops_count=len(optimization_data["stops"]))
        
        # Pour l'instant, on simule en réorganisant les stops
        # Dans la vraie implémentation, c'est ici qu'on appellerait OR-Tools
        
        stops = optimization_data["stops"]
        
        # Créer une séquence simulée qui met des stops CLIENT à la même localisation ensemble
        location_groups = {}
        for stop in stops:
            location_id = stop["location_id"]
            if location_id not in location_groups:
                location_groups[location_id] = []
            location_groups[location_id].append(stop)
        
        # Simuler une séquence optimisée avec groupements
        optimized_sequence = []
        for location_id, location_stops in location_groups.items():
            # Trier par type : depot -> lab -> client
            location_stops.sort(key=lambda s: {
                "depot_pickup": 1, "depot_dropoff": 2,
                "lab_pickup": 3, "lab_dropoff": 4,
                "client": 5
            }.get(s["stop_type"], 6))
            
            optimized_sequence.extend([stop["id"] for stop in location_stops])
        
        return {
            "optimized_stop_sequence": optimized_sequence,
            "optimization_metadata": {
                "algorithm": "simulated",
                "original_stops": len(stops),
                "location_groups": len(location_groups)
            }
        }
    
    def _extract_optimized_stops(self, two_phase_result: Dict) -> List[Dict]:
        """
        Extrait les stops optimisés complets des résultats TwoPhaseOptimizer
        
        Args:
            two_phase_result: Résultat du TwoPhaseOptimizer
            
        Returns:
            List[Dict]: Stops complets avec leurs métadonnées (incluant original_stop_id)
        """
        optimized_stops = []
        
        # 1. Ajouter les stops de la Phase 1 (shared pickups)
        phase1_stops = two_phase_result.get("phase1_shared_pickups", {}).get("optimized_stops", [])
        for stop in phase1_stops:
            optimized_stops.append(stop)
        
        # 2. Ajouter les stops de la Phase 2 (OR-Tools)
        phase2_stops = two_phase_result.get("phase2_or_tools", {}).get("optimized_stops", [])
        for stop in phase2_stops:
            optimized_stops.append(stop)
        
        logger.info("Extracted optimized stops",
                   phase1_stops=len(phase1_stops),
                   phase2_stops=len(phase2_stops),
                   total_stops=len(optimized_stops))
        
        return optimized_stops
    
    def _extract_optimized_sequence(self, two_phase_result: Dict) -> List[str]:
        """
        Extrait la séquence optimisée des résultats TwoPhaseOptimizer
        
        Args:
            two_phase_result: Résultat du TwoPhaseOptimizer
            
        Returns:
            List[str]: Séquence des stop_ids dans l'ordre optimisé
        """
        optimized_sequence = []
        
        # 1. Ajouter les stops de la Phase 1 (shared pickups)
        phase1_stops = two_phase_result.get("phase1_shared_pickups", {}).get("optimized_stops", [])
        for stop in phase1_stops:
            optimized_sequence.append(stop["id"])
        
        # 2. Ajouter les stops de la Phase 2 (OR-Tools)
        phase2_stops = two_phase_result.get("phase2_or_tools", {}).get("optimized_stops", [])
        for stop in phase2_stops:
            optimized_sequence.append(stop["id"])
        
        logger.info("Extracted optimized sequence",
                   phase1_stops=len(phase1_stops),
                   phase2_stops=len(phase2_stops),
                   total_sequence=len(optimized_sequence))
        
        return optimized_sequence
    
    async def _update_supabase_with_results(self, route_id: str, 
                                          fusion_result: Dict, 
                                          enrichment_result: Dict) -> Dict:
        """
        Met à jour Supabase avec les résultats finaux via les repositories existants
        
        Args:
            route_id: ID de la route
            fusion_result: Résultat de la fusion des stops
            enrichment_result: Résultat de l'enrichissement Directions
            
        Returns:
            Dict: Résultat de la mise à jour
        """
        logger.info("Updating Supabase with optimization results", route_id=route_id)
        
        try:
            # 1. Mettre à jour la route principale (via routes_repository)
            route_update_data = {
                "estimated_duration": enrichment_result["estimated_duration_minutes"],
                "total_distance_km": enrichment_result["total_distance_km"],
                "polyline": enrichment_result["route_polyline"],
                "status": "optimized"
            }
            
            route_result = self.data_retriever.routes_repo.update_route_optimization_data(
                route_id, route_update_data
            )
            
            if route_result["status"] != "success":
                raise Exception(f"Erreur mise à jour route: {route_result['message']}")
            
            # 2. MISE A JOUR des stops existants (pas de création/suppression)
            # Les stops fusionnés ont les mêmes UUID que ceux dans Supabase
            # On met à jour uniquement : stop_order, arrival_time, etc.
            enriched_stops = self._prepare_stops_for_update(
                fusion_result["merged_stops"],
                enrichment_result["stop_details"]
            )
            
            update_result = await self._update_existing_stops(enriched_stops)
            
            if update_result["status"] != "success":
                raise Exception(f"Erreur mise à jour stops: {update_result['message']}")
            
            # 3. Avec la nouvelle logique, pas de mise à jour des shipments nécessaire
            # Les shipments pointent toujours vers les UUID originaux des stops
            shipments_updated = 0
            
            logger.info("Supabase update completed successfully",
                       route_id=route_id,
                       stops_created=len(enriched_stops),
                       shipments_updated=shipments_updated)
            
            return {
                "success": True,
                "route_updated": True,
                "stops_updated": update_result.get("updated_count", len(enriched_stops)),
                "shipments_updated": shipments_updated
            }
            
        except Exception as e:
            logger.error("Error updating Supabase", route_id=route_id, error=str(e))
            return {
                "success": False,
                "error": str(e)
            }
    
    def _prepare_stops_for_supabase(self, merged_stops: List[Dict], 
                                   stop_details: List[Dict]) -> List[Dict]:
        """Prépare les stops fusionnés avec les données d'enrichissement pour Supabase"""
        
        # Créer un mapping des détails par stop_id
        details_map = {detail["stop_id"]: detail for detail in stop_details}
        
        prepared_stops = []
        for stop in merged_stops:
            stop_id = stop["id"]
            details = details_map.get(stop_id, {})
            
            prepared_stop = {
                **stop,  # Données de base du stop
                # Données d'enrichissement Directions
                "estimated_arrival_time": details.get("estimated_arrival_time"),
                "estimated_departure_time": details.get("estimated_departure_time"),
                "distance_from_previous": details.get("distance_from_previous", 0),
                "duration_from_previous": details.get("duration_from_previous", 0)
            }
            
            prepared_stops.append(prepared_stop)
        
        return prepared_stops
    
    async def _update_shipments_references(self, route_id: str, 
                                         stop_id_mapping: Dict[str, str]) -> Dict:
        """Met à jour les références des shipments après fusion"""
        
        shipments = await self.data_retriever.get_route_shipments(route_id)
        updated_count = 0
        
        for shipment in shipments:
            shipment_id = shipment["id"]
            update_data = {}
            needs_update = False
            
            # Vérifier pickup_stop_id
            pickup_stop_id = shipment.get("pickup_stop_id")
            if pickup_stop_id in stop_id_mapping:
                new_pickup_id = stop_id_mapping[pickup_stop_id]
                if new_pickup_id != pickup_stop_id:
                    update_data["pickup_stop_id"] = new_pickup_id
                    needs_update = True
            
            # Vérifier delivery_stop_id  
            delivery_stop_id = shipment.get("delivery_stop_id")
            if delivery_stop_id in stop_id_mapping:
                new_delivery_id = stop_id_mapping[delivery_stop_id]
                if new_delivery_id != delivery_stop_id:
                    update_data["delivery_stop_id"] = new_delivery_id
                    needs_update = True
            
            # Appliquer la mise à jour via le repository existant
            if needs_update:
                result = self.data_retriever.driver_shipments_repo.update_shipment_stop_references(
                    shipment_id, update_data
                )
                if result["status"] == "success":
                    updated_count += 1
        
        return {"updated_count": updated_count}
    
    def _prepare_stops_for_update(self, merged_stops: List[Dict], 
                                  stop_details: List[Dict]) -> List[Dict]:
        """
        Prépare les stops pour UPDATE uniquement (pas de création)
        Les stops gardent leur UUID original et on met à jour les infos
        
        Args:
            merged_stops: Stops après fusion par UUID
            stop_details: Détails d'enrichissement Google Directions
            
        Returns:
            List[Dict]: Stops préparés pour mise à jour
        """
        # Créer un mapping des détails par stop_id
        details_map = {detail["stop_id"]: detail for detail in stop_details}
        
        prepared_stops = []
        skipped_stops = 0
        
        for stop in merged_stops:
            # Utiliser l'UUID original pour la mise à jour
            stop_uuid = stop.get("original_stop_id", stop["id"])
            
            # Valider que c'est un UUID valide (pas d'IDs "expanded")
            if "_expanded_" in stop_uuid or not self._is_valid_uuid(stop_uuid):
                logger.debug("Skipping stop with invalid UUID", 
                           stop_id=stop["id"], 
                           uuid_to_update=stop_uuid)
                skipped_stops += 1
                continue
            
            details = details_map.get(stop["id"], {})
            
            # Préparer uniquement les champs à mettre à jour (colonnes existantes seulement)
            update_data = {
                "id": stop_uuid,  # UUID original pour identifier le stop
                "stop_order": stop["final_stop_order"],  # Nouvel ordre après optimisation
                "estimated_arrival_time": details.get("estimated_arrival_time"),
                "estimated_departure_time": details.get("estimated_departure_time"),
                "distance_from_previous": details.get("distance_from_previous", 0),
                "duration_from_previous": details.get("duration_from_previous", 0)
                # Supprimé: "optimized" et "optimization_metadata" car colonnes n'existent pas
            }
            
            prepared_stops.append(update_data)
        
        logger.info("Prepared stops for update",
                   total_stops=len(prepared_stops),
                   skipped_invalid_uuid=skipped_stops)
        
        return prepared_stops
    
    def _is_valid_uuid(self, uuid_string: str) -> bool:
        """Valide qu'une chaîne est un UUID valide"""
        try:
            import uuid
            uuid.UUID(uuid_string)
            return True
        except (ValueError, TypeError):
            return False
    
    async def _update_existing_stops(self, stops_updates: List[Dict]) -> Dict:
        """
        Met à jour les stops existants dans Supabase
        
        Args:
            stops_updates: Liste des mises à jour à appliquer
            
        Returns:
            Dict: Résultat de la mise à jour
        """
        logger.info("Updating existing stops in Supabase", count=len(stops_updates))
        
        try:
            updated_count = 0
            errors = []
            
            # Mettre à jour chaque stop individuellement
            # (On pourrait optimiser avec un batch update si le repo le supporte)
            for stop_update in stops_updates:
                stop_id = stop_update["id"]
                
                # Enlever l'id des données de mise à jour
                update_data = {k: v for k, v in stop_update.items() if k != "id"}
                
                # Appeler le repository pour UPDATE
                result = self.data_retriever.stops_repo.update_stop(stop_id, update_data)
                
                if result.get("status") == "success":
                    updated_count += 1
                else:
                    errors.append({
                        "stop_id": stop_id,
                        "error": result.get("message", "Unknown error")
                    })
            
            # Résultat global
            if errors:
                logger.warning("Some stops failed to update",
                             updated=updated_count,
                             failed=len(errors),
                             errors=errors[:5])  # Log max 5 errors
                return {
                    "status": "partial_success",
                    "updated_count": updated_count,
                    "errors": errors
                }
            else:
                logger.info("All stops updated successfully", count=updated_count)
                return {
                    "status": "success",
                    "updated_count": updated_count
                }
                
        except Exception as e:
            logger.error("Error updating stops", error=str(e))
            return {
                "status": "error",
                "message": str(e),
                "updated_count": 0
            }