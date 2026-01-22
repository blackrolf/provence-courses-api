"""
Service de sauvegarde des solutions OR-Tools enrichies
Utilise le client Supabase existant pour sauvegarder toutes les données
"""

import structlog
from typing import Dict, List, Any
from .solution_enricher import SolutionEnricher
from app.integrations.supabase.base_client import supabase_base_client
from app.integrations.supabase.repositories.routes_repository import RoutesRepository
from app.integrations.supabase.repositories.stops_repository import StopsRepository

logger = structlog.get_logger()


class SolutionSaver:
    """
    Sauvegarde les solutions OR-Tools enrichies en base Supabase
    via le client HTTP Supabase
    """
    
    def __init__(self):
        self.enricher = SolutionEnricher()
        self.supabase_client = supabase_base_client
        # Utiliser les repositories existants au lieu de dupliquer le code
        self.routes_repo = RoutesRepository(supabase_base_client)
        self.stops_repo = StopsRepository(supabase_base_client)
    
    async def save_complete_solution(self, route_id: str, final_stops: List[Dict], 
                                   optimization_metadata: Dict, 
                                   driver_start_time: str = None) -> Dict:
        """
        Sauvegarde complète de la solution optimisée
        
        Args:
            route_id: ID de la route
            final_stops: Stops finaux fusionnés et ordonnés
            optimization_metadata: Métadonnées de l'optimisation OR-Tools
            driver_start_time: Heure de début du chauffeur (si None, récupérée depuis la DB)
            
        Returns:
            Dict: Résultat de la sauvegarde
        """
        logger.info("Starting complete solution save",
                   route_id=route_id,
                   stops_count=len(final_stops),
                   start_time=driver_start_time)
        
        try:
            # 1. Enrichir la solution avec tous les calculs
            logger.info("Starting solution enrichment", 
                       final_stops_count=len(final_stops),
                       driver_start_time=driver_start_time)
            
            enriched_solution = await self.enricher.enrich_solution(
                route_id, final_stops, driver_start_time
            )
            
            logger.info("Solution enrichment completed", 
                       enriched_stops_count=len(enriched_solution.get("enriched_stops", [])),
                       route_totals=enriched_solution.get("route_totals", {}))
            
            # 2. Sauvegarder les stops enrichis
            stops_result = await self._save_enriched_stops(
                route_id, enriched_solution["enriched_stops"]
            )
            
            # 3. Sauvegarder les métadonnées de la route
            route_result = await self._save_route_metadata(
                route_id, enriched_solution["route_totals"], 
                enriched_solution["polyline"], optimization_metadata
            )
            
            # 4. Créer le résumé de sauvegarde
            save_summary = {
                "status": "success",
                "route_id": route_id,
                "stops_saved": stops_result["stops_saved"],
                "route_updated": route_result["success"],
                "enrichment_data": {
                    "total_distance_km": enriched_solution["route_totals"]["total_distance_km"],
                    "total_duration_minutes": enriched_solution["route_totals"]["total_duration_minutes"],
                    "estimated_start_time": enriched_solution["route_totals"]["estimated_start_time"],
                    "estimated_end_time": enriched_solution["route_totals"]["estimated_end_time"],
                    "polyline_generated": len(enriched_solution["polyline"]) > 0
                },
                "optimization_metadata": optimization_metadata,
                "save_details": {
                    "stops_result": stops_result,
                    "route_result": route_result
                }
            }
            
            logger.info("Complete solution save completed",
                       route_id=route_id,
                       stops_saved=stops_result["stops_saved"],
                       total_distance=enriched_solution["route_totals"]["total_distance_km"],
                       total_duration=enriched_solution["route_totals"]["total_duration_minutes"])
            
            return save_summary
            
        except Exception as e:
            logger.error("Error saving complete solution", route_id=route_id, error=str(e))
            return {
                "status": "error",
                "route_id": route_id,
                "message": f"Erreur sauvegarde: {str(e)}"
            }
    
    async def _save_enriched_stops(self, route_id: str, enriched_stops: List[Dict]) -> Dict:
        """Sauvegarde les stops enrichis via le client Supabase"""
        logger.info("Saving enriched stops", route_id=route_id, stops_count=len(enriched_stops))
        
        stops_saved = 0
        errors = []
        update_commands = []  # Garder pour debug
        
        logger.info("Starting to process enriched stops", 
                   enriched_stops_count=len(enriched_stops),
                   sample_stop_keys=list(enriched_stops[0].keys()) if enriched_stops else [])
        
        # DEBUG: Afficher les 3 premiers stops pour analyse
        for i, stop in enumerate(enriched_stops[:3]):
            logger.info(f"DEBUG Stop {i}", 
                       stop_id=stop.get("id"),
                       stop_type=stop.get("stop_type"),
                       has_arrival_time=stop.get("estimated_arrival_time") is not None,
                       has_distance=stop.get("distance_from_previous") is not None,
                       final_order=stop.get("final_order"),
                       final_stop_order=stop.get("final_stop_order"))
        
        for i, stop in enumerate(enriched_stops):
            try:
                stop_id = stop.get("id")
                if not stop_id:
                    logger.error("Stop missing ID", stop_index=i, stop_data=stop)
                    errors.append(f"Stop {i}: Missing ID")
                    continue
                
                # Préparer les données de mise à jour
                update_data = {
                    "stop_order": stop.get("final_order", stop.get("final_stop_order")),
                    "estimated_arrival_time": stop.get("estimated_arrival_time"),
                    "estimated_departure_time": stop.get("estimated_departure_time"),
                    "distance_from_previous": stop.get("distance_from_previous", 0.0),
                    "duration_from_previous": stop.get("duration_from_previous", 0)
                }
                
                logger.debug("Preparing stop update", 
                           stop_id=stop_id,
                           stop_index=i,
                           raw_update_data=update_data)
                
                # Filtrer les valeurs null
                filtered_data = {k: v for k, v in update_data.items() if v is not None}
                
                logger.debug("Filtered stop data", 
                           stop_id=stop_id,
                           filtered_data=filtered_data,
                           has_data=len(filtered_data) > 0)
                
                if filtered_data:
                    # TEMPORAIRE : Utiliser le client direct au lieu du repository pour déboguer
                    result = self.supabase_client.update(
                        table="driver_route_stops",
                        data=filtered_data,
                        id=stop_id
                    )
                    
                    logger.debug("Stop update attempt (direct client)", 
                               stop_id=stop_id, 
                               data=filtered_data, 
                               result_status=result.get("status"))
                    
                    if result.get("status") == "success":
                        stops_saved += 1
                        logger.debug("Stop updated successfully", stop_id=stop_id)
                    else:
                        error_msg = result.get("message", "Unknown error")
                        errors.append(f"Stop {stop_id}: {error_msg}")
                        logger.error("Failed to update stop", 
                                   stop_id=stop_id, 
                                   error=error_msg,
                                   full_result=result)
                    
                    # Garder pour debug
                    update_commands.append({
                        "stop_id": stop_id,
                        "stop_order": stop.get("final_order", stop.get("final_stop_order")),
                        "data": filtered_data,
                        "result": result.get("status")
                    })
                else:
                    logger.warning("No data to update for stop", 
                                 stop_id=stop_id,
                                 raw_data=update_data)
                
            except Exception as e:
                error_msg = f"Stop {stop.get('id', 'unknown')}: {str(e)}"
                errors.append(error_msg)
                logger.error("Exception updating stop", stop_id=stop.get('id'), error=str(e))
        
        logger.info("Enriched stops save completed", 
                   stops_saved=stops_saved, 
                   total_stops=len(enriched_stops),
                   errors_count=len(errors))
        
        return {
            "stops_saved": stops_saved,
            "total_stops": len(enriched_stops),
            "errors": errors,
            "update_commands": update_commands
        }
    
    async def _save_route_metadata(self, route_id: str, route_totals: Dict, 
                                 polyline: str, optimization_metadata: Dict) -> Dict:
        """Sauvegarde les métadonnées de la route via le client Supabase"""
        logger.info("Saving route metadata", route_id=route_id)
        
        try:
            # Préparer les données de mise à jour de la route
            route_update_data = {
                "status": "optimized",
                "estimated_duration": route_totals["estimated_duration"],
                "total_distance_km": route_totals["total_distance_km"]
            }
            
            # Ajouter la polyline si disponible
            if polyline:
                route_update_data["polyline"] = polyline
            
            # TEMPORAIRE : Utiliser le client direct au lieu du repository pour déboguer
            result = self.supabase_client.update(
                table="driver_routes",
                data=route_update_data,
                id=route_id
            )
            
            if result["status"] == "success":
                logger.info("Route metadata updated successfully", route_id=route_id)
                return {
                    "success": True,
                    "update_data": route_update_data,
                    "optimization_metadata": {
                        "method": optimization_metadata.get("method", "OR-Tools V3"),
                        "constraints_applied": optimization_metadata.get("constraints_applied", 0),
                        "total_distance_km": route_totals["total_distance_km"],
                        "working_hours": route_totals["working_hours"]
                    }
                }
            else:
                logger.error("Failed to update route metadata", route_id=route_id, error=result["message"])
                return {
                    "success": False,
                    "error": result["message"]
                }
            
        except Exception as e:
            logger.error("Exception updating route metadata", route_id=route_id, error=str(e))
            return {
                "success": False,
                "error": str(e)
            }
    
