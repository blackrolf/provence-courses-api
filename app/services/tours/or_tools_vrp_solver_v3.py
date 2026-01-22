"""
Solveur OR-Tools VRP V3.0 - Optimisation distance PURE avec OSRM intégré
Architecture simplifiée : OR-Tools + OSRM direct + Contraintes Marseille 1h30 minimum
"""

import structlog
import httpx
import asyncio
import time
from typing import Dict, List, Tuple, Any, Optional
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

from app.services.tours.osrm_distance_matrix import OSRMDistanceMatrixService

logger = structlog.get_logger()


class ORToolsVRPSolverV3:
    """
    Solveur VRP V3.0 - Distance PURE avec OSRM intégré
    
    Objectifs:
    - Optimisation 100% DISTANCE (pas de pondération temps)
    - OSRM intégré directement dans OR-Tools
    - Dimension temps UNIQUEMENT pour contraintes Marseille (1h30 minimum)
    - Traçabilité UUID complète
    - Architecture simplifiée
    """
    
    def __init__(self):
        # Configuration OSRM
        self.osrm_url = "http://localhost:5000"
        
        # Paramètres OR-Tools
        self.TIME_LIMIT_SECONDS = 15  # Réduit de 60 à 15 secondes
        self.SERVICE_TIME_SECONDS = 5
        
        # Contraintes Marseille : 1h30 MINIMUM (5400 secondes)
        self.MARSEILLE_MIN_TIME_SECONDS = 90 * 60  # 1h30 = 5400s
        self.MARSEILLE_POSTAL_CODES = ["13001", "13006", "13012", "13013", "13014", "13015"]
        
        # Configuration pure distance
        self.OPTIMIZE_DISTANCE_ONLY = True
        
    async def solve_vehicle_routing_problem(self, filtered_stops: List[Dict], 
                                          shipments: List[Dict], 
                                          start_location: Dict,
                                          pickup_delivery_constraints: List[Dict] = None) -> Dict:
        """
        Résout le VRP avec optimisation distance PURE
        
        Args:
            filtered_stops: Stops filtrés (sans shared pickups)
            shipments: Shipments avec contraintes pickup/delivery
            start_location: Point de rendez-vous (meeting point)
            pickup_delivery_constraints: Contraintes pickup/delivery depuis shipment_expander
            
        Returns:
            Dict: Solution optimisée avec UUID réels préservés
        """
        logger.info("Starting OR-Tools VRP V3.0 - Distance PURE optimization")
        start_time = time.time()
        
        try:
            # 1. Construire les matrices OSRM directement
            logger.info("Building OSRM matrices", stops_count=len(filtered_stops))
            distance_matrix, duration_matrix, stops_mapping = await self._build_osrm_matrices(
                filtered_stops, start_location
            )
            
            # 2. Préparer les données VRP
            vrp_data = self._prepare_vrp_data(
                distance_matrix, duration_matrix, stops_mapping, 
                filtered_stops, shipments, pickup_delivery_constraints
            )
            
            # 3. Créer et résoudre le modèle OR-Tools
            manager, routing, solution = await self._create_and_solve_vrp_model(vrp_data)
            
            if solution:
                # 4. Extraire la solution avec UUID préservés
                optimized_solution = self._extract_solution_with_uuids(
                    manager, routing, solution, vrp_data, filtered_stops
                )
                
                processing_time = time.time() - start_time
                optimized_solution["optimization_metadata"] = {
                    "solver": "OR-Tools VRP V3.0 - Distance PURE",
                    "processing_time_seconds": round(processing_time, 2),
                    "solution_found": True,
                    "objective_value": solution.ObjectiveValue(),
                    "optimization_focus": "distance_only",
                    "marseille_constraint": f"{self.MARSEILLE_MIN_TIME_SECONDS/60:.0f}min minimum",
                    "osrm_integration": "direct"
                }
                
                logger.info("OR-Tools VRP V3.0 completed successfully",
                           processing_time=processing_time,
                           objective_value=solution.ObjectiveValue(),
                           total_distance_m=optimized_solution.get("total_distance_meters", 0),
                           stops_optimized=len(optimized_solution.get("optimized_stops", [])))
                
                return optimized_solution
            else:
                logger.error("OR-Tools VRP V3.0: No solution found")
                return self._create_fallback_solution(filtered_stops, time.time() - start_time)
                
        except Exception as e:
            logger.error("Error in OR-Tools VRP V3.0 optimization", error=str(e))
            return self._create_error_solution(str(e), time.time() - start_time)
    
    async def _build_osrm_matrices(self, filtered_stops: List[Dict],
                                  start_location: Dict) -> Tuple[List[List[int]], List[List[int]], List[Dict]]:
        """
        Construit les matrices distance/durée via le service OSRM optimisé
        Utilise batching et retry pour éviter les timeouts

        Returns:
            Tuple: (distance_matrix, duration_matrix, stops_mapping)
        """
        logger.info("Building OSRM matrices for OR-Tools V3.0")

        # 1. Préparer la liste complète : start_location + filtered_stops
        all_stops = [start_location] + filtered_stops
        stops_mapping = []

        for i, stop in enumerate(all_stops):
            stops_mapping.append({
                "index": i,
                "stop_id": stop["id"],
                "stop_type": stop.get("stop_type", "start_location"),
                "location_id": stop.get("location_id"),
                "coordinates": [stop["longitude"], stop["latitude"]],
                "formatted_address": stop.get("formatted_address", ""),
                "is_start_location": i == 0
            })

        matrix_size = len(all_stops)
        depot_index = 0  # start_location toujours à l'index 0

        logger.info("Coordinates prepared for OSRM",
                   matrix_size=matrix_size,
                   depot_index=depot_index)

        # 2. Utiliser le service OSRM optimisé avec batching
        try:
            osrm_service = OSRMDistanceMatrixService()

            # Préparer les données pour le service
            stops_data = []
            for stop in all_stops:
                stops_data.append({
                    "id": stop["id"],
                    "latitude": stop["latitude"],
                    "longitude": stop["longitude"],
                    "stop_type": stop.get("stop_type", "start_location"),
                    "location_id": stop.get("location_id"),
                    "formatted_address": stop.get("formatted_address", "")
                })

            # Appeler le service optimisé
            matrix_result = await osrm_service.generate_distance_matrix_for_route(stops_data)

            # Convertir les résultats (peuvent contenir des None pour certaines cellules)
            distance_matrix = []
            duration_matrix = []

            for row in matrix_result["distance_matrix"]:
                distance_matrix.append([int(val) if val is not None else 10000 for val in row])

            for row in matrix_result["duration_matrix"]:
                duration_matrix.append([int(val) if val is not None else 600 for val in row])

            logger.info("OSRM matrices built successfully via optimized service",
                       matrix_size=f"{matrix_size}x{matrix_size}",
                       sample_distance=distance_matrix[0][1] if matrix_size > 1 else 0,
                       sample_duration=duration_matrix[0][1] if matrix_size > 1 else 0,
                       processing_time=matrix_result.get("osrm_metadata", {}).get("processing_time", 0))

            return distance_matrix, duration_matrix, stops_mapping

        except Exception as e:
            logger.error("Failed to build OSRM matrices via optimized service, using fallback",
                        error=str(e))
            # Fallback: matrices avec valeurs par défaut
            distance_matrix = [[10000 if i != j else 0 for j in range(matrix_size)] for i in range(matrix_size)]
            duration_matrix = [[600 if i != j else 0 for j in range(matrix_size)] for i in range(matrix_size)]
            return distance_matrix, duration_matrix, stops_mapping
    
    def _prepare_vrp_data(self, distance_matrix: List[List[int]], 
                         duration_matrix: List[List[int]], 
                         stops_mapping: List[Dict],
                         filtered_stops: List[Dict], 
                         shipments: List[Dict],
                         pickup_delivery_constraints: List[Dict] = None) -> Dict:
        """
        Prépare les données VRP pour OR-Tools V3.0
        """
        logger.info("Preparing VRP data for OR-Tools V3.0")
        
        matrix_size = len(stops_mapping)
        depot_index = 0
        
        # Identifier les stops Marseille avec contrainte 1h30 minimum
        marseille_stops = self._identify_marseille_stops(filtered_stops, stops_mapping)
        
        # Préparer les contraintes pickup/delivery
        if pickup_delivery_constraints:
            pickup_delivery_pairs = self._prepare_pickup_delivery_pairs_from_constraints(
                pickup_delivery_constraints, stops_mapping
            )
        else:
            # Fallback vers l'ancienne méthode si pas de contraintes fournies
            pickup_delivery_pairs = self._prepare_pickup_delivery_pairs(shipments, stops_mapping)
        
        vrp_data = {
            # Matrices OSRM
            "distance_matrix": distance_matrix,  # ← OBJECTIF PRINCIPAL
            "duration_matrix": duration_matrix,  # ← CONTRAINTE MARSEILLE
            
            # Structure OR-Tools
            "stops_mapping": stops_mapping,
            "depot_index": depot_index,
            "matrix_size": matrix_size,
            
            # Configuration véhicule
            "num_vehicles": 1,
            "vehicle_capacity": 1000,
            
            # Contraintes
            "pickup_delivery_pairs": pickup_delivery_pairs,
            "marseille_stops": marseille_stops,
            "service_times": [self.SERVICE_TIME_SECONDS] * matrix_size,
        }
        
        logger.info("VRP data prepared for V3.0",
                   matrix_size=matrix_size,
                   pickup_delivery_pairs=len(pickup_delivery_pairs),
                   marseille_stops=len(marseille_stops),
                   objective="distance_only")
        
        return vrp_data
    
    def _identify_marseille_stops(self, filtered_stops: List[Dict], 
                                 stops_mapping: List[Dict]) -> List[int]:
        """
        Identifie les stops Marseille (13001, 13006, 13012, 13013, 13014, 13015) avec contrainte 1h30 minimum
        """
        marseille_indices = []
        
        for mapping in stops_mapping:
            if mapping["is_start_location"]:
                continue
                
            stop_id = mapping["stop_id"]
            stop = next((s for s in filtered_stops if s["id"] == stop_id), None)
            
            if stop:
                address = stop.get("formatted_address", "")
                if any(code in address for code in self.MARSEILLE_POSTAL_CODES):
                    marseille_indices.append(mapping["index"])
                    logger.debug("Marseille stop identified",
                               stop_id=stop_id,
                               index=mapping["index"],
                               address=address[:50])
        
        logger.info("Marseille stops identified", 
                   count=len(marseille_indices),
                   constraint=f"{self.MARSEILLE_MIN_TIME_SECONDS/60:.0f}min minimum")
        
        return marseille_indices
    
    def _prepare_pickup_delivery_pairs_from_constraints(self, 
                                                       pickup_delivery_constraints: List[Dict],
                                                       stops_mapping: List[Dict]) -> List[Tuple[int, int]]:
        """
        Prépare les paires pickup/delivery à partir des contraintes de shipment_expander
        
        Args:
            pickup_delivery_constraints: Contraintes avec IDs expandus
            stops_mapping: Mapping des stops vers indices OR-Tools
            
        Returns:
            List[Tuple[int, int]]: Paires (pickup_index, delivery_index)
        """
        pairs = []
        stop_id_to_index = {mapping["stop_id"]: mapping["index"] for mapping in stops_mapping}
        
        for constraint in pickup_delivery_constraints:
            pickup_stop_id = constraint["pickup_stop_id"]
            delivery_stop_id = constraint["delivery_stop_id"]
            
            pickup_index = stop_id_to_index.get(pickup_stop_id)
            delivery_index = stop_id_to_index.get(delivery_stop_id)
            
            if pickup_index is not None and delivery_index is not None:
                pairs.append((pickup_index, delivery_index))
                logger.debug("Pickup/delivery pair from constraint",
                           shipment_ref=constraint.get("shipment_ref"),
                           pickup_stop_id=pickup_stop_id,
                           delivery_stop_id=delivery_stop_id,
                           pickup_index=pickup_index,
                           delivery_index=delivery_index)
            else:
                logger.warning("Could not map constraint to indices",
                             shipment_ref=constraint.get("shipment_ref"),
                             pickup_stop_id=pickup_stop_id,
                             delivery_stop_id=delivery_stop_id,
                             pickup_found=pickup_index is not None,
                             delivery_found=delivery_index is not None)
        
        logger.info("Pickup/delivery pairs from constraints", 
                   constraints_count=len(pickup_delivery_constraints),
                   pairs_created=len(pairs))
        return pairs
    
    def _prepare_pickup_delivery_pairs(self, shipments: List[Dict], 
                                     stops_mapping: List[Dict]) -> List[Tuple[int, int]]:
        """
        Prépare les paires pickup/delivery pour OR-Tools
        """
        pairs = []
        stop_id_to_index = {mapping["stop_id"]: mapping["index"] for mapping in stops_mapping}
        
        for shipment in shipments:
            constraint_type = shipment.get("or_tools_constraint_type")
            
            if constraint_type == "pickup_delivery":
                pickup_stop_id = shipment.get("pickup_stop_id")
                delivery_stop_id = shipment.get("delivery_stop_id")
                
                pickup_index = stop_id_to_index.get(pickup_stop_id)
                delivery_index = stop_id_to_index.get(delivery_stop_id)
                
                if pickup_index is not None and delivery_index is not None:
                    pairs.append((pickup_index, delivery_index))
                    logger.debug("Pickup/delivery pair added",
                               shipment_ref=shipment.get("shipment_ref"),
                               pickup_index=pickup_index,
                               delivery_index=delivery_index)
        
        logger.info("Pickup/delivery pairs prepared", count=len(pairs))
        return pairs
    
    async def _create_and_solve_vrp_model(self, vrp_data: Dict) -> Tuple[Any, Any, Any]:
        """
        Crée et résout le modèle OR-Tools VRP V3.0 - Distance PURE
        """
        logger.info("Creating OR-Tools VRP model V3.0 - Distance PURE")
        
        matrix_size = vrp_data["matrix_size"]
        num_vehicles = vrp_data["num_vehicles"]
        depot_index = vrp_data["depot_index"]
        
        # 1. Créer le manager et routing
        manager = pywrapcp.RoutingIndexManager(matrix_size, num_vehicles, depot_index)
        routing = pywrapcp.RoutingModel(manager)
        
        # 2. 🎯 CALLBACK DISTANCE PURE (objectif principal)
        def distance_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            return vrp_data["distance_matrix"][from_node][to_node]
        
        distance_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(distance_callback_index)
        
        logger.info("Distance objective set - 100% distance optimization")
        
        # 3. ⏱️ DIMENSION TEMPS (pour contraintes Marseille uniquement)
        def time_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            travel_time = vrp_data["duration_matrix"][from_node][to_node]
            service_time = vrp_data["service_times"][from_node]
            return travel_time + service_time
        
        time_callback_index = routing.RegisterTransitCallback(time_callback)
        routing.AddDimension(
            time_callback_index,
            300,  # Slack maximum (5 min)
            24 * 60 * 60,  # Capacité maximum (24h)
            False,  # Start cumul to zero
            "Time"
        )
        time_dimension = routing.GetDimensionOrDie("Time")
        
        # 4. 🚫 CONTRAINTES MARSEILLE - 1h30 MINIMUM
        for marseille_index in vrp_data["marseille_stops"]:
            node_index = manager.NodeToIndex(marseille_index)
            if node_index != -1:
                # Hard constraint : ne peut pas arriver avant 1h30 de tournée
                time_dimension.CumulVar(node_index).SetMin(self.MARSEILLE_MIN_TIME_SECONDS)
                logger.debug("Marseille constraint applied",
                           index=marseille_index,
                           min_time=f"{self.MARSEILLE_MIN_TIME_SECONDS/60:.0f}min")
        
        logger.info("Marseille constraints applied", 
                   count=len(vrp_data["marseille_stops"]),
                   min_time=f"{self.MARSEILLE_MIN_TIME_SECONDS/60:.0f}min")
        
        # 5. Contraintes pickup/delivery
        for pickup_index, delivery_index in vrp_data["pickup_delivery_pairs"]:
            pickup_node = manager.NodeToIndex(pickup_index)
            delivery_node = manager.NodeToIndex(delivery_index)
            
            if pickup_node != -1 and delivery_node != -1:
                routing.AddPickupAndDelivery(pickup_node, delivery_node)
                routing.solver().Add(
                    time_dimension.CumulVar(pickup_node) <= time_dimension.CumulVar(delivery_node)
                )
        
        logger.info("Pickup/delivery constraints applied", 
                   count=len(vrp_data["pickup_delivery_pairs"]))
        
        # 6. Dimension capacité
        def demand_callback(from_index):
            return 1
        
        demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimensionWithVehicleCapacity(
            demand_callback_index,
            0,
            [vrp_data["vehicle_capacity"]],
            True,
            "Capacity"
        )
        
        # 7. Paramètres de recherche
        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.time_limit.seconds = self.TIME_LIMIT_SECONDS
        search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
        search_parameters.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.TABU_SEARCH
        
        logger.info("OR-Tools V3.0 configuration loaded - Distance PURE optimization")
        
        # 8. Résoudre
        solution = routing.SolveWithParameters(search_parameters)
        
        return manager, routing, solution
    
    def _extract_solution_with_uuids(self, manager: Any, routing: Any, solution: Any,
                                    vrp_data: Dict, filtered_stops: List[Dict]) -> Dict:
        """
        Extrait la solution avec préservation complète des UUID
        """
        logger.info("Extracting OR-Tools V3.0 solution with UUID preservation")
        
        optimized_stops = []
        total_distance = 0
        total_time = 0
        
        time_dimension = routing.GetDimensionOrDie("Time")
        
        # Extraire la route
        vehicle_id = 0
        index = routing.Start(vehicle_id)
        
        while not routing.IsEnd(index):
            node_index = manager.IndexToNode(index)
            stop_mapping = vrp_data["stops_mapping"][node_index]
            
            time_var = time_dimension.CumulVar(index)
            time_value = solution.Value(time_var)
            
            # Récupérer le stop original par UUID
            stop_id = stop_mapping["stop_id"]
            if stop_mapping["is_start_location"]:
                # SKIP start_location - ce n'est pas un stop de la tournée
                logger.debug("Skipping start_location in solution", 
                           stop_id=stop_id[:8], 
                           node_index=node_index)
                index = solution.Value(routing.NextVar(index))
                continue
            else:
                # Stop normal
                original_stop = next(
                    (s for s in filtered_stops if s["id"] == stop_id), 
                    None
                )
            
            if original_stop:
                optimized_stop = {
                    # UUID préservés
                    "id": original_stop["id"],
                    "location_id": original_stop.get("location_id"),
                    
                    # Informations du stop
                    "stop_type": original_stop["stop_type"],
                    "stop_order": len(optimized_stops) + 1,
                    "latitude": original_stop["latitude"],
                    "longitude": original_stop["longitude"],
                    "formatted_address": original_stop["formatted_address"],
                    
                    # Données d'optimisation V3.0
                    "estimated_arrival_time": self._seconds_to_time_string(time_value),
                    "cumulative_time_seconds": time_value,
                    "or_tools_node_index": node_index,
                    "is_marseille_constraint": node_index in vrp_data["marseille_stops"],
                    
                    # Métadonnées
                    "optimization_method": "distance_pure_v3",
                    "shipment_ref": original_stop.get("shipment_ref"),
                    "shipment_action": original_stop.get("shipment_action")
                }
                
                optimized_stops.append(optimized_stop)
            
            # Calculer distances pour le segment suivant
            previous_index = index
            index = solution.Value(routing.NextVar(index))
            
            if not routing.IsEnd(index):
                from_node = node_index
                to_node = manager.IndexToNode(index)
                total_distance += vrp_data["distance_matrix"][from_node][to_node]
                total_time += vrp_data["duration_matrix"][from_node][to_node]
        
        # Ajouter distances entre stops consécutifs
        for i in range(len(optimized_stops)):
            if i > 0:
                from_node = optimized_stops[i-1]["or_tools_node_index"]
                to_node = optimized_stops[i]["or_tools_node_index"]
                optimized_stops[i]["distance_from_previous"] = vrp_data["distance_matrix"][from_node][to_node]
                optimized_stops[i]["duration_from_previous"] = vrp_data["duration_matrix"][from_node][to_node]
            else:
                optimized_stops[i]["distance_from_previous"] = 0
                optimized_stops[i]["duration_from_previous"] = 0
        
        solution_data = {
            "optimized_stops": optimized_stops,
            "total_distance_meters": total_distance,
            "total_distance_km": round(total_distance / 1000, 2),
            "total_time_seconds": total_time,
            "total_time_hours": round(total_time / 3600, 2),
            "objective_value": solution.ObjectiveValue(),
            "marseille_stops_count": len(vrp_data["marseille_stops"]),
            "pickup_delivery_pairs_satisfied": len(vrp_data["pickup_delivery_pairs"]),
            "optimization_focus": "distance_pure"
        }
        
        logger.info("OR-Tools V3.0 solution extracted",
                   stops_count=len(optimized_stops),
                   total_distance_km=solution_data["total_distance_km"],
                   objective_value=solution_data["objective_value"],
                   marseille_constraints=solution_data["marseille_stops_count"])
        
        return solution_data
    
    def _seconds_to_time_string(self, seconds: int) -> str:
        """Convertit secondes en string HH:MM"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours:02d}:{minutes:02d}"
    
    def _create_fallback_solution(self, filtered_stops: List[Dict], processing_time: float) -> Dict:
        """Crée une solution de fallback"""
        return {
            "optimized_stops": filtered_stops,
            "total_distance_meters": 0,
            "total_distance_km": 0,
            "total_time_seconds": 0,
            "total_time_hours": 0,
            "objective_value": float('inf'),
            "optimization_metadata": {
                "solver": "OR-Tools VRP V3.0 - Distance PURE",
                "processing_time_seconds": round(processing_time, 2),
                "solution_found": False,
                "fallback_used": True
            }
        }
    
    def _create_error_solution(self, error_message: str, processing_time: float) -> Dict:
        """Crée une solution d'erreur"""
        return {
            "optimized_stops": [],
            "total_distance_meters": 0,
            "total_distance_km": 0,
            "total_time_seconds": 0,
            "total_time_hours": 0,
            "objective_value": float('inf'),
            "optimization_metadata": {
                "solver": "OR-Tools VRP V3.0 - Distance PURE",
                "processing_time_seconds": round(processing_time, 2),
                "solution_found": False,
                "error": error_message
            }
        }


class ORToolsVRPV3Error(Exception):
    """Exception pour OR-Tools VRP V3.0"""
    pass