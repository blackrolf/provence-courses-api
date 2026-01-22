"""
Service d'enrichissement des tournées via Google Directions API avec fallback OSRM
"""

import structlog
from typing import Dict, List, Optional, Any
import httpx
import asyncio
import os
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

logger = structlog.get_logger()


class DirectionsEnricher:
    """Service d'enrichissement des tournées avec Google Directions API et fallback OSRM"""
    
    def __init__(self):
        self.google_api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        self.osrm_url = os.getenv("OSRM_URL", "http://localhost:5000")
        self.base_url = "https://maps.googleapis.com/maps/api/directions/json"
        
        if not self.google_api_key:
            logger.warning("Google Maps API key not found, will use OSRM fallback only")
    
    async def enrich_optimized_route(self, route_data: Dict, optimized_stops: List[Dict]) -> Dict:
        """
        Enrichit une route optimisée avec les données Google Directions
        
        Args:
            route_data: Données de base de la route (contient driver info avec start_time)
            optimized_stops: Stops optimisés et fusionnés (avec coordonnées GPS)
            
        Returns:
            Dict: Données enrichies avec polyline, distances et durées détaillées
            {
                "route_polyline": str,           # Polyline encodée Google
                "total_distance_km": float,      # Distance totale en km
                "estimated_duration_minutes": int,  # Durée totale en minutes
                "stop_details": [
                    {
                        "stop_id": str,
                        "distance_from_previous": float,  # km
                        "duration_from_previous": int,    # minutes
                        "estimated_arrival_time": str,   # HH:MM
                        "estimated_departure_time": str  # HH:MM
                    }
                ],
                "directions_metadata": {
                    "api_calls_made": int,
                    "processing_time_seconds": float,
                    "polyline_points": int
                }
            }
            
        Raises:
            DirectionsEnrichmentError: Si erreur lors de l'enrichissement
        """
        # Extraire l'heure de départ du chauffeur depuis route_data
        driver_start_time = self._extract_driver_start_time(route_data)
        
        logger.info("Starting route enrichment with Google Directions (OSRM fallback available)", 
                   route_id=route_data.get("id"),
                   stops_count=len(optimized_stops),
                   driver_start_time=driver_start_time)
        
        if len(optimized_stops) < 2:
            logger.warning("Route has less than 2 stops, minimal enrichment applied")
            return self._create_minimal_enrichment(optimized_stops, driver_start_time)
        
        # Essayer Google Maps d'abord si la clé API est disponible
        if self.google_api_key:
            try:
                logger.debug("Attempting Google Directions API enrichment")
                
                # 1. Préparer les waypoints depuis les stops optimisés
                waypoints = self._prepare_waypoints(optimized_stops)
                
                # 2. Appeler Google Directions API
                directions_result = await self._fetch_directions(waypoints)
                
                # 3. Parser les résultats et calculer les détails par stop
                enriched_data = self._parse_directions_response(
                    directions_result, 
                    optimized_stops,
                    route_data
                )
                
                logger.info("Route enrichment completed successfully with Google Maps",
                           route_id=route_data.get("id"),
                           total_distance=enriched_data["total_distance_km"],
                           total_duration=enriched_data["estimated_duration_minutes"])
                
                return enriched_data
                
            except Exception as google_error:
                logger.warning("Google Directions API failed, falling back to OSRM", 
                             route_id=route_data.get("id"),
                             error=str(google_error))
                
                # Continuer avec OSRM fallback
        else:
            logger.info("No Google Maps API key, using OSRM directly")
        
        # Fallback OSRM
        try:
            logger.info("Using OSRM fallback for route enrichment")
            return await self._enrich_with_osrm_fallback(route_data, optimized_stops, driver_start_time)
            
        except Exception as osrm_error:
            logger.error("Both Google Maps and OSRM failed for route enrichment", 
                        route_id=route_data.get("id"),
                        google_available=bool(self.google_api_key),
                        osrm_error=str(osrm_error))
            
            # En dernier recours, retourner un enrichissement minimal
            logger.warning("Falling back to minimal enrichment")
            return self._create_minimal_enrichment(optimized_stops, driver_start_time)
    
    async def _enrich_with_osrm_fallback(self, route_data: Dict, optimized_stops: List[Dict], driver_start_time: str = "08:00") -> Dict:
        """
        Enrichissement via OSRM en fallback de Google Maps
        
        Args:
            route_data: Données de base de la route
            optimized_stops: Stops optimisés avec coordonnées GPS
            
        Returns:
            Dict: Données enrichies via OSRM
        """
        logger.info("Starting OSRM fallback enrichment", 
                   route_id=route_data.get("id"),
                   stops_count=len(optimized_stops))
        
        try:
            # Importer le service OSRM
            from .osrm_distance_matrix import OSRMDistanceMatrixService
            
            osrm_service = OSRMDistanceMatrixService()
            
            # Générer la matrice de distances OSRM
            matrix_result = await osrm_service.generate_distance_matrix_for_route(optimized_stops)
            
            # Convertir la matrice OSRM en format enrichissement
            enriched_data = self._convert_osrm_to_enrichment_format(
                matrix_result, 
                optimized_stops, 
                route_data
            )
            
            # Générer le polyline via OSRM Route API
            polyline = await self._get_osrm_polyline(optimized_stops)
            if polyline:
                enriched_data["route_polyline"] = polyline
                enriched_data["directions_metadata"]["polyline_points"] = len(polyline)
            
            # Ajouter les métadonnées de fallback
            enriched_data["directions_metadata"]["fallback_used"] = "OSRM"
            enriched_data["directions_metadata"]["osrm_url"] = self.osrm_url
            
            logger.info("OSRM fallback enrichment completed successfully",
                       route_id=route_data.get("id"),
                       total_distance=enriched_data["total_distance_km"],
                       total_duration=enriched_data["estimated_duration_minutes"])
            
            return enriched_data
            
        except Exception as e:
            logger.error("Error in OSRM fallback enrichment", 
                        route_id=route_data.get("id"),
                        error=str(e))
            raise DirectionsEnrichmentError(f"Erreur OSRM fallback: {str(e)}")
    
    def _convert_osrm_to_enrichment_format(self, matrix_result: Dict, 
                                          optimized_stops: List[Dict], 
                                          route_data: Dict) -> Dict:
        """
        Convertit les résultats OSRM au format d'enrichissement standard
        
        Args:
            matrix_result: Résultat de la matrice OSRM
            optimized_stops: Stops optimisés
            route_data: Données de la route
            
        Returns:
            Dict: Format d'enrichissement standard
        """
        stops_mapping = matrix_result["stops_mapping"]
        distance_matrix = matrix_result["distance_matrix"]
        duration_matrix = matrix_result["duration_matrix"]
        
        # Extraire l'heure de départ du chauffeur
        driver_start_time = self._extract_driver_start_time(route_data)
        
        # Calculer les totaux en parcourant la route dans l'ordre optimisé
        total_distance_meters = 0
        total_duration_seconds = 0
        stop_details = []
        cumulative_time_minutes = 0
        
        # Trier les stops par ordre d'optimisation
        sorted_stops = sorted(optimized_stops, key=lambda x: x.get("stop_order", 0))
        
        for i, stop in enumerate(sorted_stops):
            stop_id = stop["id"]
            
            # Trouver l'index dans la matrice OSRM
            stop_index = None
            for mapping in stops_mapping:
                if mapping["stop_id"] == stop_id:
                    stop_index = mapping["index"]
                    break
            
            if stop_index is None:
                logger.warning("Stop not found in OSRM matrix", stop_id=stop_id)
                continue
            
            if i == 0:
                # Premier stop - utiliser l'heure de départ du chauffeur
                # SANS temps de service
                stop_details.append({
                    "stop_id": stop_id,
                    "distance_from_previous": 0,
                    "duration_from_previous": 0,
                    "estimated_arrival_time": driver_start_time,
                    "estimated_departure_time": driver_start_time  # Pas de temps de service
                })
                cumulative_time_minutes = 0  # Pas d'accumulation de temps de service
            else:
                # Stops suivants - calculer distance depuis le stop précédent
                prev_stop = sorted_stops[i - 1]
                prev_index = None
                for mapping in stops_mapping:
                    if mapping["stop_id"] == prev_stop["id"]:
                        prev_index = mapping["index"]
                        break
                
                if prev_index is not None:
                    # Distance et durée depuis le stop précédent
                    distance_meters = distance_matrix[prev_index][stop_index]
                    duration_seconds = duration_matrix[prev_index][stop_index]
                    
                    distance_km = round(distance_meters / 1000, 2)
                    duration_minutes = round(duration_seconds / 60)
                    
                    # Accumuler pour les totaux
                    total_distance_meters += distance_meters
                    total_duration_seconds += duration_seconds
                    
                    # Calculer les horaires depuis l'heure de départ du chauffeur
                    # SANS temps de service - données de route pure uniquement
                    arrival_time = self._add_minutes_to_time(driver_start_time, cumulative_time_minutes + duration_minutes)
                    # Pour departure_time, on met la même valeur que arrival (pas de temps de service)
                    departure_time = arrival_time
                    
                    stop_details.append({
                        "stop_id": stop_id,
                        "distance_from_previous": distance_km,
                        "duration_from_previous": duration_minutes,
                        "estimated_arrival_time": arrival_time,
                        "estimated_departure_time": departure_time
                    })
                    
                    # Accumulation SANS temps de service - route pure uniquement
                    cumulative_time_minutes += duration_minutes
        
        # Convertir les totaux
        total_distance_km = round(total_distance_meters / 1000, 2)
        estimated_duration_minutes = round(total_duration_seconds / 60)
        
        return {
            "route_polyline": "",  # OSRM ne fournit pas de polyline par défaut
            "total_distance_km": total_distance_km,
            "estimated_duration_minutes": estimated_duration_minutes,
            "stop_details": stop_details,
            "directions_metadata": {
                "api_calls_made": 1,
                "processing_time_seconds": matrix_result["osrm_metadata"]["processing_time"],
                "polyline_points": 0,
                "matrix_size": matrix_result["matrix_size"],
                "osrm_fallback": True
            }
        }
    
    def _prepare_waypoints(self, optimized_stops: List[Dict]) -> List[Dict]:
        """Prépare les waypoints pour Google Directions"""
        waypoints = []
        
        for stop in optimized_stops:
            if stop.get("latitude") and stop.get("longitude"):
                waypoints.append({
                    "stop_id": stop["id"],
                    "location": f"{stop['latitude']},{stop['longitude']}",
                    "address": stop.get("formatted_address", ""),
                    "stop_type": stop.get("stop_type"),
                    "stop_order": stop.get("stop_order")
                })
        
        logger.debug("Waypoints prepared for Directions API", count=len(waypoints))
        return waypoints
    
    async def _fetch_directions(self, waypoints: List[Dict]) -> Dict:
        """Appelle Google Directions API"""
        if len(waypoints) < 2:
            raise DirectionsEnrichmentError("Au moins 2 waypoints requis")
        
        # Construire la requête
        origin = waypoints[0]["location"]
        destination = waypoints[-1]["location"]
        
        # Waypoints intermédiaires (s'il y en a)
        intermediate_waypoints = []
        if len(waypoints) > 2:
            intermediate_waypoints = [wp["location"] for wp in waypoints[1:-1]]
        
        params = {
            "origin": origin,
            "destination": destination,
            "key": self.google_api_key,
            "mode": "driving",
            "optimize": "false",  # On a déjà optimisé avec OR-Tools
            "language": "fr",
            "units": "metric"
        }
        
        if intermediate_waypoints:
            params["waypoints"] = "|".join(intermediate_waypoints)
        
        async with httpx.AsyncClient(timeout=30) as client:
            logger.debug("Calling Google Directions API", 
                        origin=origin,
                        destination=destination,
                        waypoints_count=len(intermediate_waypoints))
            
            response = await client.get(self.base_url, params=params)
            response.raise_for_status()
            
            result = response.json()
            
            if result.get("status") != "OK":
                raise DirectionsEnrichmentError(
                    f"Google Directions API error: {result.get('status')} - {result.get('error_message', '')}"
                )
            
            return result
    
    def _parse_directions_response(self, directions_result: Dict, 
                                 optimized_stops: List[Dict], 
                                 route_data: Dict) -> Dict:
        """Parse la réponse Google Directions et calcule les détails par stop"""
        
        if not directions_result.get("routes"):
            raise DirectionsEnrichmentError("Aucune route trouvée dans la réponse Google Directions")
        
        route = directions_result["routes"][0]
        legs = route.get("legs", [])
        
        # Extraire la polyline principale
        route_polyline = route.get("overview_polyline", {}).get("points", "")
        
        # Calculer les totaux
        total_distance_meters = sum(leg.get("distance", {}).get("value", 0) for leg in legs)
        total_duration_seconds = sum(leg.get("duration", {}).get("value", 0) for leg in legs)
        
        total_distance_km = round(total_distance_meters / 1000, 2)
        estimated_duration_minutes = round(total_duration_seconds / 60)
        
        # Calculer les détails par stop avec l'heure de départ du chauffeur
        driver_start_time = self._extract_driver_start_time(route_data)
        stop_details = self._calculate_stop_details(legs, optimized_stops, driver_start_time)
        
        return {
            "route_polyline": route_polyline,
            "total_distance_km": total_distance_km,
            "estimated_duration_minutes": estimated_duration_minutes,
            "stop_details": stop_details,
            "directions_metadata": {
                "api_calls_made": 1,
                "processing_time_seconds": 0,  # À calculer si nécessaire
                "polyline_points": len(route_polyline),
                "legs_count": len(legs)
            }
        }
    
    def _calculate_stop_details(self, legs: List[Dict], optimized_stops: List[Dict], driver_start_time: str = "08:00") -> List[Dict]:
        """Calcule les détails par stop depuis les legs Google Directions"""
        stop_details = []
        cumulative_time_minutes = 0
        
        # Premier stop (origine) - utiliser l'heure de départ du chauffeur
        if optimized_stops:
            first_stop = optimized_stops[0]
            stop_details.append({
                "stop_id": first_stop["id"],
                "distance_from_previous": 0,
                "duration_from_previous": 0,
                "estimated_arrival_time": driver_start_time,
                "estimated_departure_time": driver_start_time  # Pas de temps de service
            })
            cumulative_time_minutes = 0  # Pas de temps de service - route pure
        
        # Stops suivants
        for i, leg in enumerate(legs):
            if i + 1 < len(optimized_stops):
                next_stop = optimized_stops[i + 1]
                
                # Distance et durée depuis le stop précédent
                distance_km = round(leg.get("distance", {}).get("value", 0) / 1000, 2)
                duration_minutes = round(leg.get("duration", {}).get("value", 0) / 60)
                
                # Horaires estimés depuis l'heure de départ du chauffeur
                # SANS temps de service - données de route pure
                arrival_time = self._add_minutes_to_time(driver_start_time, cumulative_time_minutes + duration_minutes)
                
                # Pas de temps de service - route pure
                departure_time = arrival_time
                
                stop_details.append({
                    "stop_id": next_stop["id"],
                    "distance_from_previous": distance_km,
                    "duration_from_previous": duration_minutes,
                    "estimated_arrival_time": arrival_time,
                    "estimated_departure_time": departure_time
                })
                
                # Accumulation SANS temps de service - route pure uniquement
                cumulative_time_minutes += duration_minutes
        
        return stop_details
    
    def _get_service_time(self, stop_type: str) -> int:
        """Retourne le temps de service par type de stop (en minutes)"""
        service_times = {
            "depot_pickup": 15,
            "depot_dropoff": 10,
            "lab_pickup": 10,
            "lab_dropoff": 8,
            "client": 5  # Par défaut pour client pickup/delivery
        }
        return service_times.get(stop_type, 5)
    
    async def _get_osrm_polyline(self, optimized_stops: List[Dict]) -> str:
        """
        Récupère le polyline depuis OSRM Route API
        
        Args:
            optimized_stops: Stops avec coordonnées GPS
            
        Returns:
            str: Polyline encodé ou chaîne vide si erreur
        """
        try:
            if len(optimized_stops) < 2:
                return ""
            
            # Construire la chaîne de coordonnées pour OSRM
            coords = []
            for stop in optimized_stops:
                if stop.get("latitude") and stop.get("longitude"):
                    coords.append(f"{stop['longitude']},{stop['latitude']}")
            
            if len(coords) < 2:
                return ""
            
            coords_str = ";".join(coords)
            url = f"{self.osrm_url}/route/v1/driving/{coords_str}?overview=full&geometries=polyline"
            
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("routes") and len(data["routes"]) > 0:
                        polyline = data["routes"][0].get("geometry", "")
                        logger.debug("OSRM polyline generated", length=len(polyline))
                        return polyline
            
            return ""
            
        except Exception as e:
            logger.warning("Could not generate OSRM polyline", error=str(e))
            return ""
    
    def _add_minutes_to_time(self, time_str: str, minutes: int) -> str:
        """Ajoute des minutes à une heure au format HH:MM"""
        try:
            hours, mins = map(int, time_str.split(":"))
            total_minutes = hours * 60 + mins + minutes
            
            new_hours = (total_minutes // 60) % 24
            new_minutes = total_minutes % 60
            
            return f"{new_hours:02d}:{new_minutes:02d}"
        except:
            return time_str
    
    def _extract_driver_start_time(self, route_data: Dict) -> str:
        """
        Extrait l'heure de départ du chauffeur depuis route_data
        
        Args:
            route_data: Données de la route contenant les infos driver
            
        Returns:
            str: Heure de départ au format HH:MM (ex: "19:00")
        """
        try:
            # Essayer plusieurs chemins possibles pour l'heure de départ
            driver_start_time = None
            
            # Chemin 1: route_data.driver.start_time
            if "driver" in route_data and isinstance(route_data["driver"], dict):
                driver_start_time = route_data["driver"].get("start_time")
            
            # Chemin 2: route_data.start_time (direct)
            if not driver_start_time:
                driver_start_time = route_data.get("start_time")
                
            # Chemin 3: route_data.driver_start_time 
            if not driver_start_time:
                driver_start_time = route_data.get("driver_start_time")
            
            # Validation et formatage
            if driver_start_time:
                # Si c'est déjà au format HH:MM, retourner tel quel
                if isinstance(driver_start_time, str) and ":" in driver_start_time:
                    return driver_start_time
                    
                # Si c'est un timestamp ou autre format, essayer de parser
                # (à implémenter si nécessaire selon le format réel)
                
            logger.warning("Driver start time not found in route_data, using default 08:00",
                         available_keys=list(route_data.keys()))
            return "08:00"  # Fallback par défaut
            
        except Exception as e:
            logger.error("Error extracting driver start time", error=str(e))
            return "08:00"  # Fallback en cas d'erreur
    
    def _create_minimal_enrichment(self, optimized_stops: List[Dict], driver_start_time: str = "08:00") -> Dict:
        """Crée un enrichissement minimal si pas assez de stops"""
        return {
            "route_polyline": "",
            "total_distance_km": 0.0,
            "estimated_duration_minutes": 0,  # Pas de durée si pas de route
            "stop_details": [
                {
                    "stop_id": stop["id"],
                    "distance_from_previous": 0,
                    "duration_from_previous": 0,
                    "estimated_arrival_time": driver_start_time,
                    "estimated_departure_time": driver_start_time  # Pas de temps de service
                }
                for stop in optimized_stops
            ],
            "directions_metadata": {
                "api_calls_made": 0,
                "processing_time_seconds": 0,
                "polyline_points": 0,
                "minimal_enrichment": True
            }
        }


class DirectionsEnrichmentError(Exception):
    """Exception levée lors d'erreurs d'enrichissement Directions"""
    pass