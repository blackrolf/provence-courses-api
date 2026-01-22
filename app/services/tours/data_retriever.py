"""
Service de récupération des données depuis Supabase pour la génération de tournées
"""

import structlog
from datetime import date
from typing import List, Dict, Optional
from app.integrations.supabase.base_client import supabase_base_client
from app.integrations.supabase.repositories import (
    RoutesRepository,
    StopsRepository,
    LabTourShipmentsRepository,
    DriverRouteShipmentsRepository,
    DriversRepository,
    ClientsRepository,
    LaboratoriesRepository,
    LocationsRepository
)
from .exceptions import DataRetrievalError

logger = structlog.get_logger()


class TourDataRetriever:
    """Service de récupération des données depuis Supabase"""
    
    def __init__(self):
        # Initialiser tous les repositories avec le client de base
        self.routes_repo = RoutesRepository(supabase_base_client)
        self.stops_repo = StopsRepository(supabase_base_client)
        self.lab_shipments_repo = LabTourShipmentsRepository(supabase_base_client)
        self.driver_shipments_repo = DriverRouteShipmentsRepository(supabase_base_client)
        self.drivers_repo = DriversRepository(supabase_base_client)
        self.clients_repo = ClientsRepository(supabase_base_client)
        self.labs_repo = LaboratoriesRepository(supabase_base_client)
        self.locations_repo = LocationsRepository(supabase_base_client)
    
    async def get_enriched_shipments_for_date(self, target_date: date) -> List[Dict]:
        """
        Récupère tous les shipments du jour avec toutes les informations enrichies
        
        Args:
            target_date: Date cible pour les shipments
            
        Returns:
            List[Dict]: Liste des shipments enrichis avec données clients/labos
            
        Raises:
            DataRetrievalError: Si erreur lors de la récupération
        """
        logger.info("Retrieving enriched shipments for date", date=str(target_date))
        
        try:
            # Utiliser le repository spécialisé
            result = self.lab_shipments_repo.get_enriched_shipments_by_date(str(target_date))
            
            if result["status"] != "success":
                raise DataRetrievalError(f"Erreur lors de la récupération des shipments enrichis: {result['message']}")
            
            shipments = result["data"]
            logger.info("Enriched shipments retrieved successfully", count=len(shipments))
            
            return shipments
            
        except Exception as e:
            logger.error("Error retrieving enriched shipments", error=str(e))
            raise DataRetrievalError(f"Erreur lors de la récupération des shipments enrichis: {str(e)}")
    
    async def get_drivers_list(self) -> List[Dict]:
        """
        Récupère la liste des drivers actifs
        
        Returns:
            List[Dict]: Liste des drivers
        """
        logger.info("Retrieving drivers list")
        
        try:
            result = self.drivers_repo.get_all_drivers()
            
            if result["status"] != "success":
                raise DataRetrievalError(f"Erreur lors de la récupération des drivers: {result['message']}")
            
            drivers = result["data"]
            logger.info("Drivers retrieved successfully", count=len(drivers))
            
            return drivers
            
        except Exception as e:
            logger.error("Error retrieving drivers", error=str(e))
            raise DataRetrievalError(f"Erreur lors de la récupération des drivers: {str(e)}")
    
    async def get_locations_map(self) -> Dict[str, Dict]:
        """
        Récupère toutes les locations et les retourne sous forme de dictionnaire
        
        Returns:
            Dict[str, Dict]: Map location_id -> location_data
        """
        logger.info("Retrieving locations map")
        
        try:
            locations_map = self.locations_repo.get_locations_map()
            
            logger.info("Locations map created successfully", count=len(locations_map))
            
            return locations_map
            
        except Exception as e:
            logger.error("Error retrieving locations", error=str(e))
            raise DataRetrievalError(f"Erreur lors de la récupération des locations: {str(e)}")
    
    async def get_laboratories_location_map(self) -> Dict[str, str]:
        """
        Récupère le mapping laboratory_id → location_id pour tous les laboratoires
        
        Returns:
            Dict[str, str]: Map laboratory_id -> location_id
        """
        logger.info("Retrieving laboratories location mapping")
        
        try:
            result = self.labs_repo.get_all_laboratories()
            
            if result["status"] != "success":
                raise DataRetrievalError(f"Erreur lors de la récupération des laboratoires: {result['message']}")
            
            laboratories = result["data"]
            
            # Créer le mapping laboratory_id -> location_id
            lab_location_map = {}
            for lab in laboratories:
                lab_id = lab["id"]
                location_id = lab.get("location_id")
                if location_id:
                    lab_location_map[lab_id] = location_id
                else:
                    logger.warning("Laboratory without location_id", lab_id=lab_id, lab_name=lab.get("name"))
            
            logger.info("Laboratories location mapping created successfully", count=len(lab_location_map))
            
            return lab_location_map
            
        except Exception as e:
            logger.error("Error retrieving laboratories location mapping", error=str(e))
            raise DataRetrievalError(f"Erreur lors de la récupération du mapping des laboratoires: {str(e)}")
    
    async def create_route_stop(self, stop_data: Dict) -> str:
        """
        Crée un nouveau stop dans driver_route_stops
        
        Args:
            stop_data: Données du stop à créer
            
        Returns:
            str: ID du stop créé
        """
        logger.debug("Creating route stop", route_id=stop_data.get("route_id"))
        
        try:
            result = self.stops_repo.create_stop(stop_data)
            
            if result["status"] != "success":
                raise DataRetrievalError(f"Erreur lors de la création du stop: {result['message']}")
            
            stop_id = result["data"]["id"]
            logger.debug("Route stop created successfully", stop_id=stop_id)
            
            return stop_id
            
        except Exception as e:
            logger.error("Error creating route stop", error=str(e))
            raise DataRetrievalError(f"Erreur lors de la création du stop: {str(e)}")
    
    async def create_route_shipment(self, shipment_data: Dict) -> str:
        """
        Crée un nouveau shipment dans driver_route_shipments
        
        Args:
            shipment_data: Données du shipment à créer
            
        Returns:
            str: ID du shipment créé
        """
        logger.debug("Creating route shipment", route_id=shipment_data.get("route_id"))
        
        try:
            result = self.driver_shipments_repo.create_shipment(shipment_data)
            
            if result["status"] != "success":
                raise DataRetrievalError(f"Erreur lors de la création du shipment: {result['message']}")
            
            shipment_id = result["data"]["id"]
            logger.debug("Route shipment created successfully", shipment_id=shipment_id)
            
            return shipment_id
            
        except Exception as e:
            logger.error("Error creating route shipment", error=str(e))
            raise DataRetrievalError(f"Erreur lors de la création du shipment: {str(e)}")
    
    async def create_driver_route(self, route_data: Dict) -> str:
        """
        Crée une nouvelle route dans driver_routes
        
        Args:
            route_data: Données de la route à créer
            
        Returns:
            str: ID de la route créée
        """
        logger.debug("Creating driver route", driver_id=route_data.get("driver_id"))
        
        try:
            result = self.routes_repo.create_route(route_data)
            
            if result["status"] != "success":
                raise DataRetrievalError(f"Erreur lors de la création de la route: {result['message']}")
            
            route_id = result["data"]["id"]
            logger.debug("Driver route created successfully", route_id=route_id)
            
            return route_id
            
        except Exception as e:
            logger.error("Error creating driver route", error=str(e))
            raise DataRetrievalError(f"Erreur lors de la création de la route: {str(e)}")
    
    async def get_depot_locations(self) -> List[Dict]:
        """
        Récupère toutes les locations de type depot
        
        Returns:
            List[Dict]: Liste des depots
        """
        logger.info("Retrieving depot locations")
        
        try:
            # Note: Utiliser le client de base directement pour la table 'depot'
            result = supabase_base_client.select("depot", "*")
            
            if result["status"] != "success":
                raise DataRetrievalError(f"Erreur lors de la récupération des dépôts: {result['message']}")
            
            depots = result["data"]
            logger.info("Depot locations retrieved successfully", count=len(depots))
            
            return depots
            
        except Exception as e:
            logger.error("Error retrieving depot locations", error=str(e))
            raise DataRetrievalError(f"Erreur lors de la récupération des dépôts: {str(e)}")
    
    async def clean_existing_routes(self, target_date: date) -> int:
        """
        Nettoie les tournées pending/optimized du jour
        
        Args:
            target_date: Date cible
            
        Returns:
            int: Nombre de tournées supprimées
            
        Raises:
            DataRetrievalError: Si erreur lors du nettoyage
        """
        logger.info("Cleaning existing routes", date=str(target_date))
        
        try:
            # Utiliser le repository des routes
            result = self.routes_repo.delete_routes_by_conditions(
                str(target_date), 
                ["pending", "optimized"]
            )
            
            if result["status"] != "success":
                raise DataRetrievalError(f"Erreur lors du nettoyage des routes: {result['message']}")
            
            deleted_count = result["deleted_count"]
            logger.info("Routes cleaned successfully", 
                       count=deleted_count,
                       deleted_routes=result.get("deleted_routes", []))
            
            return deleted_count
            
        except Exception as e:
            logger.error("Error cleaning existing routes", error=str(e))
            raise DataRetrievalError(f"Erreur lors du nettoyage des routes: {str(e)}")
    
    async def create_driver_route(self, route_data: Dict) -> str:
        """
        Crée une nouvelle driver_route
        
        Args:
            route_data: Données de la route à créer
            
        Returns:
            str: ID de la route créée
            
        Raises:
            DataRetrievalError: Si erreur lors de la création
        """
        logger.info("Creating driver route", driver_id=route_data.get("driver_id"))
        
        try:
            result = self.routes_repo.create_driver_route(route_data)
            
            if result["status"] != "success":
                raise DataRetrievalError(f"Erreur lors de la création de la route: {result['message']}")
            
            route_id = result["data"][0]["id"]
            logger.info("Driver route created successfully", route_id=route_id)
            
            return route_id
            
        except Exception as e:
            logger.error("Error creating driver route", error=str(e))
            raise DataRetrievalError(f"Erreur lors de la création de la route: {str(e)}")
    
    async def create_route_stop(self, stop_data: Dict) -> str:
        """
        Crée un nouveau driver_route_stop
        
        Args:
            stop_data: Données du stop à créer
            
        Returns:
            str: ID du stop créé
            
        Raises:
            DataRetrievalError: Si erreur lors de la création
        """
        try:
            result = self.stops_repo.create_stop(stop_data)
            
            if result["status"] != "success":
                raise DataRetrievalError(f"Erreur lors de la création du stop: {result['message']}")
            
            stop_id = result["data"][0]["id"]
            return stop_id
            
        except Exception as e:
            logger.error("Error creating route stop", error=str(e))
            raise DataRetrievalError(f"Erreur lors de la création du stop: {str(e)}")
    
    async def create_route_shipment(self, shipment_data: Dict) -> str:
        """
        Crée un nouveau driver_route_shipment
        
        Args:
            shipment_data: Données du shipment à créer
            
        Returns:
            str: ID du shipment créé
            
        Raises:
            DataRetrievalError: Si erreur lors de la création
        """
        try:
            result = self.driver_shipments_repo.create_shipment(shipment_data)
            
            if result["status"] != "success":
                raise DataRetrievalError(f"Erreur lors de la création du shipment: {result['message']}")
            
            shipment_id = result["data"][0]["id"]
            return shipment_id
            
        except Exception as e:
            logger.error("Error creating route shipment", error=str(e))
            raise DataRetrievalError(f"Erreur lors de la création du shipment: {str(e)}")
    
    async def get_route_by_id(self, route_id: str) -> Optional[Dict]:
        """
        Récupère une route par son ID
        
        Args:
            route_id: ID de la route
            
        Returns:
            Dict: Données de la route ou None si non trouvée
        """
        try:
            result = self.routes_repo.get_route_by_id(route_id)
            
            if result["status"] == "success" and result["data"]:
                return result["data"][0]
            
            return None
            
        except Exception as e:
            logger.error("Error retrieving route by ID", route_id=route_id, error=str(e))
            return None
    
    async def get_route_stops(self, route_id: str) -> List[Dict]:
        """
        Récupère tous les stops d'une route
        
        Args:
            route_id: ID de la route
            
        Returns:
            List[Dict]: Liste des stops
        """
        try:
            result = self.stops_repo.get_stops_by_route_id(route_id)
            
            if result["status"] == "success":
                return result["data"]
            
            return []
            
        except Exception as e:
            logger.error("Error retrieving route stops", route_id=route_id, error=str(e))
            return []
    
    async def get_route_shipments(self, route_id: str) -> List[Dict]:
        """
        Récupère tous les shipments d'une route
        
        Args:
            route_id: ID de la route
            
        Returns:
            List[Dict]: Liste des shipments
        """
        try:
            result = self.driver_shipments_repo.get_shipments_by_route_id(route_id)
            
            if result["status"] == "success":
                return result["data"]
            
            return []
            
        except Exception as e:
            logger.error("Error retrieving route shipments", route_id=route_id, error=str(e))
            return []
    
    # ============================================================================
    # MÉTHODES D'OPTIMISATION - Extensions pour OR-Tools
    # ============================================================================
    
    async def get_enriched_route_stops(self, route_id: str) -> List[Dict]:
        """
        Récupère tous les stops d'une route avec leurs coordonnées GPS en une requête optimisée
        
        Cette méthode optimise les performances en joignant directement driver_route_stops 
        avec locations, évitant ainsi les requêtes multiples.
        
        Args:
            route_id: ID de la route
            
        Returns:
            List[Dict]: Liste des stops enrichis avec coordonnées
            Format de chaque stop:
            {
                "id": "uuid",
                "route_id": "uuid", 
                "location_id": "uuid",
                "stop_order": int,
                "stop_type": str,
                "client_actions": str,
                "is_shared_pickup_stop": bool,
                "latitude": float,
                "longitude": float,
                "formatted_address": str,
                "location_type": str,
                "estimated_arrival_time": str,
                "estimated_departure_time": str,
                "distance_from_previous": float,
                "duration_from_previous": int
            }
            
        Raises:
            DataRetrievalError: Si erreur lors de la récupération
        """
        logger.info("Retrieving enriched route stops for optimization", route_id=route_id)
        
        try:
            # Requête optimisée avec jointure stops + locations
            # Utilisation du client de base pour une requête personnalisée
            query = """
            SELECT 
                drs.*,
                l.latitude,
                l.longitude,
                l.formatted_address,
                l.type as location_type
            FROM driver_route_stops drs
            JOIN locations l ON drs.location_id = l.id
            WHERE drs.route_id = %s
            ORDER BY drs.stop_order
            """
            
            # Note: Utiliser execute_rpc avec une fonction Supabase custom ou adapter selon votre client
            # Pour l'instant, on utilise la méthode existante et on enrichit
            stops_result = await self.get_route_stops(route_id)
            
            if not stops_result:
                logger.warning("No stops found for route", route_id=route_id)
                return []
            
            # Récupérer la map des locations
            locations_map = await self.get_locations_map()
            
            # Enrichir chaque stop avec les coordonnées
            enriched_stops = []
            for stop in stops_result:
                location_id = stop.get("location_id")
                location_data = locations_map.get(location_id, {})
                
                enriched_stop = {
                    # Données du stop
                    "id": stop.get("id"),
                    "route_id": stop.get("route_id"),
                    "location_id": location_id,
                    "stop_order": stop.get("stop_order"),
                    "stop_type": stop.get("stop_type"),
                    "client_actions": stop.get("client_actions"),
                    "is_shared_pickup_stop": stop.get("is_shared_pickup_stop", False),
                    
                    # Données temporelles (pour optimisation)
                    "estimated_arrival_time": stop.get("estimated_arrival_time"),
                    "estimated_departure_time": stop.get("estimated_departure_time"),
                    "distance_from_previous": stop.get("distance_from_previous"),
                    "duration_from_previous": stop.get("duration_from_previous"),
                    
                    # Coordonnées GPS (critiques pour OR-Tools)
                    "latitude": location_data.get("latitude"),
                    "longitude": location_data.get("longitude"),
                    "formatted_address": location_data.get("formatted_address"),
                    "location_type": location_data.get("type"),
                    
                    # Métadonnées
                    "completed": stop.get("completed", False),
                    "arrival_time": stop.get("arrival_time"),
                    "is_late_stop": stop.get("is_late_stop", False),
                    "created_at": stop.get("created_at")
                }
                
                # Validation des données critiques
                if enriched_stop["latitude"] is None or enriched_stop["longitude"] is None:
                    logger.warning("Stop missing GPS coordinates", 
                                 stop_id=stop.get("id"),
                                 location_id=location_id)
                
                enriched_stops.append(enriched_stop)
            
            logger.info("Enriched route stops retrieved successfully", 
                       route_id=route_id,
                       stops_count=len(enriched_stops),
                       stops_with_gps=sum(1 for s in enriched_stops if s["latitude"] and s["longitude"]))
            
            return enriched_stops
            
        except Exception as e:
            logger.error("Error retrieving enriched route stops", 
                        route_id=route_id, 
                        error=str(e))
            raise DataRetrievalError(f"Erreur lors de la récupération des stops enrichis: {str(e)}")
    
    async def get_tour_optimization_data(self, route_id: str) -> Dict:
        """
        Package complet de données pour l'optimisation OR-Tools d'une tournée
        
        Cette méthode récupère TOUTES les données nécessaires pour OR-Tools en un seul appel :
        - Route info (driver, date, status)
        - Driver info (start_time)
        - Start location (point de départ OR-Tools)
        - Stops enrichis avec coordonnées GPS
        - Shipments avec relations pickup/delivery
        - Contraintes géographiques
        
        Args:
            route_id: ID de la route à optimiser
            
        Returns:
            Dict: Package complet d'optimisation
            {
                "route": {
                    "id": str,
                    "driver_id": str, 
                    "date": str,
                    "status": str
                },
                "driver": {
                    "id": str,
                    "name": str,
                    "start_time": str  # Ex: "19:00"
                },
                "start_location": {
                    "id": str,
                    "latitude": float,
                    "longitude": float,
                    "formatted_address": str
                },
                "stops": List[Dict],  # Stops enrichis avec GPS
                "shipments": List[Dict],  # Shipments avec pickup/delivery relations
                "constraints": {
                    "geographic_restrictions": List[Dict],
                    "time_windows": Dict,
                    "vehicle_capacity": int
                },
                "metadata": {
                    "total_stops": int,
                    "total_shipments": int,
                    "data_quality_score": float,
                    "ready_for_optimization": bool
                }
            }
            
        Raises:
            DataRetrievalError: Si erreur lors de la récupération ou données incomplètes
        """
        logger.info("Building complete optimization data package", route_id=route_id)
        
        try:
            # 1. Récupérer les données de base en parallèle
            route_data = await self.get_route_by_id(route_id)
            if not route_data:
                raise DataRetrievalError(f"Route non trouvée: {route_id}")
            
            # 2. Récupérer les informations du driver avec start_time (NOUVEAU)
            try:
                driver_result = self.drivers_repo.get_driver_with_start_info(route_data["driver_id"])
                if driver_result["status"] == "success" and driver_result["data"]:
                    driver_data = driver_result["data"][0]
                else:
                    # Fallback : créer un driver par défaut
                    logger.warning("Driver not found, using fallback", driver_id=route_data["driver_id"])
                    driver_data = {
                        "id": route_data["driver_id"],
                        "name": f"Driver {route_data['driver_id'][:8]}",
                        "start_time": "07:00"  # Valeur par défaut
                    }
            except Exception as e:
                logger.error("Error retrieving driver info, using fallback", error=str(e))
                driver_data = {
                    "id": route_data["driver_id"],
                    "name": f"Driver {route_data['driver_id'][:8]}",
                    "start_time": "07:00"  # Valeur par défaut
                }
            
            # 3. Récupérer les coordonnées de start_location (NOUVEAU)
            start_location_data = await self._get_start_location_coordinates()
            
            # 4. Récupérer les stops enrichis avec coordonnées
            stops_data = await self.get_enriched_route_stops(route_id)
            
            # 5. Récupérer les shipments
            shipments_data = await self.get_route_shipments(route_id)
            
            # 6. Analyser les contraintes géographiques (avec start_time)
            constraints = self._build_optimization_constraints(stops_data, route_data, driver_data)
            
            # 7. Validation et calcul du score de qualité des données
            metadata = self._analyze_optimization_data_quality(
                route_data, stops_data, shipments_data
            )
            
            # 8. Package final avec données driver et start_location
            optimization_package = {
                "route": {
                    "id": route_data["id"],
                    "driver_id": route_data["driver_id"],
                    "date": route_data["date"],
                    "status": route_data["status"],
                    "estimated_duration": route_data.get("estimated_duration"),
                    "total_distance_km": route_data.get("total_distance_km")
                },
                "driver": {
                    "id": driver_data["id"],
                    "name": driver_data.get("full_name"),  # Utiliser full_name de la DB
                    "start_time": driver_data.get("start_time")  # Ex: "19:00"
                },
                "start_location": start_location_data,
                "stops": stops_data,
                "shipments": shipments_data,
                "constraints": constraints,
                "metadata": metadata
            }
            
            logger.info("Optimization data package built successfully", 
                       route_id=route_id,
                       driver_id=driver_data["id"],
                       driver_start_time=driver_data.get("start_time"),
                       start_location_coords=f"{start_location_data['latitude']}, {start_location_data['longitude']}",
                       stops_count=len(stops_data),
                       shipments_count=len(shipments_data),
                       data_quality_score=metadata["data_quality_score"],
                       ready_for_optimization=metadata["ready_for_optimization"])
            
            return optimization_package
            
        except Exception as e:
            logger.error("Error building optimization data package", 
                        route_id=route_id, 
                        error=str(e))
            raise DataRetrievalError(f"Erreur lors de la construction du package d'optimisation: {str(e)}")
    
    async def _get_start_location_coordinates(self) -> Dict:
        """
        Récupère les coordonnées de la start_location
        
        Returns:
            Dict: Coordonnées de la start_location
        """
        START_LOCATION_UUID = "08831414-5482-4822-86dd-6170633135f7"
        
        try:
            locations_map = await self.get_locations_map()
            start_location = locations_map.get(START_LOCATION_UUID)
            
            if not start_location:
                raise DataRetrievalError(f"Start location non trouvée: {START_LOCATION_UUID}")
            
            return {
                "id": START_LOCATION_UUID,
                "latitude": start_location.get("latitude"),
                "longitude": start_location.get("longitude"),
                "formatted_address": start_location.get("formatted_address", "Point de départ"),
                "type": start_location.get("type")
            }
            
        except Exception as e:
            logger.error("Error retrieving start location coordinates", error=str(e))
            raise DataRetrievalError(f"Erreur lors de la récupération de start_location: {str(e)}")
    
    def _build_optimization_constraints(self, stops_data: List[Dict], route_data: Dict, driver_data: Dict = None) -> Dict:
        """
        Construit les contraintes d'optimisation basées sur les données de la tournée
        
        Args:
            stops_data: Stops enrichis avec coordonnées
            route_data: Données de la route
            driver_data: Données du driver (NOUVEAU: avec start_time)
            
        Returns:
            Dict: Contraintes d'optimisation
        """
        # Codes postaux restreints (Marseille centre-ville)
        RESTRICTED_POSTAL_CODES = ["13001", "13006"]
        MIN_TOUR_DURATION_BEFORE_RESTRICTED = 90  # 1h30 en minutes
        
        # Récupérer le start_time du driver (NOUVEAU)
        driver_start_time = driver_data.get("start_time", "07:00") if driver_data else "07:00"
        
        constraints = {
            "geographic_restrictions": [],
            "time_windows": {
                "driver_start_time": driver_start_time,  # NOUVEAU: Heure de départ du driver
                "earliest_start": "07:00",
                "latest_end": "18:00",
                "restricted_zones_earliest": "13:30"
            },
            "vehicle_capacity": 100,  # À adapter selon vos véhicules
            "service_times": {
                "depot_pickup": 15,    # minutes
                "depot_dropoff": 10,
                "lab_pickup": 10,
                "lab_dropoff": 8,
                "client_pickup": 5,
                "client_delivery": 5
            }
        }
        
        # Identifier les stops dans les zones restreintes
        for stop in stops_data:
            address = stop.get("formatted_address", "")
            is_restricted = any(code in address for code in RESTRICTED_POSTAL_CODES)
            
            if is_restricted:
                constraints["geographic_restrictions"].append({
                    "stop_id": stop["id"],
                    "location_id": stop["location_id"],
                    "restriction_type": "time_window",
                    "earliest_visit_minutes": MIN_TOUR_DURATION_BEFORE_RESTRICTED,
                    "reason": "marseille_center_parking_restrictions",
                    "address": address
                })
        
        return constraints
    
    def _analyze_optimization_data_quality(self, route_data: Dict, stops_data: List[Dict], 
                                         shipments_data: List[Dict]) -> Dict:
        """
        Analyse la qualité des données pour l'optimisation OR-Tools
        
        Args:
            route_data: Données de la route
            stops_data: Stops enrichis
            shipments_data: Shipments
            
        Returns:
            Dict: Métadonnées de qualité
        """
        issues = []
        
        # Vérifications critiques
        stops_with_gps = sum(1 for s in stops_data if s.get("latitude") and s.get("longitude"))
        complete_shipments = sum(1 for s in shipments_data 
                               if s.get("pickup_stop_id") and s.get("delivery_stop_id"))
        
        if stops_with_gps < len(stops_data):
            issues.append(f"{len(stops_data) - stops_with_gps} stops manquent de coordonnées GPS")
        
        if complete_shipments < len(shipments_data):
            issues.append(f"{len(shipments_data) - complete_shipments} shipments incomplets")
        
        if not stops_data:
            issues.append("Aucun stop trouvé pour cette route")
        
        if not shipments_data:
            issues.append("Aucun shipment trouvé pour cette route")
        
        # Score de qualité (0-1)
        max_score = 4
        score = max_score
        
        if stops_with_gps < len(stops_data):
            score -= 2
        if complete_shipments < len(shipments_data):
            score -= 1
        if not stops_data or not shipments_data:
            score -= 1
        
        data_quality_score = max(0, score / max_score)
        
        return {
            "total_stops": len(stops_data),
            "stops_with_gps": stops_with_gps,
            "total_shipments": len(shipments_data),
            "complete_shipments": complete_shipments,
            "data_quality_score": data_quality_score,
            "ready_for_optimization": (
                data_quality_score >= 0.8 and 
                len(stops_data) > 0 and 
                len(shipments_data) > 0
            ),
            "issues": issues
        }
