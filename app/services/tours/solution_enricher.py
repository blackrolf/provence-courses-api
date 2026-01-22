"""
Service d'enrichissement des solutions OR-Tools
Calcule les heures de passage, distances, durées, polylines, etc.
"""

import structlog
from typing import Dict, List, Any, Tuple
from datetime import datetime, timedelta
import math
import requests
from app.integrations.supabase.base_client import supabase_base_client
from app.integrations.supabase.repositories.routes_repository import RoutesRepository
from app.integrations.supabase.repositories.drivers_repository import DriversRepository

logger = structlog.get_logger()


class SolutionEnricher:
    """
    Enrichit les solutions OR-Tools avec :
    - Heures de passage estimées
    - Distances entre stops consécutifs
    - Durées entre stops consécutifs
    - Distance/durée totale de la route
    - Polyline de la route (optionnel)
    """
    
    def __init__(self):
        self.osrm_url = "http://localhost:5000"
        self.supabase_client = supabase_base_client
        # Utiliser les repositories existants au lieu de dupliquer le code
        self.routes_repo = RoutesRepository(supabase_base_client)
        self.drivers_repo = DriversRepository(supabase_base_client)
        # Temps moyen d'arrêt par type de stop (minutes) - Calibré sur la réalité terrain
        self.stop_durations = {
            "depot_pickup": 1,
            "lab_pickup": 1,
            "lab_dropoff": 1,
            "depot_dropoff": 1,
            "client": 1,
            "start_location": 0  # Point de départ, pas d'arrêt
        }
    
    async def _get_driver_start_time(self, route_id: str) -> str:
        """Récupère l'heure de début du chauffeur depuis la base de données"""
        try:
            # Récupérer les infos de la route et du chauffeur
            route_result = self.supabase_client.select(
                table="driver_routes",
                columns="driver_id",
                id=route_id
            )
            
            if route_result["status"] != "success" or not route_result["data"]:
                logger.warning("Route not found, using default start time", route_id=route_id)
                return "08:00"
            
            driver_id = route_result["data"][0]["driver_id"]
            
            # Récupérer l'heure de début du chauffeur
            driver_result = self.supabase_client.select(
                table="drivers",
                columns="start_time,full_name",
                id=driver_id
            )
            
            if driver_result["status"] == "success" and driver_result["data"]:
                driver_data = driver_result["data"][0]
                start_time = driver_data.get("start_time", "08:00")
                driver_name = driver_data.get("full_name", "Unknown")
                
                logger.info("Driver start time retrieved", 
                           route_id=route_id,
                           driver_name=driver_name,
                           start_time=start_time)
                
                return start_time
            else:
                logger.warning("Driver not found, using default start time", 
                             driver_id=driver_id, route_id=route_id)
                return "08:00"
                
        except Exception as e:
            logger.error("Error retrieving driver start time", 
                        route_id=route_id, error=str(e))
            return "08:00"
    
    async def enrich_solution(self, route_id: str, final_stops: List[Dict], 
                            driver_start_time: str = None) -> Dict:
        """
        Enrichit une solution complète avec tous les calculs
        
        Args:
            route_id: ID de la route
            final_stops: Stops finaux fusionnés et ordonnés
            driver_start_time: Heure de début du chauffeur (si None, récupérée depuis la DB)
            
        Returns:
            Dict: Solution enrichie prête pour la sauvegarde
        """
        
        # Récupérer l'heure de début du chauffeur si non fournie
        if driver_start_time is None:
            driver_start_time = await self._get_driver_start_time(route_id)
        
        logger.info("Enriching solution with timing and routing data",
                   route_id=route_id,
                   stops_count=len(final_stops),
                   start_time=driver_start_time)
        
        try:
            # 1. Calculer la matrice de distances/durées OSRM
            distance_matrix, duration_matrix = await self._build_distance_matrix(final_stops)
            
            # 2. Calculer les heures de passage
            enriched_stops = self._calculate_arrival_times(
                final_stops, duration_matrix, driver_start_time
            )
            
            # 3. Calculer les distances/durées between consecutive stops
            enriched_stops = self._calculate_distances_durations(
                enriched_stops, distance_matrix, duration_matrix
            )
            
            # 4. Calculer les totaux de la route
            route_totals = self._calculate_route_totals(enriched_stops)
            
            # 5. Générer la polyline (optionnel)
            polyline = await self._generate_polyline(enriched_stops)
            
            enriched_solution = {
                "route_id": route_id,
                "enriched_stops": enriched_stops,
                "route_totals": route_totals,
                "polyline": polyline,
                "enrichment_metadata": {
                    "total_stops": len(enriched_stops),
                    "matrix_size": len(distance_matrix),
                    "start_time": driver_start_time,
                    "enrichment_timestamp": datetime.now().isoformat()
                }
            }
            
            logger.info("Solution enrichment completed",
                       route_id=route_id,
                       total_distance_km=route_totals["total_distance_km"],
                       total_duration_minutes=route_totals["total_duration_minutes"],
                       estimated_end_time=route_totals["estimated_end_time"])
            
            return enriched_solution
            
        except Exception as e:
            logger.error("Error enriching solution", route_id=route_id, error=str(e))
            raise
    
    async def _build_distance_matrix(self, stops: List[Dict]) -> Tuple[List[List[int]], List[List[int]]]:
        """Construit la matrice de distances/durées OSRM"""
        logger.info("Building OSRM distance matrix", stops_count=len(stops))
        
        try:
            # Extraire les coordonnées
            coordinates = []
            for stop in stops:
                lat = stop.get("latitude")
                lon = stop.get("longitude")
                if lat is not None and lon is not None:
                    coordinates.append([lon, lat])  # OSRM utilise [lon, lat]
                else:
                    logger.warning("Stop without coordinates", stop_id=stop.get("id", "unknown"))
                    coordinates.append([5.3424522, 43.3569471])  # Coordonnées par défaut Marseille
            
            if len(coordinates) < 2:
                raise ValueError("Not enough coordinates for matrix")
            
            # Construire l'URL OSRM
            coords_str = ";".join([f"{coord[0]},{coord[1]}" for coord in coordinates])
            url = f"{self.osrm_url}/table/v1/driving/{coords_str}"
            
            # Faire la requête
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if data["code"] != "Ok":
                raise ValueError(f"OSRM error: {data.get('message', 'Unknown error')}")
            
            # Extraire les matrices (distances en mètres, durées en secondes)
            distance_matrix = data["distances"]
            duration_matrix = data["durations"]
            
            logger.info("OSRM matrix built successfully",
                       matrix_size=f"{len(distance_matrix)}x{len(distance_matrix[0])}",
                       sample_distance_m=distance_matrix[0][1] if len(distance_matrix) > 1 else 0,
                       sample_duration_s=duration_matrix[0][1] if len(duration_matrix) > 1 else 0)
            
            return distance_matrix, duration_matrix
            
        except Exception as e:
            logger.error("Error building OSRM matrix", error=str(e))
            # Fallback : matrice de distances approximatives
            return self._build_fallback_matrix(stops)
    
    def _build_fallback_matrix(self, stops: List[Dict]) -> Tuple[List[List[int]], List[List[int]]]:
        """Matrice de fallback basée sur la distance euclidienne"""
        logger.warning("Using fallback distance matrix")
        
        size = len(stops)
        distance_matrix = [[0] * size for _ in range(size)]
        duration_matrix = [[0] * size for _ in range(size)]
        
        for i in range(size):
            for j in range(size):
                if i != j:
                    stop_i = stops[i]
                    stop_j = stops[j]
                    
                    # Distance euclidienne approximative
                    lat1, lon1 = stop_i.get("latitude", 43.3), stop_i.get("longitude", 5.3)
                    lat2, lon2 = stop_j.get("latitude", 43.3), stop_j.get("longitude", 5.3)
                    
                    distance_km = self._haversine_distance(lat1, lon1, lat2, lon2)
                    distance_m = int(distance_km * 1000)
                    duration_s = int(distance_km * 60)  # Approximation : 1 km/min
                    
                    distance_matrix[i][j] = distance_m
                    duration_matrix[i][j] = duration_s
        
        return distance_matrix, duration_matrix
    
    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calcule la distance haversine entre deux points"""
        R = 6371  # Rayon de la Terre en km
        
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        
        a = (math.sin(dlat/2)**2 + 
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
             math.sin(dlon/2)**2)
        
        c = 2 * math.asin(math.sqrt(a))
        return R * c
    
    def _calculate_arrival_times(self, stops: List[Dict], duration_matrix: List[List[int]], 
                               start_time: str) -> List[Dict]:
        """Calcule les heures d'arrivée et de départ pour chaque stop"""
        logger.info("Calculating arrival and departure times", start_time=start_time)
        
        enriched_stops = []
        
        # Parser l'heure de début
        try:
            start_hour, start_minute = map(int, start_time.split(":"))
            current_time = datetime.now().replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
        except:
            logger.warning("Invalid start time format, using 08:00", start_time=start_time)
            current_time = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
        
        for i, stop in enumerate(stops):
            enriched_stop = stop.copy()
            
            # Calculer l'heure d'arrivée
            if i == 0:
                # Premier stop : heure de début
                arrival_time = current_time
            else:
                # Ajouter le temps de trajet depuis le stop précédent
                travel_duration_s = duration_matrix[i-1][i]
                travel_duration_min = travel_duration_s // 60
                arrival_time = current_time + timedelta(minutes=travel_duration_min)
            
            # Calculer l'heure de départ (arrivée + durée d'arrêt)
            stop_type = stop.get("stop_type", "client")
            stop_duration_min = self.stop_durations.get(stop_type, 15)
            departure_time = arrival_time + timedelta(minutes=stop_duration_min)
            
            # Enrichir le stop
            enriched_stop.update({
                "estimated_arrival_time": arrival_time.strftime("%H:%M"),
                "estimated_departure_time": departure_time.strftime("%H:%M"),
                "stop_duration_minutes": stop_duration_min,
                "arrival_datetime": arrival_time.isoformat(),
                "departure_datetime": departure_time.isoformat()
            })
            
            enriched_stops.append(enriched_stop)
            
            # Préparer pour le prochain stop
            current_time = departure_time
        
        logger.info("Arrival times calculated",
                   first_stop=enriched_stops[0]["estimated_arrival_time"],
                   last_stop=enriched_stops[-1]["estimated_departure_time"],
                   total_stops=len(enriched_stops))
        
        return enriched_stops
    
    def _calculate_distances_durations(self, stops: List[Dict], 
                                     distance_matrix: List[List[int]], 
                                     duration_matrix: List[List[int]]) -> List[Dict]:
        """Calcule distance_from_previous et duration_from_previous"""
        logger.info("Calculating distances and durations from previous stops")
        
        enriched_stops = []
        
        for i, stop in enumerate(stops):
            enriched_stop = stop.copy()
            
            if i == 0:
                # Premier stop : pas de précédent
                enriched_stop.update({
                    "distance_from_previous": 0.0,
                    "duration_from_previous": 0
                })
            else:
                # Distance et durée depuis le stop précédent
                distance_m = distance_matrix[i-1][i]
                duration_s = duration_matrix[i-1][i]
                
                enriched_stop.update({
                    "distance_from_previous": round(distance_m / 1000.0, 2),  # km avec 2 décimales
                    "duration_from_previous": duration_s // 60  # minutes
                })
            
            enriched_stops.append(enriched_stop)
        
        return enriched_stops
    
    def _calculate_route_totals(self, enriched_stops: List[Dict]) -> Dict:
        """Calcule les totaux de la route"""
        logger.info("Calculating route totals")
        
        total_distance_km = sum(stop.get("distance_from_previous", 0) for stop in enriched_stops)
        total_duration_minutes = sum(stop.get("duration_from_previous", 0) + 
                                   stop.get("stop_duration_minutes", 0) 
                                   for stop in enriched_stops)
        
        # Heure de début et fin
        first_stop = enriched_stops[0]
        last_stop = enriched_stops[-1]
        
        start_time = first_stop.get("estimated_arrival_time", "08:00")
        end_time = last_stop.get("estimated_departure_time", "18:00")
        
        return {
            "total_distance_km": round(total_distance_km, 2),
            "total_duration_minutes": total_duration_minutes,
            "estimated_duration": total_duration_minutes,  # Alias pour compatibilité DB
            "estimated_start_time": start_time,
            "estimated_end_time": end_time,
            "total_stops": len(enriched_stops),
            "working_hours": f"{start_time} - {end_time}"
        }
    
    async def _generate_polyline(self, enriched_stops: List[Dict]) -> str:
        """Génère la polyline de la route (optionnel)"""
        logger.info("Generating route polyline")
        
        try:
            # Extraire les coordonnées pour OSRM Route
            coordinates = []
            for stop in enriched_stops:
                lat = stop.get("latitude")
                lon = stop.get("longitude")
                if lat is not None and lon is not None:
                    coordinates.append([lon, lat])
            
            if len(coordinates) < 2:
                return ""
            
            # Construire l'URL OSRM Route
            coords_str = ";".join([f"{coord[0]},{coord[1]}" for coord in coordinates])
            url = f"{self.osrm_url}/route/v1/driving/{coords_str}?overview=full&geometries=polyline"
            
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if data["code"] == "Ok" and "routes" in data and len(data["routes"]) > 0:
                polyline = data["routes"][0]["geometry"]
                logger.info("Polyline generated successfully", length=len(polyline))
                return polyline
            else:
                logger.warning("Could not generate polyline")
                return ""
                
        except Exception as e:
            logger.warning("Error generating polyline", error=str(e))
            return ""