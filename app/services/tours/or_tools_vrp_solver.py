"""
Solveur OR-Tools VRP optimisé pour la logistique dentaire Provence
Version 2.0 - Refactorisé et corrigé
"""

import structlog
import time
from typing import Dict, List, Tuple, Any, Optional
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

logger = structlog.get_logger()


class ORToolsVRPSolver:
    """
    Solveur VRP optimisé et corrigé pour la logistique avec OR-Tools
    
    Corrections apportées :
    - Matrice composite pré-calculée (plus de callback à la volée)
    - Time windows hard constraints propres
    - Gestion correcte du depot_index  
    - Driver start time initialisé
    - Validation stricte sans overflow silencieux
    - Contraintes pickup/delivery uniquement pour les non-shared
    """
    
    def __init__(self):
        # ─── Paramètres généraux ─────────────────────────────────────────────
        self.TIME_LIMIT_SECONDS = 60
        self.SERVICE_TIME_SECONDS = 5
        self.RESTRICTED_ZONES_DELAY_MINUTES = 90  # 1h30 en minutes
        self.RESTRICTED_POSTAL_CODES = ["13001", "13006"]
        
        # 🔥 CORRECTION : Prioriser les distances (80% distance / 20% temps)
        self.DISTANCE_WEIGHT = 0.8
        self.TIME_WEIGHT = 0.2
        
        # Configuration hard constraints
        self.USE_HARD_CONSTRAINTS_FOR_RESTRICTED = True
        
    def solve_vehicle_routing_problem(self, or_tools_data: Dict) -> Dict:
        """
        Résout le problème VRP avec OR-Tools
        
        Args:
            or_tools_data: Données préparées et expandues par ORToolsDataFilter
            
        Returns:
            Dict: Solution optimisée avec séquence de stops
        """
        logger.info("Starting OR-Tools VRP optimization v2.0")
        start_time = time.time()
        
        try:
            # 1. Préparer les données pour OR-Tools
            vrp_data = self._prepare_vrp_data(or_tools_data)
            
            # 2. Créer et résoudre le modèle OR-Tools
            manager, routing, solution = self._create_and_solve_vrp_model(vrp_data)
            
            if solution:
                # 3. Extraire et formater la solution
                optimized_solution = self._extract_solution(
                    manager, routing, solution, vrp_data, or_tools_data
                )
                
                processing_time = time.time() - start_time
                optimized_solution["optimization_metadata"] = {
                    "solver": "OR-Tools VRP v2.0",
                    "processing_time_seconds": round(processing_time, 2),
                    "solution_found": True,
                    "objective_value": solution.ObjectiveValue(),
                    "time_limit_seconds": self.TIME_LIMIT_SECONDS
                }
                
                logger.info("OR-Tools VRP optimization completed successfully",
                           processing_time=processing_time,
                           objective_value=solution.ObjectiveValue(),
                           stops_optimized=len(optimized_solution.get("optimized_stops", [])))
                
                return optimized_solution
            else:
                logger.error("OR-Tools VRP: No solution found")
                return self._create_fallback_solution(or_tools_data, time.time() - start_time)
                
        except Exception as e:
            logger.error("Error in OR-Tools VRP optimization", error=str(e))
            return self._create_error_solution(str(e), time.time() - start_time)
    
    def _prepare_vrp_data(self, or_tools_data: Dict) -> Dict:
        """
        Prépare les données pour OR-Tools VRP
        
        Args:
            or_tools_data: Données filtrées et expandues du TwoPhaseOptimizer
            
        Returns:
            Dict: Données formatées pour OR-Tools
        """
        logger.info("Preparing VRP data for OR-Tools v2.0")
        
        stops = or_tools_data["stops"]
        shipments = or_tools_data["shipments"]
        distance_matrix_data = or_tools_data["distance_matrix"]
        constraints = or_tools_data["constraints"]
        
        # Valider la structure des données
        self._validate_input_data(stops, shipments, distance_matrix_data)
        
        # Extraire les matrices et mappings
        distance_matrix = distance_matrix_data["distance_matrix"]
        duration_matrix = distance_matrix_data["duration_matrix"]
        stops_mapping = distance_matrix_data["stops_mapping"]
        depot_index = distance_matrix_data["depot_index"]
        
        # 🔥 CORRECTION : Pré-calculer la matrice composite une seule fois
        composite_matrix = self._create_composite_matrix(distance_matrix, duration_matrix)
        
        # Identifier les stops avec restrictions géographiques
        restricted_stops = self._identify_restricted_stops(stops, stops_mapping)
        
        # Préparer les contraintes pickup/delivery (uniquement pour non-shared)
        pickup_delivery_pairs = self._prepare_pickup_delivery_pairs(shipments, stops_mapping)
        
        # Créer les time windows avec hard constraints
        time_windows = self._create_time_windows(
            stops, stops_mapping, constraints, restricted_stops
        )
        
        # 🔥 CORRECTION : Driver start time pour initialisation
        driver_start_time_str = constraints.get("time_windows", {}).get("driver_start_time", "19:00")
        driver_start_time_seconds = self._parse_time_to_seconds(driver_start_time_str)
        
        vrp_data = {
            # Matrices pré-calculées
            "composite_matrix": composite_matrix,
            "duration_matrix": duration_matrix,
            "distance_matrix": distance_matrix,
            
            # Structure OR-Tools
            "stops_mapping": stops_mapping,
            "depot_index": depot_index,
            "matrix_size": len(stops_mapping),
            
            # Configuration véhicule
            "num_vehicles": 1,
            "vehicle_capacities": [1000],
            
            # Contraintes
            "pickup_delivery_pairs": pickup_delivery_pairs,
            "time_windows": time_windows,
            "restricted_stops": restricted_stops,
            "service_times": [self.SERVICE_TIME_SECONDS] * len(stops_mapping),
            "driver_start_time_seconds": driver_start_time_seconds,
        }
        
        logger.info("VRP data prepared",
                   matrix_size=vrp_data["matrix_size"],
                   pickup_delivery_pairs=len(pickup_delivery_pairs),
                   restricted_stops=len(restricted_stops),
                   depot_index=depot_index,
                   composite_matrix_ready=True)
        
        return vrp_data
    
    def _validate_input_data(self, stops: List[Dict], shipments: List[Dict], 
                           distance_matrix_data: Dict) -> None:
        """
        Valide les données d'entrée et lève des exceptions si problème
        
        Args:
            stops: Liste des stops
            shipments: Liste des shipments  
            distance_matrix_data: Données de matrice de distances
        """
        if not stops:
            raise ORToolsVRPError("Aucun stop fourni pour OR-Tools")
            
        if not distance_matrix_data:
            raise ORToolsVRPError("Aucune matrice de distances fournie")
            
        required_keys = ["distance_matrix", "duration_matrix", "stops_mapping", "depot_index"]
        for key in required_keys:
            if key not in distance_matrix_data:
                raise ORToolsVRPError(f"Clé manquante dans distance_matrix_data: {key}")
        
        distance_matrix = distance_matrix_data["distance_matrix"]
        duration_matrix = distance_matrix_data["duration_matrix"]
        
        if not distance_matrix or not duration_matrix:
            raise ORToolsVRPError("Matrices distance ou duration vides")
            
        # Validation taille des matrices
        matrix_size = len(distance_matrix)
        if len(duration_matrix) != matrix_size:
            raise ORToolsVRPError(f"Tailles matrices incompatibles: distance={matrix_size}, duration={len(duration_matrix)}")
            
        for i, (dist_row, dur_row) in enumerate(zip(distance_matrix, duration_matrix)):
            if len(dist_row) != matrix_size or len(dur_row) != matrix_size:
                raise ORToolsVRPError(f"Ligne {i} matrice invalide: distance={len(dist_row)}, duration={len(dur_row)}, attendu={matrix_size}")
        
        logger.info("Input data validation passed", 
                   stops=len(stops), 
                   shipments=len(shipments),
                   matrix_size=matrix_size)
    
    def _create_composite_matrix(self, distance_matrix: List[List[int]], 
                                duration_matrix: List[List[int]]) -> List[List[int]]:
        """
        🔥 CORRECTION : Crée la matrice composite pré-calculée (70% temps + 30% distance)
        
        Args:
            distance_matrix: Matrice distances en mètres
            duration_matrix: Matrice durées en secondes
            
        Returns:
            List[List[int]]: Matrice composite pour optimisation
        """
        size = len(distance_matrix)
        composite_matrix = []
        
        for i in range(size):
            row = []
            for j in range(size):
                if i == j:
                    composite_cost = 0  # Diagonale toujours à zéro
                else:
                    # 🔥 CORRECTION : 80% distance + 20% temps, normalisé pour éviter 0
                    distance_cost = distance_matrix[i][j] * self.DISTANCE_WEIGHT
                    time_cost = duration_matrix[i][j] * self.TIME_WEIGHT
                    composite_cost = max(1, int(distance_cost + time_cost))
                
                row.append(composite_cost)
            composite_matrix.append(row)
        
        logger.info("Composite matrix created", 
                   size=f"{size}x{size}",
                   sample_values={
                       "diagonal_0_0": composite_matrix[0][0],
                       "edge_0_1": composite_matrix[0][1] if size > 1 else None
                   })
        
        return composite_matrix
    
    def _identify_restricted_stops(self, stops: List[Dict], stops_mapping: List[Dict]) -> List[int]:
        """
        Identifie les stops dans les zones restreintes (13001, 13006)
        """
        restricted_indices = []
        
        for mapping in stops_mapping:
            stop_id = mapping["stop_id"]
            stop = next((s for s in stops if s["id"] == stop_id), None)
            
            if stop:
                address = stop.get("formatted_address", "")
                if any(code in address for code in self.RESTRICTED_POSTAL_CODES):
                    restricted_indices.append(mapping["index"])
                    logger.debug("Restricted stop identified",
                               stop_id=stop_id,
                               index=mapping["index"],
                               address=address[:50])
        
        logger.info("Restricted stops identified", count=len(restricted_indices))
        return restricted_indices
    
    def _prepare_pickup_delivery_pairs(self, shipments: List[Dict], 
                                     stops_mapping: List[Dict]) -> List[Tuple[int, int]]:
        """
        🔥 CORRECTION : Prépare les paires pickup/delivery UNIQUEMENT pour les non-shared
        
        Args:
            shipments: Shipments filtrés (shared déjà exclus)
            stops_mapping: Mapping OR-Tools
            
        Returns:
            List[Tuple[int, int]]: Paires (pickup_index, delivery_index)
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
                    # Validation stricte des indices
                    if (pickup_index >= len(stops_mapping) or delivery_index >= len(stops_mapping) or
                        pickup_index < 0 or delivery_index < 0):
                        raise ORToolsVRPError(f"Index pickup/delivery invalide: pickup={pickup_index}, delivery={delivery_index}, matrix_size={len(stops_mapping)}")
                    
                    pairs.append((pickup_index, delivery_index))
                    logger.debug("Pickup/delivery pair added",
                               shipment_ref=shipment.get("shipment_ref"),
                               pickup_index=pickup_index,
                               delivery_index=delivery_index)
                else:
                    raise ORToolsVRPError(f"Stop IDs non trouvés pour pickup/delivery: pickup_stop_id={pickup_stop_id}, delivery_stop_id={delivery_stop_id}")
            
            # Note: delivery_only n'a pas besoin de contraintes pickup/delivery
        
        logger.info("Pickup/delivery pairs prepared", count=len(pairs))
        return pairs
    
    def _create_time_windows(self, stops: List[Dict], stops_mapping: List[Dict], 
                           constraints: Dict, restricted_stops: List[int]) -> List[Tuple[int, int]]:
        """
        Crée les time windows pour les stops
        """
        time_windows = []
        MAX_TIME = 24 * 60 * 60  # 24h en secondes
        
        for mapping in stops_mapping:
            index = mapping["index"]
            
            if index in restricted_stops:
                # Zone restreinte : time window commence après 90 min
                start_time = self.RESTRICTED_ZONES_DELAY_MINUTES * 60
                end_time = MAX_TIME
            else:
                # Zone normale : disponible dès le début
                start_time = 0
                end_time = MAX_TIME
            
            time_windows.append((start_time, end_time))
        
        logger.info("Time windows created",
                   total_windows=len(time_windows),
                   restricted_windows=len(restricted_stops))
        
        return time_windows
    
    def _parse_time_to_seconds(self, time_str: str) -> int:
        """Convertit une string HH:MM en secondes depuis minuit"""
        try:
            hours, minutes = map(int, time_str.split(':'))
            return hours * 3600 + minutes * 60
        except (ValueError, AttributeError):
            logger.warning("Invalid time format, using default 19:00", time_str=time_str)
            return 19 * 3600  # 19:00 par défaut
    
    def _create_and_solve_vrp_model(self, vrp_data: Dict) -> Tuple[Any, Any, Any]:
        """
        🔥 CORRECTION : Crée et résout le modèle OR-Tools VRP propre
        """
        logger.info("Creating OR-Tools VRP model v2.0")
        
        # 1. Créer le manager
        matrix_size = vrp_data["matrix_size"]
        num_vehicles = vrp_data["num_vehicles"]
        depot_index = vrp_data["depot_index"]
        
        manager = pywrapcp.RoutingIndexManager(matrix_size, num_vehicles, depot_index)
        routing = pywrapcp.RoutingModel(manager)
        
        # 2. 🔥 CALLBACK COMPOSITE PRÉ-CALCULÉ (plus rapide)
        def composite_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            
            # Validation stricte - lever exception au lieu de return 999999
            if from_node >= matrix_size or to_node >= matrix_size or from_node < 0 or to_node < 0:
                raise ORToolsVRPError(f"Node index hors limite: from={from_node}, to={to_node}, matrix_size={matrix_size}")
            
            return vrp_data["composite_matrix"][from_node][to_node]
        
        composite_callback_index = routing.RegisterTransitCallback(composite_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(composite_callback_index)
        
        # 3. Dimension temporelle
        def time_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            
            if from_node >= matrix_size or to_node >= matrix_size or from_node < 0 or to_node < 0:
                raise ORToolsVRPError(f"Time callback: node index hors limite: from={from_node}, to={to_node}")
                
            return (vrp_data["duration_matrix"][from_node][to_node] + 
                   vrp_data["service_times"][from_node])
        
        time_callback_index = routing.RegisterTransitCallback(time_callback)
        routing.AddDimension(
            time_callback_index,
            300,  # Slack maximum (5 min)
            24 * 60 * 60,  # Capacité maximum (24h)
            False,  # Start cumul to zero
            "Time"
        )
        time_dimension = routing.GetDimensionOrDie("Time")
        
        # 4. 🔥 CORRECTION : Initialiser driver start time
        driver_start_time = vrp_data["driver_start_time_seconds"]
        time_dimension.CumulVar(routing.Start(0)).SetValue(driver_start_time)
        logger.info("Driver start time initialized", start_time_seconds=driver_start_time)
        
        # 5. 🔥 CORRECTION : Time windows HARD constraints propres
        if self.USE_HARD_CONSTRAINTS_FOR_RESTRICTED:
            for location_idx, time_window in enumerate(vrp_data["time_windows"]):
                index = manager.NodeToIndex(location_idx)
                if location_idx in vrp_data["restricted_stops"]:
                    # Contrainte dure pour zones restreintes
                    time_dimension.CumulVar(index).SetRange(time_window[0], time_window[1])
                    logger.debug("Hard constraint applied for restricted stop", 
                               location_idx=location_idx, 
                               time_window=time_window)
                else:
                    # Zone normale
                    time_dimension.CumulVar(index).SetRange(time_window[0], time_window[1])
        
        # 6. Contraintes pickup/delivery
        valid_pairs_count = 0
        for pickup_index, delivery_index in vrp_data["pickup_delivery_pairs"]:
            pickup_node = manager.NodeToIndex(pickup_index)
            delivery_node = manager.NodeToIndex(delivery_index)
            
            if pickup_node == -1 or delivery_node == -1:
                raise ORToolsVRPError(f"Node OR-Tools invalide: pickup_index={pickup_index}, delivery_index={delivery_index}")
            
            if pickup_node == delivery_node:
                raise ORToolsVRPError(f"Pickup et delivery identiques: {pickup_node}")
            
            # Contraintes pickup/delivery
            routing.AddPickupAndDelivery(pickup_node, delivery_node)
            routing.solver().Add(
                time_dimension.CumulVar(pickup_node) <= time_dimension.CumulVar(delivery_node)
            )
            valid_pairs_count += 1
        
        logger.info("Pickup/delivery constraints added", count=valid_pairs_count)
        
        # 7. Dimension capacité
        def demand_callback(from_index):
            return 1
        
        demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimensionWithVehicleCapacity(
            demand_callback_index,
            0,
            vrp_data["vehicle_capacities"],
            True,
            "Capacity"
        )
        
        # 8. 🔥 NOUVEAU : Dimension spéciale pour zones Marseille centre (13001, 13006)
        marseille_centre_stops = [idx for idx in vrp_data["restricted_stops"] 
                                 if any(code in ["13001", "13006"] for code in self.RESTRICTED_POSTAL_CODES)]
        
        if marseille_centre_stops:
            def marseille_centre_callback(from_index):
                from_node = manager.IndexToNode(from_index)
                # Les zones Marseille centre ont un coût temporel plus élevé
                if from_node in marseille_centre_stops:
                    return 1000  # Coût élevé pour encourager groupage
                return 1
            
            marseille_callback_index = routing.RegisterUnaryTransitCallback(marseille_centre_callback)
            routing.AddDimension(
                marseille_callback_index,
                0,  # Pas de slack
                5000,  # Capacité max
                True,  # Start cumul to zero
                "MarseilleCentre"
            )
            
            logger.info("Dimension Marseille centre ajoutée", 
                       stops_count=len(marseille_centre_stops))
        
        # 9. 🔥 CORRECTION : Optimiser DISTANCE au lieu de temps
        # Supprimer le coefficient span sur le temps
        # time_dimension.SetGlobalSpanCostCoefficient(100)  # Supprimé
        
        # 9. 📌 Paramètres de recherche optimisés
        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.time_limit.seconds = self.TIME_LIMIT_SECONDS
        search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
        search_parameters.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.TABU_SEARCH
        search_parameters.log_search = False
        
        try:
            search_parameters.num_search_workers = 8
        except AttributeError:
            pass  # Version OR-Tools qui ne supporte pas cette fonctionnalité
        
        logger.info("OR-Tools configuration loaded",
                   time_limit=self.TIME_LIMIT_SECONDS,
                   strategy="PARALLEL_CHEAPEST_INSERTION",
                   metaheuristic="TABU_SEARCH")
        
        # 10. Résoudre
        solution = routing.SolveWithParameters(search_parameters)
        
        return manager, routing, solution
    
    def _extract_solution(self, manager: Any, routing: Any, solution: Any, 
                         vrp_data: Dict, or_tools_data: Dict) -> Dict:
        """
        Extrait et formate la solution OR-Tools
        """
        logger.info("Extracting OR-Tools solution v2.0")
        
        optimized_stops = []
        total_distance = 0
        total_time = 0
        
        time_dimension = routing.GetDimensionOrDie("Time")
        
        # Extraire la route du véhicule
        vehicle_id = 0
        index = routing.Start(vehicle_id)
        route_sequence = []
        
        while not routing.IsEnd(index):
            node_index = manager.IndexToNode(index)
            
            # Récupérer les infos du stop
            stop_mapping = vrp_data["stops_mapping"][node_index]
            time_var = time_dimension.CumulVar(index)
            time_value = solution.Value(time_var)
            
            # Trouver le stop original
            original_stop = next(
                (s for s in or_tools_data["stops"] if s["id"] == stop_mapping["stop_id"]), 
                None
            )
            
            if original_stop:
                optimized_stop = {
                    "id": original_stop["id"],
                    "location_id": original_stop["location_id"],
                    "stop_type": original_stop["stop_type"],
                    "stop_order": len(optimized_stops) + 1,
                    "original_stop_order": original_stop.get("stop_order"),
                    "latitude": original_stop["latitude"],
                    "longitude": original_stop["longitude"],
                    "formatted_address": original_stop["formatted_address"],
                    
                    # Données d'optimisation
                    "estimated_arrival_time": self._seconds_to_time_string(time_value),
                    "estimated_departure_time": self._seconds_to_time_string(
                        time_value + vrp_data["service_times"][node_index]
                    ),
                    "or_tools_node_index": node_index,
                    "cumulative_time_seconds": time_value,
                    "is_restricted_zone": node_index in vrp_data["restricted_stops"],
                    
                    # Données d'expansion
                    "shipment_ref": original_stop.get("shipment_ref"),
                    "shipment_action": original_stop.get("shipment_action"),
                    "original_stop_id": original_stop.get("original_stop_id")
                }
                
                optimized_stops.append(optimized_stop)
                route_sequence.append(node_index)
            
            # Calculer distances et temps pour le segment suivant
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
                from_node = route_sequence[i-1]
                to_node = route_sequence[i]
                optimized_stops[i]["distance_from_previous"] = vrp_data["distance_matrix"][from_node][to_node]
                optimized_stops[i]["duration_from_previous"] = vrp_data["duration_matrix"][from_node][to_node]
            else:
                optimized_stops[i]["distance_from_previous"] = 0
                optimized_stops[i]["duration_from_previous"] = 0
        
        solution_data = {
            "optimized_stops": optimized_stops,
            "route_sequence": route_sequence,
            "total_distance_meters": total_distance,
            "total_distance_km": round(total_distance / 1000, 2),
            "total_time_seconds": total_time,
            "total_time_hours": round(total_time / 3600, 2),
            "objective_value": solution.ObjectiveValue(),
            "restricted_stops_count": sum(1 for s in optimized_stops if s["is_restricted_zone"]),
            "pickup_delivery_pairs_satisfied": len(vrp_data["pickup_delivery_pairs"])
        }
        
        logger.info("OR-Tools solution extracted v2.0",
                   stops_count=len(optimized_stops),
                   total_distance_km=solution_data["total_distance_km"],
                   total_time_hours=solution_data["total_time_hours"],
                   objective_value=solution_data["objective_value"])
        
        return solution_data
    
    def _seconds_to_time_string(self, seconds: int) -> str:
        """Convertit secondes en string HH:MM"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours:02d}:{minutes:02d}"
    
    def _create_fallback_solution(self, or_tools_data: Dict, processing_time: float) -> Dict:
        """Crée une solution de fallback si OR-Tools ne trouve pas de solution"""
        logger.warning("Creating fallback solution - OR-Tools failed")
        
        return {
            "optimized_stops": or_tools_data["stops"],
            "route_sequence": list(range(len(or_tools_data["stops"]))),
            "total_distance_meters": 0,
            "total_distance_km": 0,
            "total_time_seconds": 0,
            "total_time_hours": 0,
            "objective_value": float('inf'),
            "optimization_metadata": {
                "solver": "OR-Tools VRP v2.0",
                "processing_time_seconds": round(processing_time, 2),
                "solution_found": False,
                "fallback_used": True,
                "error": "No solution found within time limit"
            }
        }
    
    def _create_error_solution(self, error_message: str, processing_time: float) -> Dict:
        """Crée une solution d'erreur"""
        logger.error("Creating error solution", error=error_message)
        
        return {
            "optimized_stops": [],
            "route_sequence": [],
            "total_distance_meters": 0,
            "total_distance_km": 0,
            "total_time_seconds": 0,
            "total_time_hours": 0,
            "objective_value": float('inf'),
            "optimization_metadata": {
                "solver": "OR-Tools VRP v2.0",
                "processing_time_seconds": round(processing_time, 2),
                "solution_found": False,
                "error": error_message
            }
        }


class ORToolsVRPError(Exception):
    """Exception levée lors d'erreurs OR-Tools VRP"""
    pass