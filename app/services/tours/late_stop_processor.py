"""
Service de traitement des arrêts de dernière minute
"""

import structlog
from datetime import datetime, date
from typing import List, Dict, Tuple, Optional
from app.services.tours.data_retriever import TourDataRetriever
from app.integrations.supabase.base_client import supabase_base_client
from app.services.tours.osrm_distance_matrix import OSRMDistanceMatrixService
from app.services.tours.depot_location_service import get_depot_location_id
from .exceptions import DataRetrievalError

logger = structlog.get_logger()


class LateStopProcessor:
    """Service de traitement des demandes d'arrêts de dernière minute"""
    
    def __init__(self):
        self.data_retriever = TourDataRetriever()
        self.supabase = supabase_base_client
        self.osrm_service = OSRMDistanceMatrixService()
    
    async def process_late_stop_request(self, late_stop_request_id: str) -> Dict:
        """
        Traite une demande d'arrêt de dernière minute complète
        
        Args:
            late_stop_request_id: ID de la demande dans lab_tour_late_stops
            
        Returns:
            Dict: Résultat du traitement avec détails de placement
            
        Raises:
            ValueError: Si demande invalide ou déjà traitée
            DataRetrievalError: Si erreur d'accès aux données
        """
        logger.info("Processing late stop request", late_stop_request_id=late_stop_request_id)
        
        try:
            # 1. Récupérer et valider la demande de late stop
            late_stop_data = await self._get_late_stop_request(late_stop_request_id)
            
            # 2. Récupérer les données de la tournée du laboratoire
            lab_tour_data = await self._get_lab_tour_data(late_stop_data["lab_tour_id"])
            
            # 3. Trouver la tournée driver correspondante pour ce client
            driver_route_data = await self._find_corresponding_driver_route(
                lab_tour_data["laboratory_id"], 
                lab_tour_data["date"],
                late_stop_data["client_id"]
            )
            
            # 4. Récupérer la séquence actuelle des stops de la tournée
            current_stops_sequence = await self._get_current_stops_sequence(driver_route_data["id"])
            
            # 5. Déterminer le placement optimal du/des nouveaux stop(s)
            placement_plan = await self._determine_stop_placement(
                late_stop_data, 
                lab_tour_data, 
                current_stops_sequence
            )
            
            # 6. Créer les nouveaux stops et shipments
            insertion_result = await self._create_late_stops_and_shipments(
                driver_route_data["id"],
                placement_plan,
                late_stop_data,
                lab_tour_data
            )
            
            # 7. Mettre à jour les stop_order de toute la séquence
            reorder_result = await self._update_stops_sequence(
                driver_route_data["id"],
                insertion_result["new_sequence"]
            )
            
            # 8. Marquer la demande comme approuvée
            await self._update_late_stop_status(late_stop_request_id, "approved")
            
            # Compiler le résultat final avec métriques
            result = {
                "driver_route_id": driver_route_data["id"],
                "inserted_stops": insertion_result["inserted_stops"],
                "placement_details": placement_plan,
                "created_shipments": insertion_result["created_shipments"],
                "tour_updates": {
                    "stops_before": len(current_stops_sequence),
                    "stops_after": len(insertion_result["new_sequence"]),
                    "stops_reordered": reorder_result["stops_updated"]
                },
                # NOUVELLES MÉTRIQUES POUR LE FRONT-END
                "impact_metrics": self._calculate_total_impact_metrics(placement_plan)
            }
            
            logger.info("Late stop request processed successfully",
                       late_stop_request_id=late_stop_request_id,
                       driver_route_id=driver_route_data["id"],
                       stops_inserted=len(insertion_result["inserted_stops"]))
            
            return result
            
        except Exception as e:
            logger.error("Error processing late stop request",
                        late_stop_request_id=late_stop_request_id,
                        error=str(e))
            # Marquer comme rejetée en cas d'erreur
            await self._update_late_stop_status(late_stop_request_id, "rejected", str(e))
            raise
    
    async def _get_late_stop_request(self, late_stop_request_id: str) -> Dict:
        """Récupère et valide la demande de late stop"""
        logger.debug("Fetching late stop request", request_id=late_stop_request_id)
        
        result = self.supabase.select(
            "lab_tour_late_stops",
            "*",
            id=late_stop_request_id
        )
        
        if result["status"] != "success" or not result["data"]:
            raise ValueError(f"Demande de late stop non trouvée: {late_stop_request_id}")
        
        late_stop_data = result["data"][0]
        
        # Valider le statut
        if late_stop_data["status"] != "pending":
            raise ValueError(f"Demande déjà traitée (statut: {late_stop_data['status']})")
        
        # Valider qu'au moins une action est demandée
        if not late_stop_data["has_pickup"] and not late_stop_data["has_delivery"]:
            raise ValueError("Aucune action (pickup/delivery) spécifiée dans la demande")
        
        logger.debug("Late stop request validated",
                    client_id=late_stop_data["client_id"],
                    has_pickup=late_stop_data["has_pickup"],
                    has_delivery=late_stop_data["has_delivery"])
        
        return late_stop_data
    
    async def _get_lab_tour_data(self, lab_tour_id: str) -> Dict:
        """Récupère les données de la tournée laboratoire"""
        logger.debug("Fetching lab tour data", lab_tour_id=lab_tour_id)
        
        result = self.supabase.select(
            "lab_tours",
            "*",
            id=lab_tour_id
        )
        
        if result["status"] != "success" or not result["data"]:
            raise DataRetrievalError(f"Tournée laboratoire non trouvée: {lab_tour_id}")
        
        return result["data"][0]
    
    async def _find_corresponding_driver_route(self, laboratory_id: str, tour_date: str, client_id: str) -> Dict:
        """
        Trouve la tournée driver correspondante via l'assignation du client concerné
        
        Logique métier:
        1. Récupérer le driver_id du client concerné par le late stop
        2. Chercher la dernière route de ce driver (date exacte ou J-1 pour tolérance)
        3. Si pas de driver assigné → erreur
        """
        logger.debug("Finding corresponding driver route via client assignment",
                    laboratory_id=laboratory_id,
                    date=tour_date,
                    client_id=client_id)
        
        # 1. Récupérer le driver assigné au client concerné
        client_result = self.supabase.select(
            "laboratory_clients",
            "driver_id, name",
            id=client_id
        )
        
        if client_result["status"] != "success" or not client_result["data"]:
            raise DataRetrievalError(f"Client non trouvé: {client_id}")
        
        client_data = client_result["data"][0]
        driver_id = client_data.get("driver_id")
        
        if not driver_id:
            raise ValueError(f"Aucun driver assigné au client '{client_data.get('name', client_id)}'. Late stop impossible.")
        
        logger.debug("Driver found for client", 
                    driver_id=driver_id,
                    client_name=client_data.get("name"))
        
        # 2. Chercher une route de ce driver pour AUJOURD'HUI seulement
        from datetime import datetime
        
        target_date = datetime.strptime(tour_date, "%Y-%m-%d").date()
        
        # PRIORITÉ 1: Chercher routes avec statut validated ou in_progress (prioritaires pour late stop)
        priority_statuses = ["validated", "in_progress"]
        driver_route = None
        
        for status in priority_statuses:
            route_result = self.supabase.select(
                "driver_routes",
                "*?order=created_at.desc",
                driver_id=driver_id,
                date=str(target_date),
                status=status
            )
            
            if route_result["status"] == "success" and route_result["data"]:
                driver_route = route_result["data"][0]
                logger.info(f"Found driver route with priority status '{status}'",
                           driver_route_id=driver_route["id"],
                           route_date=driver_route["date"],
                           status=status)
                break
        
        # PRIORITÉ 2: Si aucune route prioritaire, essayer "optimized" en fallback
        if not driver_route:
            route_result = self.supabase.select(
                "driver_routes",
                "*?order=created_at.desc",
                driver_id=driver_id,
                date=str(target_date),
                status="optimized"
            )
            
            if route_result["status"] == "success" and route_result["data"]:
                driver_route = route_result["data"][0]
                logger.info("Found driver route with fallback status 'optimized'",
                           driver_route_id=driver_route["id"],
                           route_date=driver_route["date"],
                           status="optimized")
        
        # Diagnostic détaillé si aucune route trouvée
        if not driver_route:
            # Chercher TOUTES les routes de ce driver pour diagnostic
            all_routes_result = self.supabase.select(
                "driver_routes",
                "id, date, status, created_at",
                driver_id=driver_id
            )
            
            debug_info = {
                "driver_id": driver_id,
                "search_date": str(target_date),
                "target_statuses": ["validated", "in_progress", "optimized"],
                "all_routes_found": []
            }
            
            if all_routes_result["status"] == "success" and all_routes_result["data"]:
                debug_info["all_routes_found"] = all_routes_result["data"]
                logger.error("No suitable driver route found", debug_info=debug_info)
            else:
                logger.error("No routes found at all for driver", driver_id=driver_id)
            
            raise DataRetrievalError(
                f"Aucune tournée active trouvée pour le driver {driver_id} "
                f"pour la date {target_date} (statuts: validated/in_progress/optimized). "
                f"Late stop impossible - la tournée doit exister le jour même."
            )
        
        logger.info("Driver route found via client assignment",
                   driver_route_id=driver_route["id"],
                   driver_id=driver_id,
                   route_date=driver_route["date"],
                   client_name=client_data.get("name"))
        
        return driver_route
    
    async def _get_current_stops_sequence(self, driver_route_id: str) -> List[Dict]:
        """Récupère la séquence actuelle des stops triée par stop_order"""
        logger.debug("Fetching current stops sequence", driver_route_id=driver_route_id)
        
        result = self.supabase.select(
            "driver_route_stops",
            "*?order=stop_order.asc",
            route_id=driver_route_id
        )
        
        if result["status"] != "success":
            raise DataRetrievalError(f"Erreur lors de la récupération des stops: {result['message']}")
        
        stops_sequence = result["data"]
        logger.debug("Current stops sequence retrieved", total_stops=len(stops_sequence))
        
        return stops_sequence
    
    async def _determine_stop_placement(self, late_stop_data: Dict, lab_tour_data: Dict, 
                                      current_stops: List[Dict]) -> Dict:
        """
        Détermine où placer le/les nouveaux stop(s) dans la séquence avec optimisation OSRM
        
        Logique:
        1. Déterminer le type d'action (pickup/delivery)
        2. Utiliser OSRM pour trouver le placement optimal par distance minimale
        3. Respecter les contraintes métier (pickups avant dropoffs)
        """
        logger.debug("Determining stop placement with OSRM optimization")
        
        # Récupérer les informations du client concerné
        client_data = await self._get_client_data(late_stop_data["client_id"])
        
        placement_plan = {
            "stops_to_insert": [],
            "insertion_points": [],
            "placement_metrics": {}
        }
        
        # ========== LOGIQUE MÉTIER AVEC OSRM ==========
        
        if late_stop_data["has_delivery"] and not late_stop_data["has_pickup"]:
            # 🚛 LIVRAISON DE DERNIÈRE MINUTE
            delivery_plan = await self._plan_late_delivery_with_osrm(client_data, current_stops)
            placement_plan.update(delivery_plan)
            
        elif late_stop_data["has_pickup"] and not late_stop_data["has_delivery"]:
            # 📦 RÉCUPÉRATION DE DERNIÈRE MINUTE  
            pickup_plan = await self._plan_late_pickup_with_osrm(client_data, lab_tour_data, current_stops)
            placement_plan.update(pickup_plan)
            
        elif late_stop_data["has_pickup"] and late_stop_data["has_delivery"]:
            # 🔄 PICKUP + DELIVERY (cas rare, mais possible)
            pickup_plan = await self._plan_late_pickup_with_osrm(client_data, lab_tour_data, current_stops)
            delivery_plan = await self._plan_late_delivery_with_osrm(client_data, current_stops)
            
            # Fusionner les plans
            placement_plan["stops_to_insert"].extend(pickup_plan["stops_to_insert"])
            placement_plan["stops_to_insert"].extend(delivery_plan["stops_to_insert"])
            placement_plan["existing_stops_used"] = {
                **pickup_plan.get("existing_stops_used", {}),
                **delivery_plan.get("existing_stops_used", {})
            }
            placement_plan["placement_metrics"].update(pickup_plan.get("placement_metrics", {}))
            placement_plan["placement_metrics"].update(delivery_plan.get("placement_metrics", {}))
            
        else:
            raise ValueError("Late stop doit avoir has_pickup=true OU has_delivery=true")
        
        logger.debug("Stop placement determined with OSRM",
                    stops_to_insert=len(placement_plan["stops_to_insert"]),
                    has_metrics=bool(placement_plan.get("placement_metrics")))
        
        return placement_plan
    
    async def _get_client_data(self, client_id: str) -> Dict:
        """Récupère les données enrichies du client"""
        result = self.supabase.select(
            "laboratory_clients",
            "*, locations(*)",
            id=client_id
        )
        
        if result["status"] != "success" or not result["data"]:
            raise DataRetrievalError(f"Client non trouvé: {client_id}")
        
        return result["data"][0]
    
    async def _find_optimal_insertion_position(self, client_data: Dict, current_stops: List[Dict], 
                                             stop_type_constraint: str = None) -> Dict:
        """
        Utilise OSRM pour trouver la position optimale d'insertion d'un nouveau stop
        
        Args:
            client_data: Données du client avec coordonnées GPS
            current_stops: Séquence actuelle des stops
            stop_type_constraint: Contrainte de type (ex: 'pickup_only', 'delivery_only')
            
        Returns:
            Dict: Position optimale avec métriques de coût
        """
        logger.debug("Finding optimal insertion position with OSRM",
                    client_id=client_data.get("id"),
                    current_stops_count=len(current_stops))
        
        if len(current_stops) < 2:
            # Pas assez de stops pour optimisation, placement simple
            return {
                "insertion_index": len(current_stops),
                "insertion_after_stop_id": current_stops[-1]["id"] if current_stops else None,
                "insertion_before_stop_id": None,
                "distance_added_meters": 0,
                "time_added_seconds": 0,
                "total_distance_impact": 0
            }
        
        # Enrichir les stops actuels avec coordonnées si nécessaire
        enriched_stops = await self._enrich_stops_with_coordinates(current_stops)
        
        # Créer le nouveau stop client
        new_stop = {
            "id": f"temp_client_{client_data['id']}",
            "latitude": client_data["locations"]["latitude"],
            "longitude": client_data["locations"]["longitude"],
            "stop_type": "client_pickup",  # Sera ajusté selon le contexte
            "location_id": client_data["location_id"]
        }
        
        best_position = None
        min_total_cost = float('inf')
        
        # Tester chaque position d'insertion possible
        valid_positions = self._get_valid_insertion_positions(enriched_stops, stop_type_constraint)
        
        for insert_index in valid_positions:
            # Créer la séquence avec le nouveau stop inséré
            test_sequence = enriched_stops[:insert_index] + [new_stop] + enriched_stops[insert_index:]
            
            try:
                # Calculer la matrice OSRM pour cette séquence
                matrix_result = await self.osrm_service.generate_distance_matrix_for_route(test_sequence)
                
                # Calculer le coût total de cette configuration
                total_cost = self._calculate_sequence_cost(matrix_result, test_sequence)
                
                if total_cost < min_total_cost:
                    min_total_cost = total_cost
                    
                    # Calculer l'impact de l'insertion
                    impact_metrics = self._calculate_insertion_impact(
                        matrix_result, enriched_stops, insert_index, new_stop
                    )
                    
                    best_position = {
                        "insertion_index": insert_index,
                        "insertion_after_stop_id": enriched_stops[insert_index - 1]["id"] if insert_index > 0 else None,
                        "insertion_before_stop_id": enriched_stops[insert_index]["id"] if insert_index < len(enriched_stops) else None,
                        "distance_added_meters": impact_metrics["distance_added"],
                        "time_added_seconds": impact_metrics["time_added"],
                        "total_distance_impact": impact_metrics["total_impact"]
                    }
                    
            except Exception as e:
                logger.warning("OSRM calculation failed for position", 
                             insert_index=insert_index, error=str(e))
                continue
        
        if best_position is None:
            # Fallback: placement en fin de séquence
            logger.warning("OSRM optimization failed, using fallback position")
            best_position = {
                "insertion_index": len(enriched_stops),
                "insertion_after_stop_id": enriched_stops[-1]["id"] if enriched_stops else None,
                "insertion_before_stop_id": None,
                "distance_added_meters": 0,
                "time_added_seconds": 0,
                "total_distance_impact": 0
            }
        
        logger.info("Optimal insertion position found",
                   insertion_index=best_position["insertion_index"],
                   distance_added=best_position["distance_added_meters"],
                   time_added=best_position["time_added_seconds"])
        
        return best_position
    
    async def _enrich_stops_with_coordinates(self, stops: List[Dict]) -> List[Dict]:
        """Enrichit les stops avec les coordonnées GPS depuis la table locations"""
        enriched_stops = []
        
        for stop in stops:
            if stop.get("latitude") and stop.get("longitude"):
                # Coordonnées déjà présentes
                enriched_stops.append(stop)
            else:
                # Récupérer les coordonnées depuis location_id
                location_result = self.supabase.select(
                    "locations",
                    "latitude, longitude, formatted_address",
                    id=stop["location_id"]
                )
                
                if location_result["status"] == "success" and location_result["data"]:
                    location = location_result["data"][0]
                    enriched_stop = {
                        **stop,
                        "latitude": location["latitude"],
                        "longitude": location["longitude"],
                        "formatted_address": location.get("formatted_address", "")
                    }
                    enriched_stops.append(enriched_stop)
                else:
                    logger.warning("Location not found for stop", stop_id=stop["id"], location_id=stop["location_id"])
                    enriched_stops.append(stop)  # Garder le stop même sans coordonnées
        
        return enriched_stops
    
    def _get_valid_insertion_positions(self, stops: List[Dict], constraint: str = None) -> List[int]:
        """Détermine les positions valides pour l'insertion selon les contraintes métier"""
        if not stops:
            return [0]
        
        if constraint == "pickup_only":
            # Pickups doivent être avant les dropoffs
            # Trouver le dernier pickup ou insérer avant le premier dropoff
            last_pickup_index = -1
            first_dropoff_index = len(stops)
            
            for i, stop in enumerate(stops):
                if stop["stop_type"] in ["depot_pickup", "client_pickup"]:
                    last_pickup_index = i
                elif stop["stop_type"] in ["depot_dropoff", "lab_dropoff", "client_delivery"]:
                    if first_dropoff_index == len(stops):
                        first_dropoff_index = i
            
            # Positions valides: après le dernier pickup et avant le premier dropoff
            max_position = min(first_dropoff_index, len(stops))
            return list(range(last_pickup_index + 1, max_position + 1))
        
        elif constraint == "delivery_only":
            # Deliveries peuvent être placées n'importe où, mais en respectant l'ordre logique
            return list(range(len(stops) + 1))
        
        else:
            # Pas de contrainte spécifique
            return list(range(len(stops) + 1))
    
    def _calculate_sequence_cost(self, matrix_result: Dict, stops_sequence: List[Dict]) -> float:
        """Calcule le coût total (distance) d'une séquence de stops"""
        if len(stops_sequence) < 2:
            return 0.0
        
        distance_matrix = matrix_result["distance_matrix"]
        total_distance = 0
        
        # Calculer la distance totale en suivant la séquence
        for i in range(len(stops_sequence) - 1):
            from_index = i
            to_index = i + 1
            total_distance += distance_matrix[from_index][to_index]
        
        return total_distance
    
    def _calculate_insertion_impact(self, matrix_result: Dict, original_stops: List[Dict], 
                                  insert_index: int, new_stop: Dict) -> Dict:
        """Calcule l'impact de l'insertion d'un stop sur la tournée"""
        distance_matrix = matrix_result["distance_matrix"]
        duration_matrix = matrix_result["duration_matrix"]
        
        # Impact distance
        if insert_index == 0:
            # Insertion au début
            if len(original_stops) > 0:
                distance_added = distance_matrix[0][1]  # Nouveau stop vers premier stop original
                time_added = duration_matrix[0][1]
            else:
                distance_added = 0
                time_added = 0
        elif insert_index >= len(original_stops):
            # Insertion à la fin
            if len(original_stops) > 0:
                prev_index = len(original_stops) - 1
                new_index = len(original_stops)
                distance_added = distance_matrix[prev_index][new_index]
                time_added = duration_matrix[prev_index][new_index]
            else:
                distance_added = 0
                time_added = 0
        else:
            # Insertion au milieu
            prev_index = insert_index - 1
            new_index = insert_index
            next_index = insert_index + 1
            
            # Distance: (prev → new) + (new → next) - (prev → next)
            old_segment = distance_matrix[prev_index][next_index] if prev_index >= 0 else 0
            new_segments = distance_matrix[prev_index][new_index] + distance_matrix[new_index][next_index]
            distance_added = new_segments - old_segment
            
            # Temps: même logique
            old_time = duration_matrix[prev_index][next_index] if prev_index >= 0 else 0
            new_time = duration_matrix[prev_index][new_index] + duration_matrix[new_index][next_index]
            time_added = new_time - old_time
        
        return {
            "distance_added": max(0, distance_added),  # Ne peut pas être négatif
            "time_added": max(0, time_added),
            "total_impact": distance_added
        }
    
    async def _plan_late_delivery_with_osrm(self, client_data: Dict, current_stops: List[Dict]) -> Dict:
        """
        🚛 LIVRAISON DE DERNIÈRE MINUTE avec optimisation OSRM
        
        Règle métier: depot_pickup (existant) → nouveau client_delivery optimalement placé
        Le shipment sera: pickup_stop_id=depot_pickup existant, delivery_stop_id=nouveau client_delivery
        """
        logger.debug("Planning late delivery with OSRM optimization", client_id=client_data.get("id"))
        
        # 1. Trouver le depot_pickup existant dans la tournée (obligatoire pour late delivery)
        depot_pickup_stop = next((s for s in current_stops if s["stop_type"] == "depot_pickup"), None)
        
        if not depot_pickup_stop:
            raise ValueError("Aucun depot_pickup trouvé dans la tournée pour la livraison de dernière minute")
        
        # 2. Utiliser OSRM pour trouver la position optimale du client_delivery
        optimal_position = await self._find_optimal_insertion_position(
            client_data, 
            current_stops, 
            stop_type_constraint="delivery_only"
        )
        
        # 3. Créer le stop client_delivery avec position optimale
        delivery_stop = {
            "stop_type": "client_delivery",
            "location_id": client_data["location_id"],
            "client_actions": "delivery",
            "insertion_index": optimal_position["insertion_index"],
            "insertion_after_stop_id": optimal_position["insertion_after_stop_id"],
            "insertion_before_stop_id": optimal_position["insertion_before_stop_id"]
        }
        
        return {
            "stops_to_insert": [delivery_stop],
            "existing_stops_used": {
                "pickup_stop": depot_pickup_stop,  # Stop existant pour le shipment
                "delivery_stop": None  # Sera le nouveau stop créé
            },
            "shipment_type": "depot_to_client_late_delivery",
            "placement_metrics": {
                "delivery_stop": {
                    "distance_added_meters": optimal_position["distance_added_meters"],
                    "time_added_seconds": optimal_position["time_added_seconds"],
                    "time_added_minutes": round(optimal_position["time_added_seconds"] / 60, 1),
                    "insertion_after": optimal_position["insertion_after_stop_id"],
                    "insertion_before": optimal_position["insertion_before_stop_id"]
                }
            }
        }
    
    async def _plan_late_pickup_with_osrm(self, client_data: Dict, lab_tour_data: Dict, current_stops: List[Dict]) -> Dict:
        """
        📦 RÉCUPÉRATION DE DERNIÈRE MINUTE avec optimisation OSRM
        
        Règle métier: nouveau client_pickup optimalement placé → lab_dropoff/depot_dropoff (existant ou créé)
        """
        logger.debug("Planning late pickup with OSRM optimization", client_id=client_data.get("id"))
        
        # 1. Utiliser OSRM pour trouver la position optimale du client_pickup
        optimal_position = await self._find_optimal_insertion_position(
            client_data, 
            current_stops, 
            stop_type_constraint="pickup_only"
        )
        
        # 2. Créer le stop client_pickup avec position optimale
        pickup_stop = {
            "stop_type": "client_pickup",
            "location_id": client_data["location_id"],
            "client_actions": "pickup",
            "insertion_index": optimal_position["insertion_index"],
            "insertion_after_stop_id": optimal_position["insertion_after_stop_id"],
            "insertion_before_stop_id": optimal_position["insertion_before_stop_id"]
        }
        
        # 3. Déterminer la destination selon les règles métier
        stops_to_create = [pickup_stop]
        existing_delivery_stop = None
        dropoff_metrics = {}
        
        if client_data.get("depot_is_lab", False):
            # Cas "Mika = Lab": les échantillons vont au dépôt
            existing_depot_dropoff = next((s for s in current_stops if s["stop_type"] == "depot_dropoff"), None)
            
            if existing_depot_dropoff:
                # Réutiliser le depot_dropoff existant
                existing_delivery_stop = existing_depot_dropoff
                logger.debug("Reusing existing depot_dropoff", stop_id=existing_depot_dropoff["id"])
            else:
                # Créer un nouveau depot_dropoff en fin de tournée
                depot_dropoff = {
                    "stop_type": "depot_dropoff",
                    "location_id": await self._get_depot_location_id(),
                    "client_actions": None,
                    "insertion_index": len(current_stops),  # En fin
                    "insertion_after_stop_id": current_stops[-1]["id"] if current_stops else None,
                    "insertion_before_stop_id": None
                }
                stops_to_create.append(depot_dropoff)
                dropoff_metrics = {
                    "distance_added_meters": 0,  # Approx car en fin de tournée
                    "time_added_seconds": 0,
                    "time_added_minutes": 0
                }
                logger.debug("Creating new depot_dropoff")
        else:
            # Cas normal: les échantillons vont au laboratoire
            lab_id = lab_tour_data["laboratory_id"]
            
            # Chercher un lab_dropoff existant pour ce laboratoire
            existing_lab_dropoff = next((s for s in current_stops 
                                       if s["stop_type"] == "lab_dropoff" 
                                       and s.get("laboratory_id") == lab_id), None)
            
            if existing_lab_dropoff:
                # Réutiliser le lab_dropoff existant
                existing_delivery_stop = existing_lab_dropoff
                logger.debug("Reusing existing lab_dropoff", stop_id=existing_lab_dropoff["id"], lab_id=lab_id)
            else:
                # Créer un nouveau lab_dropoff avant le depot_dropoff s'il existe
                depot_dropoff_index = next((i for i, s in enumerate(current_stops) 
                                          if s["stop_type"] == "depot_dropoff"), len(current_stops))
                
                lab_dropoff = {
                    "stop_type": "lab_dropoff",
                    "location_id": await self._get_laboratory_location_id(lab_id),
                    "laboratory_id": lab_id,
                    "client_actions": None,
                    "insertion_index": depot_dropoff_index,
                    "insertion_after_stop_id": current_stops[depot_dropoff_index - 1]["id"] if depot_dropoff_index > 0 else None,
                    "insertion_before_stop_id": current_stops[depot_dropoff_index]["id"] if depot_dropoff_index < len(current_stops) else None
                }
                stops_to_create.append(lab_dropoff)
                dropoff_metrics = {
                    "distance_added_meters": 0,  # Estimation
                    "time_added_seconds": 0,
                    "time_added_minutes": 0
                }
                logger.debug("Creating new lab_dropoff", lab_id=lab_id)
        
        return {
            "stops_to_insert": stops_to_create,
            "existing_stops_used": {
                "pickup_stop": None,  # Sera le nouveau stop créé
                "delivery_stop": existing_delivery_stop  # Stop existant réutilisé ou None si nouveau
            },
            "shipment_type": "client_to_lab_late_pickup",
            "placement_metrics": {
                "pickup_stop": {
                    "distance_added_meters": optimal_position["distance_added_meters"],
                    "time_added_seconds": optimal_position["time_added_seconds"],
                    "time_added_minutes": round(optimal_position["time_added_seconds"] / 60, 1),
                    "insertion_after": optimal_position["insertion_after_stop_id"],
                    "insertion_before": optimal_position["insertion_before_stop_id"]
                },
                "dropoff_stop": dropoff_metrics
            }
        }
    
    def _calculate_total_impact_metrics(self, placement_plan: Dict) -> Dict:
        """
        Calcule les métriques totales d'impact du late stop pour le front-end
        
        Returns:
            Dict: Métriques formatées pour l'affichage front-end
        """
        placement_metrics = placement_plan.get("placement_metrics", {})
        
        total_distance_added = 0
        total_time_added_seconds = 0
        stop_placements = []
        
        # Agrégation des métriques de tous les stops ajoutés
        for stop_key, metrics in placement_metrics.items():
            if isinstance(metrics, dict):
                total_distance_added += metrics.get("distance_added_meters", 0)
                total_time_added_seconds += metrics.get("time_added_seconds", 0)
                
                # Information de placement pour le front
                if metrics.get("insertion_after") or metrics.get("insertion_before"):
                    stop_placements.append({
                        "stop_type": stop_key.replace("_stop", ""),
                        "inserted_after_stop_id": metrics.get("insertion_after"),
                        "inserted_before_stop_id": metrics.get("insertion_before"),
                        "distance_added_meters": metrics.get("distance_added_meters", 0),
                        "time_added_minutes": metrics.get("time_added_minutes", 0)
                    })
        
        return {
            "total_distance_added_meters": round(total_distance_added),
            "total_time_added_minutes": round(total_time_added_seconds / 60, 1),
            "total_time_added_seconds": total_time_added_seconds,
            "stop_placements": stop_placements,
            "summary": {
                "distance_impact": f"+{round(total_distance_added)}m",
                "time_impact": f"+{round(total_time_added_seconds / 60, 1)}min",
                "stops_added": len(stop_placements)
            }
        }
    
    async def _plan_pickup_stop(self, client_data: Dict, current_stops: List[Dict]) -> Dict:
        """Planifie un stop de pickup chez le client"""
        # Logique simplifiée: insérer le pickup vers le milieu de la tournée
        # TODO: Améliorer avec calcul GPS
        
        insertion_index = len(current_stops) // 2
        
        return {
            "stop_type": "client_pickup",
            "location_id": client_data["location_id"],
            "client_actions": "pickup",
            "insertion_index": insertion_index,
            "insertion_after_stop_id": current_stops[insertion_index - 1]["id"] if insertion_index > 0 else None,
            "insertion_before_stop_id": current_stops[insertion_index]["id"] if insertion_index < len(current_stops) else None
        }
    
    async def _plan_delivery_stop(self, client_data: Dict, lab_tour_data: Dict, current_stops: List[Dict]) -> Dict:
        """Planifie un stop de delivery (lab_dropoff ou depot_dropoff)"""
        
        # Vérifier les flags pour déterminer le type de delivery
        if client_data.get("depot_is_lab", False):
            # Delivery au dépôt
            stop_type = "depot_dropoff"
            # Chercher s'il existe déjà un depot_dropoff
            existing_depot_dropoff = next((s for s in current_stops if s["stop_type"] == "depot_dropoff"), None)
            
            if existing_depot_dropoff:
                # Pas besoin de créer un nouveau stop, utiliser l'existant
                return None
            else:
                # Créer un nouveau depot_dropoff en fin de tournée
                insertion_index = len(current_stops)
        else:
            # Delivery au laboratoire
            stop_type = "lab_dropoff"
            # Chercher s'il existe déjà un lab_dropoff pour ce labo
            lab_id = lab_tour_data["laboratory_id"]
            existing_lab_dropoff = next((s for s in current_stops 
                                       if s["stop_type"] == "lab_dropoff" 
                                       and s.get("laboratory_id") == lab_id), None)
            
            if existing_lab_dropoff:
                return None
            else:
                # Créer un nouveau lab_dropoff en fin de tournée (avant depot_dropoff s'il existe)
                depot_dropoff_index = next((i for i, s in enumerate(current_stops) 
                                          if s["stop_type"] == "depot_dropoff"), len(current_stops))
                insertion_index = depot_dropoff_index
        
        # Déterminer la location_id selon le type de stop
        if stop_type == "client_delivery":
            location_id = client_data["location_id"]
        elif stop_type == "lab_dropoff":
            # TODO: Récupérer la location_id du laboratoire
            location_id = await self._get_laboratory_location_id(lab_tour_data["laboratory_id"])
        elif stop_type == "depot_dropoff":
            # TODO: Récupérer la location_id du dépôt
            location_id = await self._get_depot_location_id()
        else:
            location_id = None
            
        return {
            "stop_type": stop_type,
            "location_id": location_id,
            "laboratory_id": lab_tour_data["laboratory_id"] if stop_type == "lab_dropoff" else None,
            "client_actions": "delivery" if stop_type.startswith("client") else None,
            "insertion_index": insertion_index,
            "insertion_after_stop_id": current_stops[insertion_index - 1]["id"] if insertion_index > 0 else None,
            "insertion_before_stop_id": current_stops[insertion_index]["id"] if insertion_index < len(current_stops) else None
        }
    
    async def _create_late_stops_and_shipments(self, driver_route_id: str, placement_plan: Dict,
                                             late_stop_data: Dict, lab_tour_data: Dict) -> Dict:
        """Crée les nouveaux stops et shipments selon les règles métier"""
        logger.debug("Creating late stops and shipments", driver_route_id=driver_route_id)
        
        inserted_stops = []
        created_shipments = []
        
        # Créer tous les nouveaux stops d'abord
        for stop_plan in placement_plan["stops_to_insert"]:
            if stop_plan is None:
                continue
                
            # Créer le stop
            stop_data = {
                "route_id": driver_route_id,
                "location_id": stop_plan["location_id"],
                "stop_order": stop_plan["insertion_index"] + 1,  # Temporaire, sera réajusté
                "stop_type": stop_plan["stop_type"],
                "client_actions": stop_plan.get("client_actions"),
                "is_late_stop": True,
                "completed": False,
                "created_at": datetime.now().isoformat()
            }
            
            stop_id = await self.data_retriever.create_route_stop(stop_data)
            stop_data["id"] = stop_id
            inserted_stops.append(stop_data)
            
            logger.debug("Created new stop", 
                        stop_id=stop_id, 
                        stop_type=stop_plan["stop_type"],
                        is_late_stop=True)
        
        # Créer le shipment selon les règles métier
        if placement_plan.get("existing_stops_used"):
            shipment_data = await self._create_late_shipment_with_existing_stops(
                driver_route_id, placement_plan, inserted_stops, late_stop_data, lab_tour_data
            )
            created_shipments.append(shipment_data)
        else:
            logger.warning("No existing stops configuration found in placement plan")
        
        # Recalculer la séquence complète avec les nouveaux stops
        updated_sequence = await self._get_current_stops_sequence(driver_route_id)
        
        result = {
            "inserted_stops": inserted_stops,
            "created_shipments": created_shipments,
            "new_sequence": updated_sequence
        }
        
        logger.debug("Late stops and shipments created",
                    stops_created=len(inserted_stops),
                    shipments_created=len(created_shipments))
        
        return result
    
    async def _create_late_shipment_with_existing_stops(self, driver_route_id: str, placement_plan: Dict, 
                                                       inserted_stops: List[Dict], late_stop_data: Dict, 
                                                       lab_tour_data: Dict) -> Dict:
        """Crée un shipment en reliant correctement aux stops existants et nouveaux"""
        
        existing_stops = placement_plan["existing_stops_used"]
        shipment_type = placement_plan.get("shipment_type", "late_shipment")
        
        # Déterminer pickup_stop_id et delivery_stop_id selon les règles métier
        pickup_stop_id = None
        delivery_stop_id = None
        
        # Récupérer les stops existants si référencés
        if existing_stops.get("pickup_stop"):
            pickup_stop_id = existing_stops["pickup_stop"]["id"]
            logger.debug("Using existing pickup stop", stop_id=pickup_stop_id)
        
        if existing_stops.get("delivery_stop"):
            delivery_stop_id = existing_stops["delivery_stop"]["id"]
            logger.debug("Using existing delivery stop", stop_id=delivery_stop_id)
        
        # Récupérer les stops nouvellement créés
        for stop in inserted_stops:
            if stop["stop_type"] == "client_pickup" and pickup_stop_id is None:
                pickup_stop_id = stop["id"]
                logger.debug("Using new pickup stop", stop_id=pickup_stop_id)
            elif stop["stop_type"] in ["client_delivery", "lab_dropoff", "depot_dropoff"] and delivery_stop_id is None:
                delivery_stop_id = stop["id"]
                logger.debug("Using new delivery stop", stop_id=delivery_stop_id, stop_type=stop["stop_type"])
        
        if not pickup_stop_id or not delivery_stop_id:
            raise ValueError(f"Impossible de déterminer pickup/delivery stops: pickup={pickup_stop_id}, delivery={delivery_stop_id}")
        
        # Créer le shipment
        shipment_data = {
            "route_id": driver_route_id,
            "shipment_ref": f"Late-{late_stop_data['id'][:8]}",
            "laboratory_id": lab_tour_data["laboratory_id"],
            "laboratory_client_id": late_stop_data["client_id"],
            "pickup_stop_id": pickup_stop_id,
            "delivery_stop_id": delivery_stop_id,
            "shipment_type": shipment_type,
            "is_late_shipment": True,
            "pickup_status": "pending",
            "delivery_status": "pending",
            "created_at": datetime.now().isoformat()
        }
        
        shipment_id = await self.data_retriever.create_route_shipment(shipment_data)
        shipment_data["id"] = shipment_id
        
        logger.debug("Late shipment created with business rules", 
                    shipment_id=shipment_id,
                    pickup_stop_id=pickup_stop_id,
                    delivery_stop_id=delivery_stop_id,
                    shipment_type=shipment_type)
        
        return shipment_data
    
    async def _create_pickup_delivery_shipment(self, driver_route_id: str, pickup_stop_id: str, 
                                              delivery_stop_id: str, late_stop_data: Dict, lab_tour_data: Dict) -> Dict:
        """Crée un shipment pickup/delivery pour un late stop"""
        
        shipment_data = {
            "route_id": driver_route_id,
            "shipment_ref": f"Late-{late_stop_data['id'][:8]}",
            "laboratory_id": lab_tour_data["laboratory_id"],
            "laboratory_client_id": late_stop_data["client_id"],
            "pickup_stop_id": pickup_stop_id,
            "delivery_stop_id": delivery_stop_id,
            "shipment_type": "client_pickup",  # Type général pour late stop pickup
            "is_late_shipment": True,
            "pickup_status": "pending",
            "delivery_status": "pending",
            "created_at": datetime.now().isoformat()
        }
        
        shipment_id = await self.data_retriever.create_route_shipment(shipment_data)
        shipment_data["id"] = shipment_id
        
        logger.debug("Late stop shipment created", 
                    shipment_id=shipment_id,
                    pickup_stop_id=pickup_stop_id,
                    delivery_stop_id=delivery_stop_id)
        
        return shipment_data
    
    async def _get_laboratory_location_id(self, laboratory_id: str) -> str:
        """Récupère la location_id d'un laboratoire"""
        result = self.supabase.select(
            "laboratories",
            "location_id",
            id=laboratory_id
        )
        
        if result["status"] != "success" or not result["data"]:
            raise DataRetrievalError(f"Laboratoire non trouvé: {laboratory_id}")
        
        return result["data"][0]["location_id"]
    
    async def _get_depot_location_id(self) -> str:
        """Récupère la location_id du dépôt actif via le service centralisé"""
        try:
            # Utiliser le nouveau service centralisé
            return get_depot_location_id()
        except Exception as e:
            logger.error("Failed to get depot location via centralized service", error=str(e))
            # Fallback vers l'ancienne méthode si nécessaire
            result = self.supabase.select(
                "depot",
                "location_id",
                is_active=True
            )
            
            if result["status"] != "success" or not result["data"]:
                raise DataRetrievalError("Aucun dépôt actif trouvé")
            
            return result["data"][0]["location_id"]
    
    async def _plan_late_delivery(self, client_data: Dict, current_stops: List[Dict]) -> Dict:
        """
        🚛 LIVRAISON DE DERNIÈRE MINUTE
        Règle métier: depot_pickup (existant) → nouveau client_delivery
        """
        logger.debug("Planning late delivery", client_id=client_data.get("id"))
        
        # 1. Trouver le depot_pickup existant dans la tournée
        depot_pickup_stop = next((s for s in current_stops if s["stop_type"] == "depot_pickup"), None)
        
        if not depot_pickup_stop:
            raise ValueError("Aucun depot_pickup trouvé dans la tournée pour la livraison de dernière minute")
        
        # 2. Planifier le nouveau stop client_delivery
        insertion_index = len(current_stops) // 2  # Milieu de tournée pour livraison
        
        delivery_stop = {
            "stop_type": "client_delivery",
            "location_id": client_data["location_id"],
            "client_actions": "delivery",
            "insertion_index": insertion_index,
            "insertion_after_stop_id": current_stops[insertion_index - 1]["id"] if insertion_index > 0 else None,
            "insertion_before_stop_id": current_stops[insertion_index]["id"] if insertion_index < len(current_stops) else None
        }
        
        return {
            "stops_to_insert": [delivery_stop],
            "existing_stops_used": {
                "pickup_stop": depot_pickup_stop,  # On réutilise ce stop pour le shipment
                "delivery_stop": None  # Sera le nouveau stop créé
            },
            "shipment_type": "depot_to_client_late_delivery"
        }
    
    async def _plan_late_pickup(self, client_data: Dict, lab_tour_data: Dict, current_stops: List[Dict]) -> Dict:
        """
        📦 RÉCUPÉRATION DE DERNIÈRE MINUTE
        Règle métier: nouveau client_pickup → lab_dropoff (existant ou créé)
        """
        logger.debug("Planning late pickup", client_id=client_data.get("id"))
        
        # 1. Planifier le nouveau stop client_pickup
        insertion_index = len(current_stops) // 2  # Milieu de tournée pour pickup
        
        pickup_stop = {
            "stop_type": "client_pickup",
            "location_id": client_data["location_id"],
            "client_actions": "pickup",
            "insertion_index": insertion_index,
            "insertion_after_stop_id": current_stops[insertion_index - 1]["id"] if insertion_index > 0 else None,
            "insertion_before_stop_id": current_stops[insertion_index]["id"] if insertion_index < len(current_stops) else None
        }
        
        # 2. Déterminer la destination selon les règles métier
        stops_to_create = [pickup_stop]
        existing_delivery_stop = None
        
        if client_data.get("depot_is_lab", False):
            # Cas "Mika = Lab": les échantillons vont au dépôt
            existing_depot_dropoff = next((s for s in current_stops if s["stop_type"] == "depot_dropoff"), None)
            
            if existing_depot_dropoff:
                # Réutiliser le depot_dropoff existant
                existing_delivery_stop = existing_depot_dropoff
                logger.debug("Reusing existing depot_dropoff", stop_id=existing_depot_dropoff["id"])
            else:
                # Créer un nouveau depot_dropoff en fin de tournée
                depot_dropoff = {
                    "stop_type": "depot_dropoff",
                    "location_id": await self._get_depot_location_id(),
                    "client_actions": None,
                    "insertion_index": len(current_stops),  # En fin
                    "insertion_after_stop_id": current_stops[-1]["id"] if current_stops else None,
                    "insertion_before_stop_id": None
                }
                stops_to_create.append(depot_dropoff)
                logger.debug("Creating new depot_dropoff")
        else:
            # Cas normal: les échantillons vont au laboratoire
            lab_id = lab_tour_data["laboratory_id"]
            
            # Chercher un lab_dropoff existant pour ce laboratoire
            existing_lab_dropoff = next((s for s in current_stops 
                                       if s["stop_type"] == "lab_dropoff" 
                                       and s.get("laboratory_id") == lab_id), None)
            
            if existing_lab_dropoff:
                # Réutiliser le lab_dropoff existant
                existing_delivery_stop = existing_lab_dropoff
                logger.debug("Reusing existing lab_dropoff", stop_id=existing_lab_dropoff["id"], lab_id=lab_id)
            else:
                # Créer un nouveau lab_dropoff avant le depot_dropoff s'il existe
                depot_dropoff_index = next((i for i, s in enumerate(current_stops) 
                                          if s["stop_type"] == "depot_dropoff"), len(current_stops))
                
                lab_dropoff = {
                    "stop_type": "lab_dropoff",
                    "location_id": await self._get_laboratory_location_id(lab_id),
                    "laboratory_id": lab_id,
                    "client_actions": None,
                    "insertion_index": depot_dropoff_index,
                    "insertion_after_stop_id": current_stops[depot_dropoff_index - 1]["id"] if depot_dropoff_index > 0 else None,
                    "insertion_before_stop_id": current_stops[depot_dropoff_index]["id"] if depot_dropoff_index < len(current_stops) else None
                }
                stops_to_create.append(lab_dropoff)
                logger.debug("Creating new lab_dropoff", lab_id=lab_id)
        
        return {
            "stops_to_insert": stops_to_create,
            "existing_stops_used": {
                "pickup_stop": None,  # Sera le nouveau stop créé
                "delivery_stop": existing_delivery_stop  # Stop existant réutilisé ou None si nouveau
            },
            "shipment_type": "client_to_lab_late_pickup"
        }
    
    def _determine_shipment_type_from_stop(self, stop_plan: Dict) -> str:
        """Détermine le type de shipment basé sur le type de stop"""
        stop_type = stop_plan["stop_type"]
        
        if stop_type == "client_pickup":
            return "client_pickup"
        elif stop_type == "client_delivery":
            return "client_delivery"
        elif stop_type == "lab_dropoff":
            return "client_to_lab"
        elif stop_type == "depot_dropoff":
            return "client_to_depot"
        else:
            return "unknown"
    
    async def _update_stops_sequence(self, driver_route_id: str, new_sequence: List[Dict]) -> Dict:
        """Met à jour les stop_order de toute la séquence"""
        logger.debug("Updating stops sequence", driver_route_id=driver_route_id)
        
        stops_updated = 0
        
        for new_order, stop in enumerate(new_sequence, 1):
            if stop["stop_order"] != new_order:
                # Mettre à jour le stop_order
                update_result = self.supabase.update(
                    "driver_route_stops",
                    {"stop_order": new_order, "updated_at": datetime.now().isoformat()},
                    id=stop["id"]
                )
                
                if update_result["status"] == "success":
                    stops_updated += 1
        
        logger.debug("Stops sequence updated", stops_updated=stops_updated)
        
        return {"stops_updated": stops_updated}
    
    async def _update_late_stop_status(self, late_stop_request_id: str, status: str, 
                                     rejection_reason: Optional[str] = None):
        """Met à jour le statut de la demande de late stop"""
        logger.debug("Updating late stop status", 
                    request_id=late_stop_request_id, 
                    status=status)
        
        update_data = {
            "status": status,
            "reviewed_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        if rejection_reason:
            update_data["rejection_reason"] = rejection_reason
        
        result = self.supabase.update(
            "lab_tour_late_stops",
            update_data,
            id=late_stop_request_id
        )
        
        if result["status"] != "success":
            logger.error("Failed to update late stop status", 
                        request_id=late_stop_request_id,
                        error=result.get("message"))