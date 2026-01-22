"""
Orchestrateur d'optimisation en 2 phases : Shared Pickups + OR-Tools
"""

import structlog
from typing import Dict, List, Any
from .shared_pickup_optimizer import SharedPickupOptimizer, SharedPickupOptimizerError
from .or_tools_data_filter import ORToolsDataFilter, ORToolsDataFilterError
from .or_tools_vrp_solver_v3 import ORToolsVRPSolverV3, ORToolsVRPV3Error
from .data_retriever import TourDataRetriever
from .osrm_distance_matrix import OSRMDistanceMatrixService
from .shipment_expander import ShipmentExpander, ShipmentExpanderError
from .solution_enricher import SolutionEnricher
from .solution_saver import SolutionSaver
from .tour_reconstructor_v2 import TourReconstructorV2
from .uuid_tracker import UUIDTracker

logger = structlog.get_logger()


class TwoPhaseOptimizer:
    """
    Orchestrateur pour l'optimisation en 2 phases
    
    Phase 1: Optimisation GPS des shared pickups
    Phase 2: OR-Tools pour le reste de la tournée à partir de start_location
    """
    
    def __init__(self):
        self.shared_pickup_optimizer = SharedPickupOptimizer()
        self.or_tools_filter = ORToolsDataFilter()
        self.or_tools_solver_v3 = ORToolsVRPSolverV3()
        self.data_retriever = TourDataRetriever()
        self.osrm_service = OSRMDistanceMatrixService()
        self.shipment_expander = ShipmentExpander()
        self.tour_reconstructor_v2 = TourReconstructorV2()
        self.uuid_tracker = UUIDTracker()
    
    async def optimize_route_two_phases(self, route_id: str) -> Dict:
        """
        Optimise une route en 2 phases : shared pickups + OR-Tools
        
        Args:
            route_id: ID de la route à optimiser
            
        Returns:
            Dict: Résultat complet des 2 phases d'optimisation
        """
        logger.info("Starting two-phase optimization", route_id=route_id)
        
        try:
            # 1. Récupérer les données complètes d'optimisation
            optimization_data = await self.data_retriever.get_tour_optimization_data(route_id)
            
            # 2. PHASE 1 : Optimiser les shared pickups
            phase1_result = await self._execute_phase1_shared_pickups(optimization_data)
            
            # 3. PHASE 2 : Préparer et exécuter OR-Tools
            phase2_result = await self._execute_phase2_or_tools(optimization_data, phase1_result)
            
            # 4. PHASE 2b : Résoudre avec OR-Tools VRP V3.0 (NOUVEAU)
            phase2_result = await self._execute_or_tools_v3_direct(optimization_data, phase1_result)
            
            # 4. Combiner les résultats des 2 phases
            final_result = self._combine_optimization_phases(
                optimization_data, phase1_result, phase2_result
            )
            
            logger.info("Two-phase optimization completed successfully",
                       route_id=route_id,
                       phase1_stops=len(phase1_result.get("optimized_stops", [])),
                       phase2_stops=len(phase2_result.get("or_tools_stops", [])),
                       total_distance=final_result.get("total_distance_km"))
            
            return final_result
            
        except Exception as e:
            logger.error("Error in two-phase optimization", 
                        route_id=route_id, 
                        error=str(e))
            raise TwoPhaseOptimizerError(f"Erreur lors de l'optimisation 2 phases: {str(e)}")
    
    async def _execute_phase1_shared_pickups(self, optimization_data: Dict) -> Dict:
        """
        Phase 1 : Optimisation GPS des shared pickups
        
        Args:
            optimization_data: Données complètes d'optimisation
            
        Returns:
            Dict: Résultat de l'optimisation shared pickups
        """
        logger.info("Executing Phase 1: Shared Pickups Optimization")
        
        # Identifier les stops avec shared pickups
        all_stops = optimization_data["stops"]
        shared_pickup_stops = [
            stop for stop in all_stops 
            if stop.get("is_shared_pickup_stop", False)
        ]
        
        logger.info("Identified shared pickup stops", count=len(shared_pickup_stops))
        
        if not shared_pickup_stops:
            logger.info("No shared pickup stops found, skipping Phase 1")
            return {
                "optimized_stops": [],
                "total_distance_km": 0,
                "optimization_method": "no_shared_pickups",
                "phase_skipped": True
            }
        
        # Utiliser start_location comme point de départ pour shared pickups
        start_location_coords = {
            "latitude": optimization_data["start_location"]["latitude"],
            "longitude": optimization_data["start_location"]["longitude"],
            "address": optimization_data["start_location"]["formatted_address"]
        }
        
        # Optimiser avec le service shared pickups
        phase1_result = self.shared_pickup_optimizer.optimize_shared_pickup_sequence(
            start_location_coords, shared_pickup_stops
        )
        
        # Valider le résultat
        validation = self.shared_pickup_optimizer.validate_shared_pickup_data(
            phase1_result["optimized_stops"]
        )
        
        phase1_result["validation"] = validation
        phase1_result["phase"] = "shared_pickups"
        
        logger.info("Phase 1 completed",
                   optimized_stops=len(phase1_result["optimized_stops"]),
                   total_distance=phase1_result["total_distance_km"],
                   data_quality=validation["data_quality_score"])
        
        return phase1_result
    
    async def _execute_phase2_or_tools(self, optimization_data: Dict, phase1_result: Dict) -> Dict:
        """
        Phase 2 : Préparation et exécution OR-Tools
        
        Args:
            optimization_data: Données complètes d'optimisation
            phase1_result: Résultat de la Phase 1
            
        Returns:
            Dict: Données filtrées et préparées pour OR-Tools
        """
        logger.info("Executing Phase 2: OR-Tools Preparation")
        
        # Filtrer les données pour OR-Tools
        or_tools_data = self.or_tools_filter.filter_data_for_or_tools(
            optimization_data, phase1_result
        )
        
        # Calculer l'offset des stop_order pour OR-Tools
        stop_order_offset = self.or_tools_filter.get_stop_order_offset(phase1_result)
        
        # Générer la matrice de distances pour OR-Tools
        if or_tools_data["stops"]:
            matrix_result = await self.osrm_service.generate_distance_matrix_with_start_location(
                or_tools_data["stops"],
                or_tools_data["start_location"]
            )
            or_tools_data["distance_matrix"] = matrix_result
        else:
            logger.warning("No stops for OR-Tools optimization")
            or_tools_data["distance_matrix"] = None
        
        # Préparer le package final pour OR-Tools
        phase2_result = {
            "phase": "or_tools_preparation",
            "or_tools_data": or_tools_data,
            "stop_order_offset": stop_order_offset,
            "ready_for_or_tools": or_tools_data["metadata"]["ready_for_or_tools"],
            "or_tools_stops": or_tools_data["stops"],
            "or_tools_shipments": or_tools_data["shipments"],
            "distance_matrix_generated": or_tools_data["distance_matrix"] is not None
        }
        
        logger.info("Phase 2 completed",
                   or_tools_stops=len(or_tools_data["stops"]),
                   or_tools_shipments=len(or_tools_data["shipments"]),
                   stop_order_offset=stop_order_offset,
                   ready_for_or_tools=phase2_result["ready_for_or_tools"])
        
        return phase2_result
    
    async def _execute_or_tools_solver(self, phase2_result: Dict) -> Dict:
        """
        Phase 2b : Exécution du solveur OR-Tools VRP
        
        Args:
            phase2_result: Résultat de la préparation Phase 2
            
        Returns:
            Dict: Résultat avec solution OR-Tools
        """
        logger.info("Executing Phase 2b: OR-Tools VRP Solver")
        
        try:
            or_tools_data = phase2_result["or_tools_data"]
            
            # Résoudre avec OR-Tools
            vrp_solution = self.or_tools_solver.solve_vehicle_routing_problem(or_tools_data)
            
            # Enrichir le résultat Phase 2 avec la solution OR-Tools
            phase2_result["or_tools_solution"] = vrp_solution
            phase2_result["solution_found"] = vrp_solution["optimization_metadata"]["solution_found"]
            phase2_result["objective_value"] = vrp_solution.get("objective_value", float('inf'))
            phase2_result["optimized_stops"] = vrp_solution.get("optimized_stops", [])
            phase2_result["total_distance_km"] = vrp_solution.get("total_distance_km", 0)
            phase2_result["total_time_hours"] = vrp_solution.get("total_time_hours", 0)
            
            # Ajuster les stop_order avec l'offset des shared pickups
            if vrp_solution.get("optimized_stops"):
                stop_order_offset = phase2_result.get("stop_order_offset", 1)
                for stop in phase2_result["optimized_stops"]:
                    stop["final_stop_order"] = stop["stop_order"] + stop_order_offset - 1
            
            logger.info("OR-Tools VRP solver completed",
                       solution_found=phase2_result["solution_found"],
                       optimized_stops=len(phase2_result["optimized_stops"]),
                       objective_value=phase2_result["objective_value"],
                       total_distance_km=phase2_result["total_distance_km"])
            
            return phase2_result
            
        except Exception as e:
            logger.error("Error in OR-Tools VRP solver", error=str(e))
            
            # Ajouter les informations d'erreur
            phase2_result["or_tools_solution"] = {
                "optimization_metadata": {
                    "solution_found": False,
                    "error": str(e)
                }
            }
            phase2_result["solution_found"] = False
            phase2_result["error"] = str(e)
            
            return phase2_result
    
    def _combine_optimization_phases(self, optimization_data: Dict, 
                                   phase1_result: Dict, phase2_result: Dict) -> Dict:
        """
        Combine les résultats des 2 phases d'optimisation avec reconstruction UUID-conformante
        
        Args:
            optimization_data: Données originales
            phase1_result: Résultat Phase 1
            phase2_result: Résultat Phase 2
            
        Returns:
            Dict: Résultat combiné des 2 phases avec tournée reconstruite et conformité UUID
        """
        logger.info("Combining optimization phases with UUID-conformant reconstruction")
        
        # 🆕 RECONSTRUCTION UUID-CONFORMANTE AVEC TRAÇABILITÉ COMPLÈTE
        # Utiliser le reconstructor qui a accès au UUID tracker initialisé
        reconstruction_result = self.tour_reconstructor_v2.reconstruct_with_uuid_conformity(
            original_stops=optimization_data["stops"],
            original_shipments=optimization_data["shipments"], 
            phase1_stops=phase1_result.get("optimized_stops", []),
            phase2_stops=phase2_result.get("optimized_stops", [])
        )
        
        # Vérifier la conformité UUID
        if not reconstruction_result["success"]:
            logger.error("UUID conformity FAILED during reconstruction",
                        issues=reconstruction_result["conformity_report"]["issues"])
            # Continuer avec le résultat mais marquer l'erreur
        
        reconstructed_tour = reconstruction_result["reconstructed_tour"]
        
        # Calculer les statistiques globales
        total_distance_km = (
            phase1_result.get("total_distance_km", 0) +
            phase2_result.get("total_distance_km", 0)
        )
        
        combined_result = {
            "route_id": optimization_data["route"]["id"],
            "driver_id": optimization_data["driver"]["id"],
            "optimization_method": "two_phase_uuid_conformant",
            "total_distance_km": total_distance_km,
            
            # Phase 1 : Shared Pickups
            "phase1_shared_pickups": {
                "completed": not phase1_result.get("phase_skipped", False),
                "optimized_stops": phase1_result.get("optimized_stops", []),
                "distance_km": phase1_result.get("total_distance_km", 0),
                "optimization_method": phase1_result.get("optimization_method"),
                "data_quality_score": phase1_result.get("validation", {}).get("data_quality_score", 0)
            },
            
            # Phase 2 : OR-Tools avec reconstruction UUID-conformante
            "phase2_or_tools": {
                "ready": phase2_result.get("ready_for_or_tools", False),
                "solution_found": phase2_result.get("solution_found", False),
                "stops_count": len(phase2_result.get("or_tools_stops", [])),
                "shipments_count": len(phase2_result.get("or_tools_shipments", [])),
                "optimized_stops": reconstructed_tour,  # 🆕 Tournée UUID-conformante
                "stop_order_offset": phase2_result.get("stop_order_offset", 1),
                "distance_matrix_ready": phase2_result.get("distance_matrix_generated", False),
                "total_distance_km": phase2_result.get("total_distance_km", 0),
                "total_time_hours": phase2_result.get("total_time_hours", 0),
                "objective_value": phase2_result.get("objective_value", float('inf')),
                "or_tools_solution": phase2_result.get("or_tools_solution"),
                "or_tools_data": phase2_result.get("or_tools_data"),
                
                # 🆕 MÉTADONNÉES DE RECONSTRUCTION UUID-CONFORMANTE
                "reconstruction_metadata": {
                    "uuid_conformity": reconstruction_result["conformity_report"],
                    "conversion_summary": reconstruction_result["conversion_summary"],
                    "save_plan": reconstruction_result["save_plan"],
                    "audit_report": reconstruction_result["audit_report"],
                    "reconstruction_success": reconstruction_result["success"]
                }
            },
            
            # Métadonnées globales
            "metadata": {
                "original_stops": len(optimization_data["stops"]),
                "original_shipments": len(optimization_data["shipments"]),
                "shared_pickup_stops": len(phase1_result.get("optimized_stops", [])),
                "or_tools_stops": len(phase2_result.get("or_tools_stops", [])),
                "optimization_phases": 2,
                "start_location": optimization_data["start_location"],
                "driver_start_time": optimization_data["driver"]["start_time"]
            },
            
            # Instructions pour la suite
            "next_steps": {
                "shared_pickups_optimized": True,
                "or_tools_ready": phase2_result.get("ready_for_or_tools", False),
                "or_tools_solved": phase2_result.get("solution_found", False),
                "distance_matrix_available": phase2_result.get("distance_matrix_generated", False),
                "optimization_complete": (
                    phase1_result.get("optimized_stops", []) and
                    phase2_result.get("solution_found", False)
                ),
                "final_sequence_ready": len(phase2_result.get("optimized_stops", [])) > 0
            }
        }
        
        logger.info("Phases combined successfully",
                   total_stops_phase1=len(phase1_result.get("optimized_stops", [])),
                   total_stops_phase2=len(phase2_result.get("or_tools_stops", [])),
                   total_distance=total_distance_km,
                   optimization_complete=combined_result["next_steps"]["optimization_complete"])
        
        return combined_result
    
    async def _get_driver_coordinates(self, driver_id: str) -> Dict:
        """
        Récupère les coordonnées du driver depuis la table drivers
        
        Args:
            driver_id: ID du driver
            
        Returns:
            Dict: Coordonnées du driver
        """
        try:
            driver_result = self.data_retriever.drivers_repo.get_driver_with_start_info(driver_id)
            
            if driver_result["status"] != "success" or not driver_result["data"]:
                raise TwoPhaseOptimizerError(f"Driver non trouvé: {driver_id}")
            
            driver_data = driver_result["data"][0]
            
            # Les coordonnées sont dans la table drivers
            return {
                "id": driver_data["id"],
                "name": driver_data.get("name"),
                "start_latitude": driver_data.get("latitude"),  # Coordonnées dans drivers
                "start_longitude": driver_data.get("longitude"),
                "start_address": driver_data.get("start_address"),
                "start_time": driver_data.get("start_time")
            }
            
        except Exception as e:
            logger.error("Error retrieving driver coordinates", 
                        driver_id=driver_id, 
                        error=str(e))
            raise TwoPhaseOptimizerError(f"Erreur lors de la récupération des coordonnées du driver: {str(e)}")
    
    def get_optimization_summary(self, result: Dict) -> Dict:
        """
        Génère un résumé de l'optimisation 2 phases
        
        Args:
            result: Résultat de l'optimisation 2 phases
            
        Returns:
            Dict: Résumé formaté
        """
        return {
            "route_id": result["route_id"],
            "driver_id": result["driver_id"],
            "optimization_summary": {
                "method": "Two-Phase Optimization",
                "phase1_shared_pickups": {
                    "enabled": result["phase1_shared_pickups"]["completed"],
                    "stops_optimized": len(result["phase1_shared_pickups"]["optimized_stops"]),
                    "distance_km": result["phase1_shared_pickups"]["distance_km"]
                },
                "phase2_or_tools": {
                    "ready": result["phase2_or_tools"]["ready"],
                    "stops_to_optimize": result["phase2_or_tools"]["stops_count"],
                    "shipments_to_optimize": result["phase2_or_tools"]["shipments_count"]
                },
                "total_distance_km": result["total_distance_km"],
                "optimization_complete": result["next_steps"]["optimization_complete"]
            }
        }
    
    async def _execute_or_tools_v3_direct(self, optimization_data: Dict, phase1_result: Dict) -> Dict:
        """
        Phase 2b NOUVEAU : Exécution directe OR-Tools V3.0 (distance PURE + OSRM intégré)
        
        Cette méthode inclut désormais l'expansion des shipments AVANT OR-Tools pour 
        créer les contraintes pickup/delivery correctes et préserver les UUID pour
        la reconstruction finale de la tournée.
        
        Args:
            optimization_data: Données complètes d'optimisation
            phase1_result: Résultat de la Phase 1 (shared pickups)
            
        Returns:
            Dict: Résultat avec solution OR-Tools V3.0
        """
        logger.info("Executing OR-Tools V3.0 - Direct Integration (Distance PURE + Shipment Expansion)")
        
        try:
            # 1. Filtrer les stops et shipments (exclure shared pickups déjà optimisés)
            all_stops = optimization_data["stops"]
            all_shipments = optimization_data["shipments"]
            
            # IDs des stops déjà optimisés en Phase 1
            phase1_optimized_ids = set(
                stop["id"] for stop in phase1_result.get("optimized_stops", [])
            )
            
            # Stops filtrés : logique correcte pour Phase 2 OR-Tools
            filtered_stops = []
            for stop in all_stops:
                stop_id = stop["id"]
                stop_type = stop.get("stop_type", "")
                is_shared_pickup = stop.get("is_shared_pickup_stop", False)
                
                # RÈGLE 1: Exclure les stops déjà optimisés en Phase 1 (shared pickups)
                if stop_id in phase1_optimized_ids:
                    logger.debug("Excluding stop already in Phase 1", 
                               stop_id=stop_id[:8], stop_type=stop_type)
                    continue
                
                # RÈGLE 2: Exclure TOUS les pickup stops shared (même s'ils ne sont pas en Phase 1)
                if is_shared_pickup and stop_type in ["depot_pickup", "lab_pickup"]:
                    logger.debug("Excluding shared pickup stop from OR-Tools",
                               stop_id=stop_id[:8], stop_type=stop_type, is_shared=is_shared_pickup)
                    continue
                
                # RÈGLE 3: INCLURE tous les autres stops (y compris delivery stops)
                filtered_stops.append(stop)
                logger.debug("Including stop in OR-Tools",
                           stop_id=stop_id[:8], stop_type=stop_type, is_shared=is_shared_pickup)
            
            # Shipments filtrés : exclure les shared pickups  
            filtered_shipments = [
                shipment for shipment in all_shipments
                if not shipment.get("is_shared_pickup_stop", False)
            ]
            
            logger.info("Data filtered for OR-Tools V3.0",
                       original_stops=len(all_stops),
                       filtered_stops=len(filtered_stops),
                       original_shipments=len(all_shipments),
                       filtered_shipments=len(filtered_shipments))
            
            # 2. EXPANSION DES SHIPMENTS (NOUVEAU - AVANT OR-Tools) avec UUID TRACKING
            logger.info("Expanding shipments into OR-Tools nodes + constraints with UUID tracking")
            
            # Initialiser le tracking UUID avec les données originales
            self.uuid_tracker.initialize_tracking(optimization_data["stops"], optimization_data["shipments"])
            
            expansion_result = self.shipment_expander.expand_shipments_for_ortools(
                filtered_shipments, filtered_stops
            )
            
            # Récupérer les données expandues et tracker les expanded créés
            expanded_stops = expansion_result["expanded_stops"]
            for stop in expanded_stops:
                if "_expanded_" in stop["id"]:
                    real_id = stop["id"].split("_expanded_")[0]
                    self.uuid_tracker.track_expanded_creation(
                        real_id=real_id,
                        expanded_id=stop["id"],
                        expanded_data=stop,
                        reason="shipment_expansion_for_ortools"
                    )
            pickup_delivery_constraints = expansion_result["pickup_delivery_constraints"]
            expansion_metadata = expansion_result["expansion_metadata"]
            
            logger.info("Shipment expansion completed",
                       original_shipments=len(filtered_shipments),
                       expanded_stops=len(expanded_stops),
                       pickup_delivery_constraints=len(pickup_delivery_constraints),
                       stop_multiplications=len(expansion_metadata["stop_multiplications"]))
            
            # 3. Start location (point de rendez-vous)
            start_location = optimization_data["start_location"]
            
            logger.info("Using start_location for OR-Tools V3.0",
                       start_location_id=start_location["id"],
                       coordinates=f"{start_location['latitude']}, {start_location['longitude']}",
                       address=start_location["formatted_address"][:50])
            
            # 4. Appel au solveur V3.0 avec données expandues
            logger.info("Calling OR-Tools VRP V3.0 solver with expanded data")
            vrp_solution = await self.or_tools_solver_v3.solve_vehicle_routing_problem(
                filtered_stops=expanded_stops,  # CHANGÉ: stops expandus
                shipments=filtered_shipments,   # Shipments originaux pour métadonnées
                start_location=start_location,
                pickup_delivery_constraints=pickup_delivery_constraints  # NOUVEAU: contraintes
            )
            
            # 4. Construire le résultat Phase 2 dans le format attendu
            phase2_result = {
                "phase": "or_tools_v3_direct",
                "method": "distance_pure_osrm_integrated",
                
                # Données d'entrée
                "or_tools_stops": filtered_stops,
                "or_tools_shipments": filtered_shipments,
                "start_location_used": start_location,
                
                # Solution OR-Tools V3.0
                "or_tools_solution": vrp_solution,
                "solution_found": vrp_solution.get("optimization_metadata", {}).get("solution_found", False),
                "objective_value": vrp_solution.get("objective_value", float('inf')),
                "optimized_stops": vrp_solution.get("optimized_stops", []),
                "total_distance_km": vrp_solution.get("total_distance_km", 0),
                "total_time_hours": vrp_solution.get("total_time_hours", 0),
                
                # Métadonnées V3.0
                "solver_version": "OR-Tools VRP V3.0",
                "optimization_focus": vrp_solution.get("optimization_focus", "distance_pure"),
                "marseille_constraints": vrp_solution.get("marseille_stops_count", 0),
                "pickup_delivery_pairs": vrp_solution.get("pickup_delivery_pairs_satisfied", 0),
                
                # Compatibilité avec ancien format
                "ready_for_or_tools": True,
                "distance_matrix_generated": True,  # Géré par OSRM intégré
                "stop_order_offset": len(phase1_result.get("optimized_stops", [])) + 1
            }
            
            # 5. Ajuster les stop_order avec l'offset des shared pickups
            if vrp_solution.get("optimized_stops"):
                stop_order_offset = phase2_result["stop_order_offset"]
                for stop in phase2_result["optimized_stops"]:
                    original_order = stop.get("stop_order", 1)
                    stop["final_stop_order"] = original_order + stop_order_offset - 1
                    
                    logger.debug("Stop order adjusted",
                               stop_id=stop["id"][:20],
                               original_order=original_order,
                               final_order=stop["final_stop_order"],
                               offset=stop_order_offset)
            
            logger.info("OR-Tools V3.0 direct execution completed",
                       solution_found=phase2_result["solution_found"],
                       optimized_stops=len(phase2_result["optimized_stops"]),
                       objective_value=phase2_result["objective_value"],
                       total_distance_km=phase2_result["total_distance_km"],
                       solver=phase2_result["solver_version"])
            
            return phase2_result
            
        except ORToolsVRPV3Error as e:
            logger.error("OR-Tools V3.0 specific error", error=str(e))
            return self._create_v3_error_result(str(e), "or_tools_v3_error")
            
        except Exception as e:
            logger.error("Unexpected error in OR-Tools V3.0 direct execution", error=str(e))
            return self._create_v3_error_result(str(e), "unexpected_error")
    
    def _create_v3_error_result(self, error_message: str, error_type: str) -> Dict:
        """
        Crée un résultat d'erreur pour OR-Tools V3.0
        
        Args:
            error_message: Message d'erreur
            error_type: Type d'erreur
            
        Returns:
            Dict: Résultat d'erreur formaté
        """
        return {
            "phase": "or_tools_v3_direct",
            "method": "distance_pure_osrm_integrated",
            
            # Solution vide
            "or_tools_solution": {
                "optimized_stops": [],
                "objective_value": float('inf'),
                "optimization_metadata": {
                    "solver": "OR-Tools VRP V3.0",
                    "solution_found": False,
                    "error": error_message,
                    "error_type": error_type
                }
            },
            
            # État d'erreur
            "solution_found": False,
            "objective_value": float('inf'),
            "optimized_stops": [],
            "total_distance_km": 0,
            "total_time_hours": 0,
            
            # Métadonnées
            "solver_version": "OR-Tools VRP V3.0",
            "error_occurred": True,
            "error_message": error_message,
            "error_type": error_type,
            
            # Compatibilité
            "ready_for_or_tools": False,
            "distance_matrix_generated": False,
            "stop_order_offset": 1
        }


class TwoPhaseOptimizerError(Exception):
    """Exception levée lors d'erreurs d'optimisation 2 phases"""
    pass