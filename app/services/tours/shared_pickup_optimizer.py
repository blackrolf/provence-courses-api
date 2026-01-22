"""
Service d'optimisation GPS pour les shared pickups
"""

import structlog
import math
from typing import Dict, List, Tuple, Any
from datetime import datetime

logger = structlog.get_logger()


class SharedPickupOptimizer:
    """
    Service d'optimisation GPS simple pour les shared pickups
    
    Cette logique optimise les stops avec is_shared_pickup_stop=true en utilisant
    les coordonnées GPS pour créer l'ordre optimal de visite avant que les livreurs
    se retrouvent au start_location.
    """
    
    def __init__(self):
        pass
    
    def optimize_shared_pickup_sequence(self, driver_data: Dict, shared_pickup_stops: List[Dict]) -> Dict:
        """
        Optimise la séquence des shared pickups pour un driver
        
        Args:
            driver_data: Données du driver avec coordonnées de départ
            shared_pickup_stops: Liste des stops avec is_shared_pickup_stop=true
            
        Returns:
            Dict: Séquence optimisée avec nouveaux stop_order
        """
        logger.info("Optimizing shared pickup sequence",
                   driver_id=driver_data.get("id"),
                   shared_stops_count=len(shared_pickup_stops))
        
        if not shared_pickup_stops:
            return {
                "optimized_stops": [],
                "total_distance_km": 0,
                "optimization_method": "no_shared_pickups"
            }
        
        # Point de départ : coordonnées du driver
        start_coords = {
            "latitude": driver_data.get("start_latitude", driver_data.get("latitude")),
            "longitude": driver_data.get("start_longitude", driver_data.get("longitude")),
            "address": driver_data.get("start_address", "Driver start location")
        }
        
        # Séparer depot_pickup et lab_pickup SHARED UNIQUEMENT
        # Note: shared_pickup_stops contient déjà SEULEMENT les stops avec is_shared_pickup_stop=true
        depot_pickups = [s for s in shared_pickup_stops if s.get("stop_type") == "depot_pickup"]
        lab_pickups = [s for s in shared_pickup_stops if s.get("stop_type") == "lab_pickup"]
        
        # Validation: Vérifier que tous sont bien des shared pickups
        for stop in shared_pickup_stops:
            if not stop.get("is_shared_pickup_stop"):
                logger.warning("Non-shared pickup found in shared pickup optimization",
                             stop_id=stop.get("id"),
                             stop_type=stop.get("stop_type"),
                             is_shared=stop.get("is_shared_pickup_stop"))
        
        logger.info("Categorized shared pickups",
                   depot_pickups=len(depot_pickups),
                   lab_pickups=len(lab_pickups))
        
        # Optimiser la séquence
        optimized_sequence = self._build_optimal_sequence(
            start_coords, depot_pickups, lab_pickups
        )
        
        # Calculer la distance totale
        total_distance = self._calculate_total_distance(start_coords, optimized_sequence)
        
        # Assigner les nouveaux stop_order
        final_sequence = self._assign_stop_orders(optimized_sequence)
        
        result = {
            "optimized_stops": final_sequence,
            "total_distance_km": total_distance,
            "optimization_method": "intelligent_2opt_optimization",
            "start_coordinates": start_coords,
            "sequence_breakdown": {
                "depot_pickups": len(depot_pickups),
                "lab_pickups": len(lab_pickups),
                "total_stops": len(final_sequence)
            }
        }
        
        logger.info("Shared pickup sequence optimized",
                   driver_id=driver_data.get("id"),
                   total_stops=len(final_sequence),
                   total_distance_km=total_distance)
        
        return result
    
    def _build_optimal_sequence(self, start_coords: Dict, depot_pickups: List[Dict], 
                               lab_pickups: List[Dict]) -> List[Dict]:
        """
        Construit la séquence optimale des shared pickups
        
        Règles :
        1. depot_pickup aura stop_order = 1 (toujours en premier)
        2. lab_pickups optimisés par GPS nearest neighbor
        
        Args:
            start_coords: Coordonnées de départ du driver
            depot_pickups: Stops depot_pickup
            lab_pickups: Stops lab_pickup
            
        Returns:
            List[Dict]: Séquence optimisée
        """
        sequence = []
        
        # 1. depot_pickup TOUJOURS en premier (stop_order = 1)
        if depot_pickups:
            # Si plusieurs depot_pickup, prendre le plus proche du départ
            if len(depot_pickups) > 1:
                depot_pickups.sort(key=lambda s: self._calculate_distance(
                    start_coords, 
                    {"latitude": s["latitude"], "longitude": s["longitude"]}
                ))
            sequence.extend(depot_pickups)
        
        # 2. Optimiser les lab_pickups avec nearest neighbor
        if lab_pickups:
            optimized_labs = self._nearest_neighbor_optimization(
                start_coords if not depot_pickups else {
                    "latitude": depot_pickups[-1]["latitude"],
                    "longitude": depot_pickups[-1]["longitude"]
                },
                lab_pickups.copy()
            )
            sequence.extend(optimized_labs)
        
        return sequence
    
    def _nearest_neighbor_optimization(self, start_point: Dict, stops: List[Dict]) -> List[Dict]:
        """
        Algorithme d'optimisation intelligent avec 2-opt pour les shared pickups
        
        Args:
            start_point: Point de départ {"latitude": float, "longitude": float}
            stops: Liste des stops à optimiser
            
        Returns:
            List[Dict]: Stops optimisés par ordre de visite
        """
        if not stops:
            return []
        
        if len(stops) == 1:
            return stops
        
        logger.info("Starting intelligent shared pickup optimization",
                   stops_count=len(stops),
                   start_location=f"{start_point['latitude']:.4f},{start_point['longitude']:.4f}")
        
        # 1. Créer solution initiale avec nearest neighbor
        initial_solution = self._create_initial_solution_nearest_neighbor(start_point, stops)
        initial_distance = self._calculate_route_distance(start_point, initial_solution)
        
        logger.info("Initial nearest neighbor solution",
                   distance_km=initial_distance)
        
        # 2. Améliorer avec 2-opt si plus de 2 stops
        if len(stops) >= 3:
            optimized_solution = self._improve_with_2opt(start_point, initial_solution)
            optimized_distance = self._calculate_route_distance(start_point, optimized_solution)
            
            improvement = ((initial_distance - optimized_distance) / initial_distance) * 100
            logger.info("2-opt optimization completed",
                       initial_distance_km=initial_distance,
                       optimized_distance_km=optimized_distance,
                       improvement_percent=round(improvement, 1))
            
            return optimized_solution
        else:
            return initial_solution
    
    def _create_initial_solution_nearest_neighbor(self, start_point: Dict, stops: List[Dict]) -> List[Dict]:
        """
        Crée une solution initiale avec nearest neighbor
        """
        optimized = []
        current_point = start_point
        remaining_stops = stops.copy()
        
        while remaining_stops:
            # Trouver le stop le plus proche
            nearest_stop = min(remaining_stops, key=lambda s: self._calculate_distance(
                current_point,
                {"latitude": s["latitude"], "longitude": s["longitude"]}
            ))
            
            optimized.append(nearest_stop)
            remaining_stops.remove(nearest_stop)
            
            # Nouveau point de départ
            current_point = {
                "latitude": nearest_stop["latitude"],
                "longitude": nearest_stop["longitude"]
            }
        
        return optimized
    
    def _improve_with_2opt(self, start_point: Dict, route: List[Dict]) -> List[Dict]:
        """
        Améliore la route avec l'algorithme 2-opt
        
        Args:
            start_point: Point de départ
            route: Route initiale
            
        Returns:
            List[Dict]: Route améliorée
        """
        best_route = route.copy()
        best_distance = self._calculate_route_distance(start_point, best_route)
        improved = True
        iterations = 0
        max_iterations = min(100, len(route) * len(route))  # Limiter les itérations
        
        logger.debug("Starting 2-opt optimization",
                    initial_distance=best_distance,
                    route_length=len(route))
        
        while improved and iterations < max_iterations:
            improved = False
            iterations += 1
            
            # Essayer toutes les paires d'edges possibles
            for i in range(len(route)):
                for j in range(i + 2, len(route)):
                    # Créer nouvelle route en inversant le segment [i+1:j+1]
                    new_route = route.copy()
                    new_route[i+1:j+1] = reversed(new_route[i+1:j+1])
                    
                    # Calculer la nouvelle distance
                    new_distance = self._calculate_route_distance(start_point, new_route)
                    
                    # Si amélioration, garder cette route
                    if new_distance < best_distance:
                        best_route = new_route
                        best_distance = new_distance
                        route = new_route  # Continuer à partir de cette nouvelle route
                        improved = True
                        logger.debug("2-opt improvement found",
                                   iteration=iterations,
                                   new_distance=new_distance,
                                   improvement=best_distance - new_distance)
        
        logger.info("2-opt optimization finished",
                   iterations=iterations,
                   final_distance=best_distance)
        
        return best_route
    
    def _calculate_route_distance(self, start_point: Dict, route: List[Dict]) -> float:
        """
        Calcule la distance totale d'une route complète
        
        Args:
            start_point: Point de départ
            route: Liste des stops dans l'ordre
            
        Returns:
            float: Distance totale en km
        """
        if not route:
            return 0.0
        
        total_distance = 0.0
        current_point = start_point
        
        for stop in route:
            next_point = {
                "latitude": stop["latitude"],
                "longitude": stop["longitude"]
            }
            total_distance += self._calculate_distance(current_point, next_point)
            current_point = next_point
        
        return round(total_distance, 2)
    
    def _assign_stop_orders(self, sequence: List[Dict]) -> List[Dict]:
        """
        Assigne les nouveaux stop_order à la séquence optimisée
        
        Args:
            sequence: Séquence optimisée des stops
            
        Returns:
            List[Dict]: Stops avec nouveaux stop_order
        """
        for i, stop in enumerate(sequence):
            stop["optimized_stop_order"] = i + 1  # Commence à 1
            stop["original_stop_order"] = stop.get("stop_order")  # Sauvegarder l'original
        
        return sequence
    
    def _calculate_distance(self, point1: Dict, point2: Dict) -> float:
        """
        Calcule la distance haversine entre deux points GPS
        
        Args:
            point1: {"latitude": float, "longitude": float}
            point2: {"latitude": float, "longitude": float}
            
        Returns:
            float: Distance en kilomètres
        """
        lat1, lon1 = point1["latitude"], point1["longitude"]
        lat2, lon2 = point2["latitude"], point2["longitude"]
        
        # Validation des coordonnées
        if any(coord is None for coord in [lat1, lon1, lat2, lon2]):
            logger.error("Coordonnées GPS manquantes pour calcul distance",
                        point1=point1,
                        point2=point2)
            raise ValueError(f"Coordonnées GPS manquantes: {point1} -> {point2}")
        
        # Convertir en radians
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        
        # Formule haversine
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        # Rayon de la Terre en km
        R = 6371
        return R * c
    
    def _calculate_total_distance(self, start_coords: Dict, sequence: List[Dict]) -> float:
        """
        Calcule la distance totale du parcours
        
        Args:
            start_coords: Point de départ
            sequence: Séquence des stops
            
        Returns:
            float: Distance totale en kilomètres
        """
        if not sequence:
            return 0.0
        
        total_distance = 0.0
        current_point = start_coords
        
        for stop in sequence:
            next_point = {
                "latitude": stop["latitude"],
                "longitude": stop["longitude"]
            }
            total_distance += self._calculate_distance(current_point, next_point)
            current_point = next_point
        
        return round(total_distance, 2)
    
    def validate_shared_pickup_data(self, stops: List[Dict]) -> Dict:
        """
        Valide la qualité des données pour l'optimisation shared pickups
        
        Args:
            stops: Liste des stops à valider
            
        Returns:
            Dict: Rapport de validation
        """
        validation_report = {
            "total_stops": len(stops),
            "valid_stops": 0,
            "missing_coordinates": [],
            "invalid_stop_types": [],
            "data_quality_score": 0.0,
            "ready_for_optimization": False
        }
        
        valid_stop_types = ["depot_pickup", "lab_pickup"]
        
        for stop in stops:
            # Vérifier les coordonnées
            if not stop.get("latitude") or not stop.get("longitude"):
                validation_report["missing_coordinates"].append(stop.get("id"))
                continue
            
            # Vérifier le type de stop
            if stop.get("stop_type") not in valid_stop_types:
                validation_report["invalid_stop_types"].append({
                    "stop_id": stop.get("id"),
                    "stop_type": stop.get("stop_type")
                })
                continue
            
            validation_report["valid_stops"] += 1
        
        # Calculer le score de qualité
        if validation_report["total_stops"] > 0:
            validation_report["data_quality_score"] = (
                validation_report["valid_stops"] / validation_report["total_stops"]
            )
        
        validation_report["ready_for_optimization"] = (
            validation_report["data_quality_score"] >= 0.9 and
            validation_report["valid_stops"] > 0
        )
        
        return validation_report


class SharedPickupOptimizerError(Exception):
    """Exception levée lors d'erreurs d'optimisation shared pickup"""
    pass