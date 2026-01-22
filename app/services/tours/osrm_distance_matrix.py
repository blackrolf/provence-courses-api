"""
Service de génération de matrice de distances via OSRM local
Optimisé avec batching et retry pour éviter les timeouts
"""

import structlog
import httpx
import asyncio
from typing import Dict, List, Tuple, Any
import os
import time

logger = structlog.get_logger()

# Configuration OSRM optimisée
# L'API Table OSRM peut gérer des centaines de coordonnées en une seule requête
# Voir: https://github.com/Project-OSRM/osrm-backend/issues/2326
OSRM_TABLE_API_MAX_COORDS = 100  # Limite pour l'API Table (peut être plus élevée)
OSRM_TIMEOUT = 15.0  # Timeout pour l'API Table
OSRM_FALLBACK_TIMEOUT = 5.0  # Timeout pour les appels individuels en fallback
OSRM_MAX_RETRIES = 2  # Nombre de tentatives
OSRM_RETRY_DELAY = 0.5  # Délai entre les tentatives
OSRM_CONCURRENT_REQUESTS = 4  # Nombre de requêtes parallèles max (pour fallback)


class OSRMDistanceMatrixService:
    """Service de génération de matrice de distances via OSRM local"""

    def __init__(self):
        self.osrm_url = os.getenv("OSRM_URL", "http://localhost:5000")
        self._semaphore = asyncio.Semaphore(OSRM_CONCURRENT_REQUESTS)
        
    async def generate_distance_matrix_for_route(self, stops_data: List[Dict]) -> Dict:
        """
        Génère une matrice de distances complète pour tous les stops d'une route
        
        IMPORTANT: Préserve les UUIDs des stops pour la traçabilité OR-Tools
        
        Args:
            stops_data: Liste des stops enrichis avec coordonnées GPS
            Format attendu: [{"id": "uuid", "latitude": float, "longitude": float, ...}]
            
        Returns:
            Dict: Matrice avec mapping UUID preserved
            {
                "distance_matrix": [[int]],           # Matrice NxN distances en mètres
                "duration_matrix": [[int]],           # Matrice NxN durées en secondes  
                "stops_mapping": [                    # Préservation des UUIDs
                    {
                        "index": 0,                   # Index dans la matrice
                        "stop_id": "uuid",            # UUID original du stop
                        "coordinates": [lon, lat],    # Coordonnées utilisées
                        "stop_type": "depot_pickup",  # Type du stop
                        "location_id": "uuid"         # UUID de la location
                    }
                ],
                "depot_index": int,                   # Index du dépôt dans la matrice
                "matrix_size": int,                   # Taille de la matrice (N)
                "osrm_metadata": {
                    "api_calls": int,
                    "processing_time": float,
                    "total_coordinates": int
                }
            }
            
        Raises:
            OSRMServiceError: Si erreur lors de la génération
        """
        logger.info("Generating OSRM distance matrix for route", 
                   stops_count=len(stops_data))
        
        if len(stops_data) < 2:
            raise OSRMServiceError("Au moins 2 stops requis pour générer une matrice")
        
        try:
            # 1. Préparer les coordonnées et mapping
            coordinates, stops_mapping = self._prepare_coordinates_and_mapping(stops_data)
            
            # 2. Identifier l'index du dépôt
            depot_index = await self._identify_depot_index(stops_data, stops_mapping)
            
            # 3. Appeler OSRM Table API pour générer la matrice
            matrix_result = await self._call_osrm_table_api(coordinates)
            
            # 4. Valider et structurer les résultats
            final_result = {
                "distance_matrix": matrix_result["distances"],
                "duration_matrix": matrix_result["durations"], 
                "stops_mapping": stops_mapping,
                "depot_index": depot_index,
                "matrix_size": len(stops_data),
                "osrm_metadata": {
                    "api_calls": 1,
                    "processing_time": matrix_result["processing_time"],
                    "total_coordinates": len(coordinates),
                    "osrm_url": self.osrm_url
                }
            }
            
            # 5. Validation de cohérence
            self._validate_matrix_consistency(final_result)
            
            logger.info("OSRM distance matrix generated successfully",
                       matrix_size=final_result["matrix_size"],
                       depot_index=depot_index,
                       processing_time=matrix_result["processing_time"])
            
            return final_result
            
        except Exception as e:
            logger.error("Error generating OSRM distance matrix", error=str(e))
            raise OSRMServiceError(f"Erreur lors de la génération de la matrice OSRM: {str(e)}")
    
    def _prepare_coordinates_and_mapping(self, stops_data: List[Dict]) -> Tuple[List[List[float]], List[Dict]]:
        """
        Prépare les coordonnées pour OSRM et créé le mapping de traçabilité
        
        Args:
            stops_data: Stops enrichis avec GPS
            
        Returns:
            Tuple: (coordinates, stops_mapping)
        """
        coordinates = []
        stops_mapping = []
        
        for index, stop in enumerate(stops_data):
            # Vérification des coordonnées
            lat = stop.get("latitude")
            lon = stop.get("longitude")
            
            if lat is None or lon is None:
                raise OSRMServiceError(f"Stop {stop.get('id')} manque de coordonnées GPS")
            
            # OSRM attend [longitude, latitude] (attention à l'ordre !)
            coordinates.append([float(lon), float(lat)])
            
            # Mapping pour préserver l'UUID et traçabilité
            stops_mapping.append({
                "index": index,
                "stop_id": stop["id"],
                "coordinates": [float(lon), float(lat)],
                "stop_type": stop.get("stop_type"),
                "location_id": stop.get("location_id"),
                "stop_order": stop.get("stop_order"),
                "formatted_address": stop.get("formatted_address", "")
            })
        
        logger.debug("Coordinates prepared for OSRM",
                    total_coords=len(coordinates),
                    first_coord=coordinates[0] if coordinates else None)
        
        return coordinates, stops_mapping
    
    async def _identify_depot_index(self, stops_data: List[Dict], stops_mapping: List[Dict]) -> int:
        """
        Identifie l'index du dépôt dans la matrice
        
        Le dépôt est soit :
        1. Un stop avec location_id = start_location UUID
        2. Un stop de type depot_pickup ou depot_dropoff
        
        IMPORTANT: start_location doit TOUJOURS être l'index 0 pour OR-Tools.
        Si start_location n'est pas dans les stops existants, elle sera ajoutée automatiquement.
        
        Args:
            stops_data: Données des stops
            stops_mapping: Mapping des index
            
        Returns:
            int: Index du dépôt dans la matrice (toujours 0 pour start_location)
        """
        # UUID de la start_location identifiée dans la base
        START_LOCATION_UUID = "08831414-5482-4822-86dd-6170633135f7"
        
        # Méthode 1 : Chercher par location_id (start_location)
        for mapping in stops_mapping:
            if mapping["location_id"] == START_LOCATION_UUID:
                logger.info("Depot identified by start_location UUID",
                           depot_index=mapping["index"],
                           location_id=START_LOCATION_UUID)
                return mapping["index"]
        
        # Méthode 2 : Chercher par type depot
        depot_types = ["depot_pickup", "depot_dropoff"]
        for mapping in stops_mapping:
            if mapping["stop_type"] in depot_types:
                logger.info("Depot identified by stop_type",
                           depot_index=mapping["index"],
                           stop_type=mapping["stop_type"])
                return mapping["index"]
        
        # Fallback : Premier stop par défaut
        logger.warning("No depot identified, using first stop as depot",
                      first_stop_id=stops_mapping[0]["stop_id"])
        return 0
    
    async def generate_distance_matrix_with_start_location(self, stops_data: List[Dict], 
                                                          start_location_coords: Dict) -> Dict:
        """
        Génère une matrice avec la start_location en index 0 (requis OR-Tools)
        
        Cette méthode s'assure que start_location est TOUJOURS le premier élément
        de la matrice de distances, comme requis par OR-Tools pour définir le dépôt.
        
        Args:
            stops_data: Liste des stops de la route
            start_location_coords: Coordonnées de la start_location
                {"latitude": float, "longitude": float, "formatted_address": str}
                
        Returns:
            Dict: Matrice avec start_location à l'index 0
        """
        logger.info("Generating distance matrix with start_location as depot",
                   stops_count=len(stops_data),
                   start_location_coords=start_location_coords)
        
        # Créer un pseudo-stop pour start_location
        start_location_stop = {
            "id": f"start_location_{start_location_coords.get('id', 'depot')}",
            "location_id": "08831414-5482-4822-86dd-6170633135f7",
            "latitude": start_location_coords["latitude"],
            "longitude": start_location_coords["longitude"],
            "stop_type": "depot_start",
            "stop_order": 0,
            "formatted_address": start_location_coords.get("formatted_address", "Point de départ")
        }
        
        # Vérifier si start_location existe déjà dans les stops
        start_location_exists = any(
            stop.get("location_id") == "08831414-5482-4822-86dd-6170633135f7" 
            for stop in stops_data
        )
        
        if start_location_exists:
            logger.info("Start location already exists in stops, using standard matrix generation")
            return await self.generate_distance_matrix_for_route(stops_data)
        
        # Ajouter start_location en première position
        extended_stops = [start_location_stop] + stops_data
        
        logger.info("Start location added as first stop", total_stops=len(extended_stops))
        
        # Générer la matrice avec start_location incluse
        matrix_result = await self.generate_distance_matrix_for_route(extended_stops)
        
        # Marquer que l'index 0 est le dépôt
        matrix_result["depot_index"] = 0
        matrix_result["start_location_added"] = True
        matrix_result["original_stops_count"] = len(stops_data)
        
        logger.info("Distance matrix with start_location generated successfully",
                   matrix_size=matrix_result["matrix_size"],
                   depot_confirmed_at_index_0=True)
        
        return matrix_result
    
    async def _call_osrm_table_api(self, coordinates: List[List[float]]) -> Dict:
        """
        Appelle l'API OSRM Table pour générer la matrice
        Utilise TOUJOURS l'API Table en premier (beaucoup plus rapide)
        Fallback vers appels individuels uniquement si l'API Table échoue

        Args:
            coordinates: Liste des coordonnées [[lon, lat], ...]

        Returns:
            Dict: Résultat OSRM avec distances et durées
        """
        start_time = time.time()
        n = len(coordinates)

        logger.info("Calling OSRM Table API",
                   coordinates_count=n,
                   expected_elements=n * n)

        # Toujours essayer l'API Table en premier (très rapide: ~0.02s pour 50 coords)
        try:
            result = await self._call_osrm_table_api_single(coordinates)
            processing_time = time.time() - start_time
            logger.info("OSRM Table API success",
                       matrix_size=n,
                       processing_time=f"{processing_time:.3f}s")
            return result
        except Exception as table_error:
            logger.warning("OSRM Table API failed, using individual route fallback",
                          error=str(table_error),
                          coordinates_count=n)

            # Fallback vers appels individuels (plus lent mais plus robuste)
            try:
                result = await self._call_osrm_table_api_batched(coordinates)
                processing_time = time.time() - start_time
                logger.info("OSRM fallback completed",
                           matrix_size=n,
                           processing_time=f"{processing_time:.3f}s")
                return result
            except Exception as fallback_error:
                logger.error("OSRM fallback also failed",
                            error=str(fallback_error))
                raise OSRMServiceError(f"OSRM API failed: Table API: {table_error}, Fallback: {fallback_error}")

    async def _call_osrm_table_api_single(self, coordinates: List[List[float]]) -> Dict:
        """
        Appel unique à l'API OSRM Table avec retry
        """
        start_time = time.time()

        # Construire l'URL OSRM Table
        coords_str = ";".join([f"{lon},{lat}" for lon, lat in coordinates])
        url = f"{self.osrm_url}/table/v1/driving/{coords_str}"

        # Paramètres pour obtenir à la fois distances et durées
        params = {
            "annotations": "distance,duration"
        }

        last_error = None

        for attempt in range(OSRM_MAX_RETRIES):
            try:
                async with self._semaphore:
                    async with httpx.AsyncClient(timeout=OSRM_TIMEOUT) as client:
                        logger.debug("Calling OSRM Table API",
                                    coordinates_count=len(coordinates),
                                    attempt=attempt + 1)

                        response = await client.get(url, params=params)

                        if response.status_code != 200:
                            raise OSRMServiceError(f"OSRM API erreur {response.status_code}: {response.text}")

                        result = response.json()

                        if result.get("code") != "Ok":
                            raise OSRMServiceError(f"OSRM erreur: {result.get('message', 'Erreur inconnue')}")

                        processing_time = time.time() - start_time

                        return {
                            "distances": result["distances"],
                            "durations": result["durations"],
                            "processing_time": processing_time
                        }

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                logger.warning("OSRM request timeout/error, retrying",
                              attempt=attempt + 1,
                              max_retries=OSRM_MAX_RETRIES,
                              error=str(e))
                if attempt < OSRM_MAX_RETRIES - 1:
                    await asyncio.sleep(OSRM_RETRY_DELAY * (attempt + 1))
            except Exception as e:
                last_error = e
                logger.error("OSRM unexpected error", error=str(e))
                break

        raise OSRMServiceError(f"OSRM API échoué après {OSRM_MAX_RETRIES} tentatives: {str(last_error)}")

    async def _call_osrm_table_api_batched(self, coordinates: List[List[float]]) -> Dict:
        """
        Génère la matrice par batches pour éviter de surcharger OSRM
        Utilise des appels route individuels avec rate limiting
        """
        start_time = time.time()
        n = len(coordinates)

        # Initialiser les matrices
        distances = [[0] * n for _ in range(n)]
        durations = [[0] * n for _ in range(n)]

        logger.info("Starting batched OSRM matrix generation",
                   matrix_size=n,
                   total_pairs=n * n)

        # Créer toutes les paires à calculer (en excluant la diagonale)
        pairs_to_calculate = []
        for i in range(n):
            for j in range(n):
                if i != j:
                    pairs_to_calculate.append((i, j))

        # Traiter par batches avec rate limiting
        batch_size = 50  # Nombre de paires par batch
        total_batches = (len(pairs_to_calculate) + batch_size - 1) // batch_size

        for batch_idx in range(0, len(pairs_to_calculate), batch_size):
            batch = pairs_to_calculate[batch_idx:batch_idx + batch_size]
            current_batch = batch_idx // batch_size + 1

            logger.debug("Processing OSRM batch",
                        batch=current_batch,
                        total_batches=total_batches,
                        pairs_in_batch=len(batch))

            # Traiter les paires de ce batch en parallèle limité
            tasks = []
            for i, j in batch:
                task = self._get_single_route(coordinates[i], coordinates[j], i, j)
                tasks.append(task)

            # Exécuter avec concurrence limitée
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Traiter les résultats
            for idx, result in enumerate(results):
                i, j = batch[idx]
                if isinstance(result, Exception):
                    logger.warning("Route calculation failed, using fallback",
                                  from_idx=i, to_idx=j, error=str(result))
                    distances[i][j] = 10000  # 10km fallback
                    durations[i][j] = 600    # 10min fallback
                else:
                    distances[i][j] = result["distance"]
                    durations[i][j] = result["duration"]

            # Petit délai entre les batches pour ne pas surcharger OSRM
            if batch_idx + batch_size < len(pairs_to_calculate):
                await asyncio.sleep(0.1)

        processing_time = time.time() - start_time

        logger.info("Batched OSRM matrix generation completed",
                   matrix_size=n,
                   processing_time=processing_time,
                   pairs_calculated=len(pairs_to_calculate))

        return {
            "distances": distances,
            "durations": durations,
            "processing_time": processing_time
        }

    async def _get_single_route(self, from_coord: List[float], to_coord: List[float],
                                 i: int, j: int) -> Dict:
        """
        Obtient la distance/durée entre deux points avec retry
        """
        url = f"{self.osrm_url}/route/v1/driving/{from_coord[0]},{from_coord[1]};{to_coord[0]},{to_coord[1]}?overview=false"

        for attempt in range(OSRM_MAX_RETRIES):
            try:
                async with self._semaphore:
                    async with httpx.AsyncClient(timeout=OSRM_TIMEOUT) as client:
                        response = await client.get(url)

                        if response.status_code == 200:
                            data = response.json()
                            if data.get("code") == "Ok" and data.get("routes"):
                                route = data["routes"][0]
                                return {
                                    "distance": int(route.get("distance", 0)),
                                    "duration": int(route.get("duration", 0))
                                }

                        raise OSRMServiceError(f"OSRM route error: {response.status_code}")

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt < OSRM_MAX_RETRIES - 1:
                    await asyncio.sleep(OSRM_RETRY_DELAY * (attempt + 1))
                else:
                    raise OSRMServiceError(f"Route {i}→{j} failed: {str(e)}")
            except Exception as e:
                raise OSRMServiceError(f"Route {i}→{j} error: {str(e)}")
    
    def _validate_matrix_consistency(self, matrix_result: Dict) -> None:
        """Valide la cohérence de la matrice générée"""
        
        distance_matrix = matrix_result["distance_matrix"]
        duration_matrix = matrix_result["duration_matrix"]
        matrix_size = matrix_result["matrix_size"]
        
        # Vérifications de base
        if len(distance_matrix) != matrix_size:
            raise OSRMServiceError(f"Taille matrice distance incohérente: {len(distance_matrix)} vs {matrix_size}")
        
        if len(duration_matrix) != matrix_size:
            raise OSRMServiceError(f"Taille matrice durée incohérente: {len(duration_matrix)} vs {matrix_size}")
        
        # Vérifier que chaque ligne a la bonne taille
        for i, row in enumerate(distance_matrix):
            if len(row) != matrix_size:
                raise OSRMServiceError(f"Ligne {i} matrice distance taille incorrecte: {len(row)} vs {matrix_size}")
        
        # Vérifier que la diagonale est zéro (distance de soi à soi)
        for i in range(matrix_size):
            if distance_matrix[i][i] != 0:
                logger.warning("Distance diagonale non-zéro", index=i, distance=distance_matrix[i][i])
        
        logger.info("Matrix consistency validation passed",
                   matrix_size=matrix_size,
                   depot_index=matrix_result["depot_index"])
    
    def get_distance_between_stops(self, matrix_result: Dict, from_stop_id: str, to_stop_id: str) -> Dict:
        """
        Récupère la distance entre deux stops spécifiques en utilisant leurs UUIDs
        
        Args:
            matrix_result: Résultat de generate_distance_matrix_for_route
            from_stop_id: UUID du stop de départ
            to_stop_id: UUID du stop d'arrivée
            
        Returns:
            Dict: Distance et durée entre les deux stops
        """
        stops_mapping = matrix_result["stops_mapping"]
        
        # Trouver les index des stops
        from_index = None
        to_index = None
        
        for mapping in stops_mapping:
            if mapping["stop_id"] == from_stop_id:
                from_index = mapping["index"]
            if mapping["stop_id"] == to_stop_id:
                to_index = mapping["index"]
        
        if from_index is None:
            raise OSRMServiceError(f"Stop de départ non trouvé: {from_stop_id}")
        
        if to_index is None:
            raise OSRMServiceError(f"Stop d'arrivée non trouvé: {to_stop_id}")
        
        return {
            "from_stop_id": from_stop_id,
            "to_stop_id": to_stop_id,
            "distance_meters": matrix_result["distance_matrix"][from_index][to_index],
            "duration_seconds": matrix_result["duration_matrix"][from_index][to_index],
            "from_index": from_index,
            "to_index": to_index
        }


class OSRMServiceError(Exception):
    """Exception levée lors d'erreurs du service OSRM"""
    pass