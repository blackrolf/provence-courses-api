"""
Service de sauvegarde V4 - Version corrigée avec gestion propre des expanded stops
"""

import structlog
from typing import Dict, List, Any, Optional, Tuple, Set
from datetime import datetime
from collections import defaultdict
from app.integrations.supabase.base_client import supabase_base_client
from app.integrations.supabase.repositories.routes_repository import RoutesRepository
from app.integrations.supabase.repositories.stops_repository import StopsRepository

logger = structlog.get_logger()


class SolutionSaverV4:
    """
    Sauvegarde V4 : Version corrigée avec traçabilité complète
    
    Stratégie corrigée:
    1. Mapper TOUS les changements (expanded→real + fusions)
    2. Générer TOUS les shipment_updates nécessaires
    3. Mettre à jour les shipments AVANT toute suppression
    4. Supprimer les stops en toute sécurité
    5. Mettre à jour les ordres et métadonnées
    """
    
    def __init__(self):
        self.supabase_client = supabase_base_client
        self.routes_repo = RoutesRepository(supabase_base_client)
        self.stops_repo = StopsRepository(supabase_base_client)
        self.original_state = None
    
    async def save_optimized_solution(self, route_id: str, optimized_stops: List[Dict], 
                                    optimization_metadata: Dict) -> Dict:
        """
        Sauvegarde la solution optimisée avec gestion correcte des expanded stops
        
        Args:
            route_id: ID de la route
            optimized_stops: Stops optimisés depuis OR-Tools (peuvent contenir des expanded)
            optimization_metadata: Métadonnées de l'optimisation
            
        Returns:
            Dict: Résultat de la sauvegarde avec statistiques
        """
        logger.info("Starting V4 solution save (corrected version)",
                   route_id=route_id,
                   stops_count=len(optimized_stops))
        
        try:
            # 1. Sauvegarder l'état initial pour rollback
            self.original_state = await self._save_current_state(route_id)
            logger.info("Current state saved", 
                       stops_count=len(self.original_state["stops"]),
                       shipments_count=len(self.original_state["shipments"]))
            
            # 2. Analyser et planifier TOUTES les transformations
            transformation_plan = await self._plan_complete_transformation(
                route_id, optimized_stops, self.original_state
            )
            
            # 3. Exécuter les mises à jour dans le bon ordre
            update_result = await self._execute_safe_updates(route_id, transformation_plan)
            
            # 4. Valider les contraintes
            validation_result = await self._validate_constraints(route_id)
            
            if not validation_result["valid"]:
                logger.warning("Constraint validation failed, attempting rollback",
                             violations=validation_result["violations"])
                await self._rollback(route_id)
                return {
                    "status": "error",
                    "message": "Constraint validation failed after update",
                    "violations": validation_result["violations"]
                }
            
            # 5. Mettre à jour les métadonnées de la route
            route_result = await self._update_route_metadata(
                route_id, optimization_metadata
            )
            
            # 6. Résumé de la sauvegarde réussie
            return {
                "status": "success",
                "route_id": route_id,
                "transformation_summary": {
                    "original_stops": len(self.original_state["stops"]),
                    "optimized_stops": len(optimized_stops),
                    "final_stops": transformation_plan["final_stops_count"],
                    "expanded_mappings": len(transformation_plan["expanded_mappings"]),
                    "fusion_groups": len(transformation_plan["fusion_groups"]),
                    "stops_deleted": len(transformation_plan["stops_to_delete"]),
                    "shipments_updated": update_result["shipments_updated"]
                },
                "validation": validation_result,
                "optimization_metadata": optimization_metadata
            }
            
        except Exception as e:
            logger.error("Error in V4 solution save", route_id=route_id, error=str(e))
            
            # Tenter un rollback
            if self.original_state:
                try:
                    await self._rollback(route_id)
                    logger.info("Rollback completed after error")
                except Exception as rollback_error:
                    logger.error("Rollback failed", error=str(rollback_error))
            
            return {
                "status": "error",
                "route_id": route_id,
                "message": f"Erreur sauvegarde V4: {str(e)}"
            }
    
    async def _save_current_state(self, route_id: str) -> Dict:
        """Sauvegarde l'état actuel pour rollback potentiel"""
        logger.info("Saving current state for potential rollback", route_id=route_id)
        
        # Récupérer tous les stops actuels
        stops_result = self.supabase_client.select(
            "driver_route_stops",
            "*",
            filters={"route_id": f"eq.{route_id}"}
        )
        
        # Récupérer tous les shipments actuels
        shipments_result = self.supabase_client.select(
            "driver_route_shipments",
            "*",
            filters={"route_id": f"eq.{route_id}"}
        )
        
        return {
            "stops": stops_result.get("data", []),
            "shipments": shipments_result.get("data", []),
            "timestamp": datetime.now().isoformat()
        }
    
    async def _plan_complete_transformation(self, route_id: str, 
                                          optimized_stops: List[Dict],
                                          current_state: Dict) -> Dict:
        """
        Planifie TOUTES les transformations nécessaires
        
        Gère:
        1. Mapping expanded → real avec traçabilité
        2. Fusion des stops CLIENT consécutifs
        3. Génération de TOUS les shipment_updates
        """
        logger.info("Planning complete transformation",
                   optimized_count=len(optimized_stops),
                   current_count=len(current_state["stops"]))
        
        # Créer un mapping des stops actuels
        current_stops_by_id = {stop["id"]: stop for stop in current_state["stops"]}
        
        # ÉTAPE 1: Mapper expanded → real avec traçabilité complète
        expanded_mappings = {}
        real_stops_sequence = []
        
        for stop in optimized_stops:
            stop_id = stop["id"]
            final_order = stop.get("final_stop_order", 0)
            
            if "_expanded_" in stop_id:
                # C'est un stop expanded, extraire l'ID réel
                real_id = stop_id.split("_expanded_")[0]
                expanded_mappings[stop_id] = real_id
                
                # Créer le stop réel avec les données de l'expanded
                real_stop = {**stop, "id": real_id, "original_expanded_id": stop_id}
                real_stops_sequence.append(real_stop)
                
                logger.debug("Expanded to real mapping",
                           expanded=stop_id[:20],
                           real=real_id[:20],
                           order=final_order)
            else:
                # Stop déjà réel
                real_stops_sequence.append(stop)
        
        # Trier par ordre final
        real_stops_sequence.sort(key=lambda x: x.get("final_stop_order", 0))
        
        # ÉTAPE 2: Dédupliquer les stops réels (même ID, ordres différents)
        unique_stops = {}
        duplicate_mappings = {}
        
        for stop in real_stops_sequence:
            stop_id = stop["id"]
            
            if stop_id in unique_stops:
                # Duplicata trouvé - garder celui avec le meilleur ordre selon le type
                existing = unique_stops[stop_id]
                stop_type = stop.get("stop_type", "")
                
                # Règle: lab_pickup garde le premier, autres gardent le dernier
                should_replace = (
                    stop_type != "lab_pickup" and 
                    stop.get("final_stop_order", 0) > existing.get("final_stop_order", 0)
                ) or (
                    stop_type == "lab_pickup" and
                    stop.get("final_stop_order", 0) < existing.get("final_stop_order", 0)
                )
                
                if should_replace:
                    # Tracker l'ancien pour les shipment updates
                    original_expanded = stop.get("original_expanded_id")
                    if original_expanded:
                        duplicate_mappings[original_expanded] = stop_id
                    unique_stops[stop_id] = stop
            else:
                unique_stops[stop_id] = stop
                # Tracker l'expanded original si présent
                original_expanded = stop.get("original_expanded_id")
                if original_expanded:
                    duplicate_mappings[original_expanded] = stop_id
        
        deduplicated_stops = list(unique_stops.values())
        deduplicated_stops.sort(key=lambda x: x.get("final_stop_order", 0))
        
        # ÉTAPE 3: Identifier les fusions CLIENT consécutives
        fusion_groups = []
        current_group = []
        
        for stop in deduplicated_stops:
            if (stop.get("stop_type") == "client" and 
                current_group and 
                current_group[-1].get("stop_type") == "client" and
                stop.get("location_id") == current_group[-1].get("location_id")):
                # Ajouter au groupe de fusion
                current_group.append(stop)
            else:
                # Fin du groupe précédent
                if len(current_group) > 1:
                    fusion_groups.append(current_group)
                # Démarrer nouveau groupe si client
                current_group = [stop] if stop.get("stop_type") == "client" else []
        
        # Dernier groupe
        if len(current_group) > 1:
            fusion_groups.append(current_group)
        
        logger.info("Fusion groups identified", count=len(fusion_groups))
        
        # ÉTAPE 4: Créer le plan final avec tous les updates
        final_stops = []
        stops_to_delete = set()
        shipment_updates = []
        
        # D'abord, mapper TOUS les expanded vers real
        for expanded_id, real_id in expanded_mappings.items():
            shipment_updates.append({
                "from_stop_id": expanded_id,
                "to_stop_id": real_id,
                "reason": "expanded_to_real"
            })
        
        # Ensuite, gérer les fusions CLIENT
        fusion_mapping = {}  # stop_id → stop_id gardé
        
        for stop in deduplicated_stops:
            stop_id = stop["id"]
            in_fusion_group = False
            
            for group in fusion_groups:
                if any(s["id"] == stop_id for s in group):
                    in_fusion_group = True
                    if group[0]["id"] == stop_id:
                        # Premier du groupe - on le garde avec actions combinées
                        final_stops.append({
                            "stop_id": stop_id,
                            "stop_data": stop,
                            "client_actions": self._combine_client_actions(group)
                        })
                        
                        # Les autres stops du groupe seront supprimés
                        for merged_stop in group[1:]:
                            stops_to_delete.add(merged_stop["id"])
                            fusion_mapping[merged_stop["id"]] = stop_id
                            shipment_updates.append({
                                "from_stop_id": merged_stop["id"],
                                "to_stop_id": stop_id,
                                "reason": "client_fusion"
                            })
                    break
            
            if not in_fusion_group:
                # Stop non fusionné - on le garde tel quel
                final_stops.append({
                    "stop_id": stop_id,
                    "stop_data": stop,
                    "client_actions": stop.get("client_actions")
                })
        
        # ÉTAPE 5: Identifier les stops orphelins (dans current mais pas dans optimized)
        optimized_stop_ids = {s["stop_id"] for s in final_stops}
        current_stop_ids = set(current_stops_by_id.keys())
        orphan_stops = current_stop_ids - optimized_stop_ids - stops_to_delete
        
        if orphan_stops:
            logger.warning("Orphan stops detected (not in optimized solution)",
                         count=len(orphan_stops),
                         samples=list(orphan_stops)[:5])
            # Ajouter les orphelins à supprimer
            stops_to_delete.update(orphan_stops)
        
        transformation_plan = {
            "final_stops": final_stops,
            "final_stops_count": len(final_stops),
            "stops_to_delete": list(stops_to_delete),
            "shipment_updates": shipment_updates,
            "expanded_mappings": expanded_mappings,
            "fusion_groups": [
                {
                    "kept_stop": group[0]["id"],
                    "merged_stops": [s["id"] for s in group[1:]],
                    "combined_actions": self._combine_client_actions(group)
                }
                for group in fusion_groups
            ]
        }
        
        logger.info("Transformation plan complete",
                   final_stops=len(final_stops),
                   stops_to_delete=len(stops_to_delete),
                   shipment_updates=len(shipment_updates),
                   expanded_mappings=len(expanded_mappings),
                   fusion_groups=len(fusion_groups))
        
        return transformation_plan
    
    def _combine_client_actions(self, stops_group: List[Dict]) -> str:
        """Combine les actions de plusieurs stops clients"""
        has_pickup = any(
            s.get("client_actions") in ["pickup", "both"] or
            s.get("shipment_action") == "pickup"
            for s in stops_group
        )
        has_delivery = any(
            s.get("client_actions") in ["delivery", "both"] or
            s.get("shipment_action") == "delivery"
            for s in stops_group
        )
        
        if has_pickup and has_delivery:
            return "both"
        elif has_pickup:
            return "pickup"
        elif has_delivery:
            return "delivery"
        else:
            # Défaut basé sur le premier stop
            return stops_group[0].get("client_actions", "delivery")
    
    async def _execute_safe_updates(self, route_id: str, transformation_plan: Dict) -> Dict:
        """
        Exécute les mises à jour dans l'ordre correct et sûr
        
        Ordre:
        1. Mettre à jour TOUS les shipments d'abord
        2. Supprimer les stops orphelins/fusionnés
        3. Mettre à jour les stops restants
        """
        logger.info("Executing safe updates", route_id=route_id)
        
        stats = {
            "shipments_updated": 0,
            "stops_deleted": 0,
            "stops_updated": 0,
            "errors": []
        }
        
        # PHASE 1: Mettre à jour TOUS les shipments
        logger.info("Phase 1: Updating shipments", 
                   updates_count=len(transformation_plan["shipment_updates"]))
        
        # Grouper les updates par from_stop_id pour efficacité
        updates_by_from = defaultdict(list)
        for update in transformation_plan["shipment_updates"]:
            updates_by_from[update["from_stop_id"]].append(update)
        
        for from_stop_id, updates in updates_by_from.items():
            # Prendre le dernier update pour ce stop (en cas de multiples)
            final_update = updates[-1]
            to_stop_id = final_update["to_stop_id"]
            reason = final_update["reason"]
            
            logger.debug("Processing shipment updates",
                       from_stop=from_stop_id[:20],
                       to_stop=to_stop_id[:20],
                       reason=reason)
            
            # Mettre à jour les pickup_stop_id
            try:
                result = self.supabase_client.rpc(
                    "update_shipments_stop_reference",
                    {
                        "p_route_id": route_id,
                        "p_old_stop_id": from_stop_id,
                        "p_new_stop_id": to_stop_id,
                        "p_field": "pickup_stop_id"
                    }
                )
                if result.get("data"):
                    count = result["data"].get("updated_count", 0)
                    stats["shipments_updated"] += count
                    if count > 0:
                        logger.info("Updated pickup references",
                                  from_stop=from_stop_id[:20],
                                  to_stop=to_stop_id[:20],
                                  count=count)
            except Exception as e:
                # Fallback sur update direct
                result = self.supabase_client.update(
                    "driver_route_shipments",
                    {"pickup_stop_id": to_stop_id},
                    filters={"pickup_stop_id": f"eq.{from_stop_id}"}
                )
                if result["status"] == "success":
                    stats["shipments_updated"] += len(result.get("data", []))
            
            # Mettre à jour les delivery_stop_id
            try:
                result = self.supabase_client.rpc(
                    "update_shipments_stop_reference",
                    {
                        "p_route_id": route_id,
                        "p_old_stop_id": from_stop_id,
                        "p_new_stop_id": to_stop_id,
                        "p_field": "delivery_stop_id"
                    }
                )
                if result.get("data"):
                    count = result["data"].get("updated_count", 0)
                    stats["shipments_updated"] += count
                    if count > 0:
                        logger.info("Updated delivery references",
                                  from_stop=from_stop_id[:20],
                                  to_stop=to_stop_id[:20],
                                  count=count)
            except Exception as e:
                # Fallback sur update direct
                result = self.supabase_client.update(
                    "driver_route_shipments",
                    {"delivery_stop_id": to_stop_id},
                    filters={"delivery_stop_id": f"eq.{from_stop_id}"}
                )
                if result["status"] == "success":
                    stats["shipments_updated"] += len(result.get("data", []))
        
        # PHASE 2: Supprimer les stops (maintenant safe car shipments mis à jour)
        logger.info("Phase 2: Deleting merged/orphan stops",
                   count=len(transformation_plan["stops_to_delete"]))
        
        for stop_id in transformation_plan["stops_to_delete"]:
            try:
                result = self.supabase_client.delete(
                    "driver_route_stops",
                    filters={"id": f"eq.{stop_id}"}
                )
                if result["status"] == "success":
                    stats["stops_deleted"] += 1
                    logger.debug("Stop deleted", stop_id=stop_id[:20])
                else:
                    error = f"Failed to delete stop {stop_id[:20]}: {result.get('message')}"
                    stats["errors"].append(error)
                    logger.warning(error)
            except Exception as e:
                error = f"Exception deleting stop {stop_id[:20]}: {str(e)}"
                stats["errors"].append(error)
                logger.error(error)
        
        # PHASE 3: Mettre à jour les stops restants avec nouvel ordre
        logger.info("Phase 3: Updating remaining stops with new order",
                   count=len(transformation_plan["final_stops"]))
        
        for i, stop_info in enumerate(transformation_plan["final_stops"], 1):
            stop_id = stop_info["stop_id"]
            client_actions = stop_info.get("client_actions")
            stop_data = stop_info.get("stop_data", {})
            
            # Préparer les données de mise à jour
            update_data = {
                "stop_order": i,
                "optimized": True,
                "optimization_timestamp": datetime.now().isoformat()
            }
            
            # Ajouter client_actions si pertinent
            if stop_data.get("stop_type") == "client" and client_actions:
                update_data["client_actions"] = client_actions
            
            # Ajouter les temps estimés si disponibles
            if "estimated_arrival_time" in stop_data:
                update_data["estimated_arrival_time"] = stop_data["estimated_arrival_time"]
            if "estimated_departure_time" in stop_data:
                update_data["estimated_departure_time"] = stop_data["estimated_departure_time"]
            
            try:
                result = self.supabase_client.update(
                    "driver_route_stops",
                    update_data,
                    filters={"id": f"eq.{stop_id}"}
                )
                
                if result["status"] == "success":
                    stats["stops_updated"] += 1
                    logger.debug("Stop updated",
                               stop_id=stop_id[:20],
                               order=i,
                               client_actions=client_actions)
                else:
                    error = f"Failed to update stop {stop_id[:20]}: {result.get('message')}"
                    stats["errors"].append(error)
                    logger.warning(error)
            except Exception as e:
                error = f"Exception updating stop {stop_id[:20]}: {str(e)}"
                stats["errors"].append(error)
                logger.error(error)
        
        logger.info("Updates execution completed",
                   shipments_updated=stats["shipments_updated"],
                   stops_deleted=stats["stops_deleted"],
                   stops_updated=stats["stops_updated"],
                   errors_count=len(stats["errors"]))
        
        return stats
    
    async def _validate_constraints(self, route_id: str) -> Dict:
        """Valide les contraintes après mise à jour"""
        logger.info("Validating constraints", route_id=route_id)
        
        violations = []
        
        # Vérifier l'intégrité référentielle
        orphan_shipments = self.supabase_client.rpc(
            "check_orphan_shipments",
            {"p_route_id": route_id}
        )
        
        if orphan_shipments.get("data"):
            orphan_count = orphan_shipments["data"].get("orphan_count", 0)
            if orphan_count > 0:
                violations.append(f"{orphan_count} shipments avec références invalides")
        
        # Vérifier la continuité des stop_order
        stops_result = self.supabase_client.select(
            "driver_route_stops",
            "id, stop_order",
            filters={"route_id": f"eq.{route_id}"},
            order="stop_order"
        )
        
        if stops_result["status"] == "success":
            stops = stops_result.get("data", [])
            for i, stop in enumerate(stops, 1):
                if stop["stop_order"] != i:
                    violations.append(f"Stop order discontinuity at position {i}")
                    break
        
        return {
            "valid": len(violations) == 0,
            "violations": violations
        }
    
    async def _update_route_metadata(self, route_id: str, optimization_metadata: Dict) -> Dict:
        """Met à jour les métadonnées de la route"""
        logger.info("Updating route metadata", route_id=route_id)
        
        update_data = {
            "status": "optimized",
            "optimized_at": datetime.now().isoformat(),
            "optimization_method": optimization_metadata.get("method", "TwoPhase OR-Tools V4"),
            "total_distance_km": optimization_metadata.get("total_distance_km"),
            "estimated_duration_minutes": optimization_metadata.get("estimated_duration_minutes"),
            "estimated_end_time": optimization_metadata.get("estimated_end_time")
        }
        
        result = self.supabase_client.update(
            "driver_routes",
            update_data,
            filters={"id": f"eq.{route_id}"}
        )
        
        if result["status"] == "success":
            logger.info("Route metadata updated successfully")
        else:
            logger.warning("Failed to update route metadata", 
                         error=result.get("message"))
        
        return result
    
    async def _rollback(self, route_id: str) -> None:
        """Effectue un rollback vers l'état initial"""
        logger.info("Starting rollback to original state", route_id=route_id)
        
        if not self.original_state:
            logger.warning("No original state available for rollback")
            return
        
        try:
            # Supprimer tous les stops actuels
            self.supabase_client.delete(
                "driver_route_stops",
                filters={"route_id": f"eq.{route_id}"}
            )
            
            # Restaurer les stops originaux
            if self.original_state["stops"]:
                self.supabase_client.insert(
                    "driver_route_stops",
                    self.original_state["stops"]
                )
            
            # Restaurer les shipments si nécessaire
            # (généralement pas nécessaire car on ne les supprime pas)
            
            logger.info("Rollback completed successfully")
        except Exception as e:
            logger.error("Rollback failed", error=str(e))
            raise


class SolutionSaverV4Error(Exception):
    """Exception levée lors d'erreurs de sauvegarde V4"""
    pass