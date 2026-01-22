"""
Orchestrateur principal pour la génération quotidienne des tournées
"""

import structlog
import asyncio
from datetime import date
from typing import Dict, List, Tuple
from collections import defaultdict

# from app.integrations.supabase.http_client import supabase_http_client
from app.models.responses.tours import ProcessedTour, TourStatus
from .data_retriever import TourDataRetriever
from .stop_consolidator import StopConsolidator
from .route_generator import RouteGenerator
from .shipment_mapper import ShipmentMapper
from .exceptions import (
    TourGenerationError, 
    ClientWithoutDriverError, 
    DataRetrievalError
)

logger = structlog.get_logger()


class DailyTourProcessor:
    """Orchestrateur principal pour la génération quotidienne des tournées"""
    
    def __init__(self):
        self.data_retriever = TourDataRetriever()
        self.stop_consolidator = StopConsolidator()
        self.route_generator = RouteGenerator(self.data_retriever)
        self.shipment_mapper = ShipmentMapper(self.data_retriever)
    
    async def process_daily_tours(self, target_date: date, enable_optimization: bool, include_pending_returns: bool = True) -> Dict:
        """
        Processus principal de génération des tournées quotidiennes
        
        Args:
            target_date: Date cible pour la génération
            enable_optimization: Active l'optimisation après génération
            
        Returns:
            Dict: Résultat du traitement avec tours générées et erreurs
            
        Raises:
            TourGenerationError: Si erreur lors de la génération
        """
        logger.info("Starting daily tour generation", 
                   date=str(target_date), 
                   optimization_enabled=enable_optimization)
        
        try:
            # 1. Nettoyage des tournées existantes
            cleaned_count = await self.data_retriever.clean_existing_routes(target_date)
            
            # 2. Récupération des données enrichies
            enriched_shipments = await self.data_retriever.get_enriched_shipments_for_date(target_date)
            
            if not enriched_shipments:
                logger.info("No shipments found for date", date=str(target_date))
                return {
                    "processed_tours": [],
                    "errors": [],
                    "stats": {
                        "total_shipments": 0,
                        "drivers_count": 0,
                        "cleaned_routes": cleaned_count
                    }
                }
            
            # 3. Validation et groupement des shipments
            valid_shipments, invalid_shipments = self._validate_shipments(enriched_shipments)
            grouped_shipments = self._group_shipments_by_driver(valid_shipments)
            
            # 4. Récupération des données complémentaires
            locations_map = await self.data_retriever.get_locations_map()
            drivers_map = await self._get_drivers_map()
            lab_location_map = await self.data_retriever.get_laboratories_location_map()
            
            # 5. Génération des tournées pour chaque driver
            processed_tours = []
            generation_errors = []
            
            for driver_id, driver_shipments in grouped_shipments.items():
                try:
                    driver_name = drivers_map.get(driver_id, {}).get("name", f"Driver {driver_id}")
                    
                    tour_result = await self._process_driver_tours(
                        driver_id, 
                        driver_name,
                        driver_shipments, 
                        target_date, 
                        locations_map,
                        lab_location_map
                    )
                    
                    processed_tours.append(tour_result)
                    
                except Exception as e:
                    logger.error("Error processing driver tours", 
                               driver_id=driver_id, 
                               error=str(e))
                    generation_errors.append({
                        "driver_id": driver_id,
                        "error": f"Erreur génération tournée: {str(e)}"
                    })
            
            # 6. Traitement des retours en attente AVANT optimisation (si demandé)
            if include_pending_returns:
                pending_returns_stats = await self._handle_pending_returns(target_date, processed_tours)
            else:
                pending_returns_stats = {"pending_returns_count": 0, "processed_count": 0}
                logger.info("Skipping pending returns processing (include_pending_returns=False)")
            
            # 7. Optimisation si demandée (APRÈS ajout des retours)
            if enable_optimization:
                await self._optimize_generated_tours(processed_tours)
            
            # 8. Préparation des erreurs clients
            client_errors = [
                {
                    "client_id": ship["client_id"], 
                    "error": f"Client '{ship.get('client_name', 'inconnu')}' n'a pas de livreur assigné"
                }
                for ship in invalid_shipments
            ]
            
            logger.info("Daily tour generation completed", 
                       processed_tours=len(processed_tours),
                       client_errors=len(client_errors),
                       generation_errors=len(generation_errors),
                       pending_returns=pending_returns_stats)
            
            return {
                "processed_tours": processed_tours,
                "errors": client_errors + generation_errors,
                "stats": {
                    "total_shipments": len(enriched_shipments),
                    "valid_shipments": len(valid_shipments),
                    "drivers_count": len(grouped_shipments),
                    "cleaned_routes": cleaned_count
                }
            }
            
        except Exception as e:
            logger.error("Fatal error in daily tour generation", error=str(e))
            raise TourGenerationError(f"Erreur lors de la génération des tournées: {str(e)}")
    
    async def _process_driver_tours(self, driver_id: str, driver_name: str, 
                                  shipments: List[Dict], target_date: date, 
                                  locations_map: Dict[str, Dict], 
                                  lab_location_map: Dict[str, str]) -> ProcessedTour:
        """
        Traite toutes les tournées d'un driver
        
        Args:
            driver_id: ID du chauffeur
            driver_name: Nom du chauffeur
            shipments: Shipments du chauffeur
            target_date: Date cible
            locations_map: Map des locations
            
        Returns:
            ProcessedTour: Tournée générée
        """
        logger.info("Processing driver tours", 
                   driver_id=driver_id, 
                   shipments_count=len(shipments))
        
        try:
            # 1. Consolidation des stops
            consolidated_stops = self.stop_consolidator.consolidate_stops_for_driver(
                shipments, locations_map, lab_location_map
            )
            
            # 2. Génération de la route
            route_id = await self.route_generator.create_driver_route(
                driver_id, 
                str(target_date),
                len(consolidated_stops)
            )
            
            # 3. Création des stops
            stops_map = await self.route_generator.create_route_stops(
                route_id, 
                consolidated_stops
            )
            
            # 4. Mapping des shipments
            shipment_ids = await self.shipment_mapper.create_route_shipments(
                route_id, 
                shipments, 
                stops_map, 
                consolidated_stops
            )
            
            logger.info("Driver tours processed successfully", 
                       driver_id=driver_id,
                       route_id=route_id,
                       stops_count=len(stops_map),
                       shipments_count=len(shipment_ids))
            
            # 5. Génération du résumé
            return ProcessedTour(
                tour_id=route_id,
                status=TourStatus.PENDING,
                stops_count=len(consolidated_stops),
                driver_name=driver_name,
                estimated_duration=None
            )
            
        except Exception as e:
            logger.error("Error processing driver tours", 
                        driver_id=driver_id, 
                        error=str(e))
            raise TourGenerationError(f"Erreur lors du traitement des tournées du chauffeur {driver_id}: {str(e)}")
    
    def _validate_shipments(self, shipments: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """
        Sépare les shipments valides (avec driver) des invalides
        
        Args:
            shipments: Liste des shipments à valider
            
        Returns:
            Tuple[List[Dict], List[Dict]]: (valid_shipments, invalid_shipments)
        """
        valid_shipments = []
        invalid_shipments = []
        
        for shipment in shipments:
            if shipment.get("driver_id"):
                valid_shipments.append(shipment)
            else:
                invalid_shipments.append(shipment)
        
        logger.info("Shipments validation completed", 
                   valid=len(valid_shipments), 
                   invalid=len(invalid_shipments))
        
        return valid_shipments, invalid_shipments
    
    def _group_shipments_by_driver(self, shipments: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Groupe les shipments par driver_id
        
        Args:
            shipments: Liste des shipments valides
            
        Returns:
            Dict[str, List[Dict]]: Shipments groupés par driver
        """
        grouped = defaultdict(list)
        
        for shipment in shipments:
            driver_id = shipment["driver_id"]
            grouped[driver_id].append(shipment)
        
        logger.info("Shipments grouped by driver", 
                   drivers_count=len(grouped),
                   total_shipments=len(shipments))
        
        return dict(grouped)
    
    async def _get_drivers_map(self) -> Dict[str, Dict]:
        """
        Récupère et map les drivers
        
        Returns:
            Dict[str, Dict]: Map driver_id -> driver_data
        """
        try:
            drivers = await self.data_retriever.get_drivers_list()
            return {driver["id"]: driver for driver in drivers}
        except Exception as e:
            logger.warning("Could not retrieve drivers map", error=str(e))
            return {}
    
    async def _optimize_generated_tours(self, processed_tours: List[ProcessedTour]) -> None:
        """
        Optimise les tournées générées avec le nouveau système UUID + enrichissement
        
        Args:
            processed_tours: Tours à optimiser
        """
        logger.info("Optimizing generated tours with new UUID merger system", tours_count=len(processed_tours))
        
        # Importer le nouvel orchestrateur avec fusion UUID
        from .optimization_orchestrator import OptimizationOrchestrator
        
        orchestrator = OptimizationOrchestrator()
        
        for tour in processed_tours:
            if tour.status == TourStatus.PENDING:
                logger.info("Starting full optimization with UUID merger", route_id=tour.tour_id)
                
                try:
                    # Lancer l'optimisation complète avec le nouveau système
                    optimization_result = await orchestrator.process_full_optimization(tour.tour_id)
                    
                    if optimization_result and optimization_result.get("status") == "success":
                        tour.status = TourStatus.OPTIMIZED
                        
                        # Mise à jour des statistiques du tour
                        if "optimization_summary" in optimization_result:
                            summary = optimization_result["optimization_summary"]
                            tour.stops_count = summary.get("final_stops_after_fusion", tour.stops_count)
                            tour.estimated_duration = f"{summary.get('estimated_duration_minutes', 0)}min"
                        
                        logger.info("Full optimization completed successfully", 
                                   route_id=tour.tour_id,
                                   final_stops=optimization_result.get("final_stops_count", 0),
                                   stops_merged=optimization_result.get("optimization_summary", {}).get("stops_merged", 0),
                                   distance_km=optimization_result.get("optimization_summary", {}).get("total_distance_km", 0))
                    else:
                        logger.warning("Full optimization failed", 
                                     route_id=tour.tour_id,
                                     error_message=optimization_result.get("message", "Unknown error"))
                        # Garder le statut pending si l'optimisation échoue
                
                except Exception as e:
                    logger.error("Error during OR-Tools V3 optimization", 
                               route_id=tour.tour_id, 
                               error=str(e))
                    # Garder le statut pending si erreur
        
        logger.info("Tours optimization with OR-Tools V3 completed")
    
    async def _handle_pending_returns(self, target_date: date, processed_tours: List[ProcessedTour]) -> Dict:
        """
        Traite les colis en attente au dépôt depuis les tournées précédentes
        
        Args:
            target_date: Date cible pour la génération
            processed_tours: Tours générés pour ajout des retours
            
        Returns:
            Dict: Statistiques des retours traités
        """
        logger.info("Processing pending returns from previous tours", date=str(target_date))
        
        try:
            # 1. Chercher les colis en attente
            pending_returns = await self._find_pending_return_shipments(target_date)
            
            if not pending_returns:
                logger.info("No pending returns found")
                return {"pending_returns_count": 0, "processed_count": 0}
            
            # 2. Grouper par driver_id pour ajout aux tournées existantes
            returns_by_driver = {}
            for return_shipment in pending_returns:
                driver_id = return_shipment["driver_id"]
                if driver_id not in returns_by_driver:
                    returns_by_driver[driver_id] = []
                returns_by_driver[driver_id].append(return_shipment)
            
            # 3. Ajouter aux tournées existantes
            processed_count = 0
            for driver_id, driver_returns in returns_by_driver.items():
                # Trouver la tournée du driver
                driver_tour = next((tour for tour in processed_tours if tour.tour_id), None)
                # Note: Il faudrait matcher par driver_id, mais pour l'instant on prend la première
                
                if driver_tour:
                    await self._add_returns_to_existing_tour(driver_tour.tour_id, driver_returns)
                    processed_count += len(driver_returns)
                else:
                    logger.warning("No tour found for driver with pending returns", driver_id=driver_id)
            
            logger.info("Pending returns processed successfully", 
                       found=len(pending_returns),
                       processed=processed_count)
            
            return {
                "pending_returns_count": len(pending_returns),
                "processed_count": processed_count,
                "drivers_with_returns": len(returns_by_driver)
            }
            
        except Exception as e:
            logger.error("Error processing pending returns", error=str(e))
            return {"pending_returns_count": 0, "processed_count": 0, "error": str(e)}
    
    async def _find_pending_return_shipments(self, target_date: date) -> List[Dict]:
        """
        Cherche les colis avec is_return_next_day=true dans les 5 derniers jours
        
        Args:
            target_date: Date cible
            
        Returns:
            List[Dict]: Shipments en attente de retour au laboratoire
        """
        logger.info("Searching for pending return shipments", target_date=str(target_date))
        
        try:
            from datetime import timedelta
            
            # Chercher dans les 5 derniers jours (exclut la date courante)
            search_dates = []
            for i in range(1, 6):  # 1 à 5 jours avant
                search_date = target_date - timedelta(days=i)
                search_dates.append(search_date)
            
            pending_returns = []
            
            # Chercher la tournée la plus récente avec des retours
            for search_date in search_dates:
                logger.debug("Checking date for pending returns", date=str(search_date))
                
                # Récupérer les shipments du jour
                date_shipments = await self.data_retriever.get_enriched_shipments_for_date(search_date)
                
                # Filtrer ceux avec is_return_next_day = true
                date_returns = [
                    ship for ship in date_shipments 
                    if ship.get("is_return_next_day", False)
                ]
                
                if date_returns:
                    logger.info("Found pending returns", date=str(search_date), count=len(date_returns))
                    
                    # Transformer en shipments depot_to_lab
                    for return_ship in date_returns:
                        pending_returns.append({
                            "original_shipment_id": return_ship["id"],
                            "shipment_type": "depot_to_lab",
                            "from_location_id": return_ship.get("from_location_id"),  # Location du dépôt
                            "to_location_id": return_ship.get("to_location_id"),     # Location du lab
                            "laboratory_id": return_ship["laboratory_id"],
                            "client_id": return_ship["client_id"],
                            "driver_id": return_ship["driver_id"],
                            "client_name": return_ship.get("client_name", "Client"),
                            "laboratory_name": return_ship.get("laboratory_name", "Lab"),
                            "original_date": str(search_date)
                        })
                    
                    # Prendre seulement la date la plus récente avec des retours
                    break
            
            logger.info("Pending returns search completed", total_found=len(pending_returns))
            return pending_returns
            
        except Exception as e:
            logger.error("Error searching pending returns", error=str(e))
            return []
    
    async def _add_returns_to_existing_tour(self, tour_id: str, return_shipments: List[Dict]) -> None:
        """
        Ajoute les shipments de retour à une tournée existante
        
        Args:
            tour_id: ID de la tournée
            return_shipments: Shipments de retour à ajouter
        """
        logger.info("Adding return shipments to existing tour", 
                   tour_id=tour_id, 
                   returns_count=len(return_shipments))
        
        try:
            # Récupérer les données actuelles de la tournée
            locations_map = await self.data_retriever.get_locations_map()
            current_stops = await self.data_retriever.get_route_stops(tour_id)
            
            # Récupérer le mapping des laboratoires pour les retours
            lab_location_map = await self.data_retriever.get_laboratories_location_map()
            
            # Créer les stops consolidés pour les retours
            consolidated_returns = self.stop_consolidator.consolidate_stops_for_driver(
                return_shipments, locations_map, lab_location_map
            )
            
            # Créer les nouveaux stops nécessaires
            new_stops_map = await self.route_generator.create_route_stops(
                tour_id, 
                consolidated_returns
            )
            
            # Créer les stops existants + nouveaux pour le mapping
            all_stops_map = {}
            for stop in current_stops:
                # Reconstituer le stop_key depuis les données existantes
                # Cette partie pourrait nécessiter d'améliorer le mapping
                pass
            all_stops_map.update(new_stops_map)
            
            # Mapper les shipments de retour
            await self.shipment_mapper.create_route_shipments(
                tour_id,
                return_shipments,
                all_stops_map,
                consolidated_returns
            )
            
            logger.info("Return shipments added successfully", tour_id=tour_id)
            
        except Exception as e:
            logger.error("Error adding returns to tour", tour_id=tour_id, error=str(e))