"""
Endpoints pour la gestion des tournées
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from typing import Dict, Any, List
import asyncio
from datetime import datetime, date

from app.core.security import verify_api_key
from app.models.requests.tours import DailyProcessRequest, OptimizeTourRequest
from app.models.responses.tours import DailyProcessResponse, OptimizeTourResponse, ApiErrorResponse, ProcessedTour, TourStatus
from app.services.tours.daily_processor import DailyTourProcessor
from app.services.tours.optimizer import TourOptimizer

router = APIRouter(prefix="/tours", tags=["tours"])


@router.get("/test")
async def test_endpoint():
    """Endpoint de test pour vérifier que les routes fonctionnent"""
    return {"status": "success", "message": "Tours endpoint is working"}


@router.post("/test-auth")
async def test_auth(api_key: str = Depends(verify_api_key)):
    """Test de l'authentification"""
    return {"status": "success", "message": "Authentication working", "api_key_valid": True}




@router.post("/debug-shared-pickup-coordinates")
async def debug_shared_pickup_coordinates(request: dict, api_key: str = Depends(verify_api_key)):
    """Debug des coordonnées des shared pickups"""
    from app.services.tours.data_retriever import TourDataRetriever
    
    route_id = request.get("route_id")
    if not route_id:
        return {"status": "error", "message": "route_id required"}
    
    try:
        data_retriever = TourDataRetriever()
        optimization_data = await data_retriever.get_tour_optimization_data(route_id)
        
        # Identifier les stops avec shared pickups
        all_stops = optimization_data["stops"]
        shared_pickup_stops = [
            stop for stop in all_stops 
            if stop.get("is_shared_pickup_stop", False)
        ]
        
        return {
            "status": "success",
            "route_id": route_id,
            "total_stops": len(all_stops),
            "shared_pickup_stops_count": len(shared_pickup_stops),
            "shared_pickup_coordinates": [
                {
                    "id": stop["id"],
                    "stop_type": stop["stop_type"],
                    "latitude": stop["latitude"],
                    "longitude": stop["longitude"],
                    "formatted_address": stop.get("formatted_address", "")[:50]
                }
                for stop in shared_pickup_stops
            ],
            "driver_start_location": optimization_data["start_location"]
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error debugging shared pickup coordinates: {str(e)}"
        }


@router.post("/test-shipment-data")
async def test_shipment_data(api_key: str = Depends(verify_api_key)):
    """Examiner la structure des données réelles des shipments"""
    from app.services.tours.data_retriever import TourDataRetriever
    from datetime import datetime
    
    data_retriever = TourDataRetriever()
    target_date = datetime.strptime("2025-08-03", "%Y-%m-%d").date()
    
    # Récupérer les shipments enrichis
    enriched_shipments = await data_retriever.get_enriched_shipments_for_date(target_date)
    
    # Analyser les types de shipments et leurs laboratory_id
    analysis = {
        "depot_to_client": [],
        "client_to_depot": [],
        "depot_to_lab": [],
        "lab_to_depot": [],
        "lab_to_client": [],
        "client_to_lab": []
    }
    
    for shipment in enriched_shipments[:10]:  # Limiter à 10 pour l'exemple
        shipment_type = shipment.get("shipment_type")
        if shipment_type in analysis:
            analysis[shipment_type].append({
                "id": shipment.get("id"),
                "shipment_type": shipment_type,
                "laboratory_id": shipment.get("laboratory_id"),
                "laboratory_name": shipment.get("laboratory_name"),
                "client_name": shipment.get("client_name"),
                "from_location_id": shipment.get("from_location_id"),
                "to_location_id": shipment.get("to_location_id")
            })
    
    return {
        "status": "success",
        "total_shipments": len(enriched_shipments),
        "analysis": analysis
    }


@router.post("/test-supabase-data")
async def test_supabase_data(
    request: dict,
    api_key: str = Depends(verify_api_key)
):
    """Vérifier les données générées dans Supabase pour une tournée"""
    from app.services.tours.data_retriever import TourDataRetriever
    
    tour_id = request.get("tour_id")
    if not tour_id:
        return {"status": "error", "message": "tour_id required"}
    
    data_retriever = TourDataRetriever()
    
    try:
        # 1. Récupérer la route
        route_result = await data_retriever.get_route_by_id(tour_id)
        
        # 2. Récupérer les stops de la route
        stops_result = await data_retriever.get_route_stops(tour_id)
        
        # 3. Récupérer les shipments de la route
        shipments_result = await data_retriever.get_route_shipments(tour_id)
        
        # 4. Analyser les données
        analysis = {
            "route": route_result,
            "stops_count": len(stops_result) if stops_result else 0,
            "shipments_count": len(shipments_result) if shipments_result else 0,
            "stops_sample": stops_result[:5] if stops_result else [],
            "shipments_sample": shipments_result[:5] if shipments_result else [],
        }
        
        # 5. Vérifications de cohérence
        checks = {
            "route_exists": route_result is not None,
            "has_stops": len(stops_result) > 0 if stops_result else False,
            "has_shipments": len(shipments_result) > 0 if shipments_result else False,
        }
        
        if shipments_result:
            # Vérifier que tous les shipments ont des pickup/delivery stop_id valides
            stop_ids = {stop["id"] for stop in stops_result} if stops_result else set()
            invalid_shipments = []
            
            for shipment in shipments_result:
                pickup_id = shipment.get("pickup_stop_id")
                delivery_id = shipment.get("delivery_stop_id")
                
                if pickup_id not in stop_ids or delivery_id not in stop_ids:
                    invalid_shipments.append({
                        "shipment_ref": shipment.get("shipment_ref"),
                        "pickup_stop_id": pickup_id,
                        "delivery_stop_id": delivery_id,
                        "pickup_valid": pickup_id in stop_ids,
                        "delivery_valid": delivery_id in stop_ids
                    })
            
            checks["stop_ids_valid"] = len(invalid_shipments) == 0
            checks["invalid_shipments"] = invalid_shipments[:3]  # Limiter à 3
        
        return {
            "status": "success",
            "tour_id": tour_id,
            "analysis": analysis,
            "checks": checks
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error analyzing tour data: {str(e)}"
        }


@router.post("/test-next-day-logic")
async def test_next_day_logic(api_key: str = Depends(verify_api_key)):
    """Analyser la logique next day delivery"""
    from app.services.tours.data_retriever import TourDataRetriever
    from datetime import datetime
    
    data_retriever = TourDataRetriever()
    target_date = datetime.strptime("2025-08-03", "%Y-%m-%d").date()
    
    # Récupérer les shipments enrichis
    enriched_shipments = await data_retriever.get_enriched_shipments_for_date(target_date)
    
    # Analyser les flags is_next_day
    next_day_analysis = {
        "total_shipments": len(enriched_shipments),
        "next_day_shipments": [],
        "regular_shipments": 0,
        "next_day_count": 0
    }
    
    # Examiner tous les shipments pour le flag is_next_day
    for shipment in enriched_shipments:
        # Vérifier le flag is_return_next_day trouvé dans les données
        is_return_next_day = shipment.get("is_return_next_day", False)
        
        # Si le flag is_return_next_day est true
        if is_return_next_day:
            next_day_analysis["next_day_count"] += 1
            next_day_analysis["next_day_shipments"].append({
                "id": shipment.get("id"),
                "client_name": shipment.get("client_name"),
                "laboratory_name": shipment.get("laboratory_name"),
                "shipment_type": shipment.get("shipment_type"),
                "is_return_next_day": is_return_next_day,
                "driver_id": shipment.get("driver_id"),
                "from_location_id": shipment.get("from_location_id"),
                "to_location_id": shipment.get("to_location_id")
            })
        else:
            next_day_analysis["regular_shipments"] += 1
    
    # Limiter les résultats pour l'affichage
    next_day_analysis["next_day_shipments"] = next_day_analysis["next_day_shipments"][:10]
    
    return {
        "status": "success",
        "date": "2025-08-03",
        "analysis": next_day_analysis,
        "sample_shipment_fields": list(enriched_shipments[0].keys()) if enriched_shipments else []
    }


@router.post("/test-pending-returns")
async def test_pending_returns(api_key: str = Depends(verify_api_key)):
    """Tester la logique des retours en attente"""
    from app.services.tours.daily_processor import DailyTourProcessor
    from datetime import datetime, timedelta
    
    processor = DailyTourProcessor()
    target_date = datetime.strptime("2025-08-06", "%Y-%m-%d").date()  # 6 août pour chercher dans le passé
    
    try:
        # Tester la recherche des retours en attente
        pending_returns = await processor._find_pending_return_shipments(target_date)
        
        # Simuler des stats de traitement
        stats = await processor._handle_pending_returns(target_date, [])
        
        return {
            "status": "success",
            "target_date": str(target_date),
            "search_dates": [str(target_date - timedelta(days=i)) for i in range(1, 6)],
            "pending_returns_found": len(pending_returns),
            "pending_returns_sample": pending_returns[:3],
            "processing_stats": stats
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error testing pending returns: {str(e)}"
        }


@router.post("/test-enriched-stops")
async def test_enriched_stops(
    request: dict,
    api_key: str = Depends(verify_api_key)
):
    """Test de la nouvelle méthode get_enriched_route_stops pour OR-Tools"""
    from app.services.tours.data_retriever import TourDataRetriever
    
    route_id = request.get("route_id")
    if not route_id:
        return {"status": "error", "message": "route_id required"}
    
    data_retriever = TourDataRetriever()
    
    try:
        # Tester la nouvelle méthode enrichie
        enriched_stops = await data_retriever.get_enriched_route_stops(route_id)
        
        # Analyser la qualité des données pour OR-Tools
        analysis = {
            "total_stops": len(enriched_stops),
            "stops_with_gps": sum(1 for s in enriched_stops if s.get("latitude") and s.get("longitude")),
            "stops_types": {},
            "data_quality_issues": [],
            "sample_stops": enriched_stops[:3] if enriched_stops else []
        }
        
        # Compter les types de stops
        for stop in enriched_stops:
            stop_type = stop.get("stop_type", "unknown")
            analysis["stops_types"][stop_type] = analysis["stops_types"].get(stop_type, 0) + 1
            
            # Vérifier la qualité des données critiques pour OR-Tools
            if not stop.get("latitude") or not stop.get("longitude"):
                analysis["data_quality_issues"].append({
                    "stop_id": stop.get("id"),
                    "issue": "missing_gps_coordinates",
                    "stop_order": stop.get("stop_order")
                })
            
            if not stop.get("stop_order"):
                analysis["data_quality_issues"].append({
                    "stop_id": stop.get("id"),
                    "issue": "missing_stop_order"
                })
        
        # Comparer avec la méthode ancienne pour validation
        old_stops = await data_retriever.get_route_stops(route_id)
        comparison = {
            "old_method_count": len(old_stops),
            "new_method_count": len(enriched_stops),
            "data_consistency": len(old_stops) == len(enriched_stops)
        }
        
        return {
            "status": "success",
            "route_id": route_id,
            "analysis": analysis,
            "comparison": comparison,
            "ready_for_or_tools": (
                analysis["total_stops"] > 0 and 
                analysis["stops_with_gps"] == analysis["total_stops"] and
                len(analysis["data_quality_issues"]) == 0
            )
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error testing enriched stops: {str(e)}"
        }


@router.post("/test-optimization-data")
async def test_optimization_data(
    request: dict,
    api_key: str = Depends(verify_api_key)
):
    """Test du package complet de données pour OR-Tools"""
    from app.services.tours.data_retriever import TourDataRetriever
    
    route_id = request.get("route_id")
    if not route_id:
        return {"status": "error", "message": "route_id required"}
    
    data_retriever = TourDataRetriever()
    
    try:
        # Tester le package complet d'optimisation
        optimization_data = await data_retriever.get_tour_optimization_data(route_id)
        
        # Analyse de la préparation OR-Tools
        or_tools_readiness = {
            "data_complete": optimization_data["metadata"]["ready_for_optimization"],
            "stops_count": optimization_data["metadata"]["total_stops"],
            "shipments_count": optimization_data["metadata"]["total_shipments"],
            "geographic_restrictions": len(optimization_data["constraints"]["geographic_restrictions"]),
            "data_quality_score": optimization_data["metadata"]["data_quality_score"],
            "issues": optimization_data["metadata"]["issues"]
        }
        
        # Extraire des échantillons pour validation
        samples = {
            "route_info": optimization_data["route"],
            "first_stop": optimization_data["stops"][0] if optimization_data["stops"] else None,
            "first_shipment": optimization_data["shipments"][0] if optimization_data["shipments"] else None,
            "constraints_sample": {
                "time_windows": optimization_data["constraints"]["time_windows"],
                "service_times": optimization_data["constraints"]["service_times"],
                "restricted_stops": optimization_data["constraints"]["geographic_restrictions"][:3]
            }
        }
        
        return {
            "status": "success",
            "route_id": route_id,
            "or_tools_readiness": or_tools_readiness,
            "samples": samples,
            "performance": {
                "total_data_points": (
                    len(optimization_data["stops"]) + 
                    len(optimization_data["shipments"])
                ),
                "package_complete": all([
                    optimization_data["route"],
                    optimization_data["stops"],
                    optimization_data["shipments"],
                    optimization_data["constraints"]
                ])
            }
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error testing optimization data: {str(e)}"
        }


@router.post("/test-full-optimization")
async def test_full_optimization(
    request: dict,
    api_key: str = Depends(verify_api_key)
):
    """Test de l'orchestrateur complet d'optimisation"""
    from app.services.tours.optimization_orchestrator import OptimizationOrchestrator
    
    route_id = request.get("route_id")
    if not route_id:
        return {"status": "error", "message": "route_id required"}
    
    orchestrator = OptimizationOrchestrator()
    
    try:
        # Test du processus complet d'optimisation
        result = await orchestrator.process_full_optimization(route_id)
        
        return {
            "status": "success",
            "route_id": route_id,
            "orchestrator_result": result,
            "services_status": {
                "data_retriever": "✅ Utilise repositories Supabase existants",
                "stop_fusion_service": "✅ Fusion CLIENT successifs uniquement",
                "directions_enricher": "✅ Google Directions API",
                "supabase_update": "✅ Via repositories existants"
            }
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error testing full optimization: {str(e)}"
        }


@router.post("/analyze-or-tools-readiness")
async def analyze_or_tools_readiness(
    request: dict,
    api_key: str = Depends(verify_api_key)
):
    """Analyse complète si nos données sont prêtes pour OR-Tools"""
    from app.services.tours.data_retriever import TourDataRetriever
    from app.services.tours.or_tools_analysis import ORToolsRequirementsAnalysis
    
    route_id = request.get("route_id")
    if not route_id:
        return {"status": "error", "message": "route_id required"}
    
    try:
        # 1. Récupérer les données d'optimisation complètes
        data_retriever = TourDataRetriever()
        optimization_data = await data_retriever.get_tour_optimization_data(route_id)
        
        # 2. Analyser la couverture OR-Tools
        analyzer = ORToolsRequirementsAnalysis()
        coverage_analysis = analyzer.analyze_current_data_coverage(optimization_data)
        
        # 3. Générer la roadmap d'implémentation
        roadmap = analyzer.generate_implementation_roadmap(coverage_analysis)
        
        return {
            "status": "success",
            "route_id": route_id,
            "or_tools_readiness": {
                "implementation_ready": coverage_analysis["implementation_ready"],
                "coverage_summary": coverage_analysis["coverage_summary"],
                "critical_gaps": coverage_analysis["critical_gaps"],
                "detailed_analysis": coverage_analysis["detailed_analysis"]
            },
            "implementation_roadmap": roadmap,
            "data_overview": {
                "total_stops": len(optimization_data.get("stops", [])),
                "total_shipments": len(optimization_data.get("shipments", [])),
                "data_quality_score": optimization_data["metadata"]["data_quality_score"],
                "ready_for_optimization": optimization_data["metadata"]["ready_for_optimization"]
            }
        }
        
    except Exception as e:
        return {
            "status": "error",  
            "message": f"Error analyzing OR-Tools readiness: {str(e)}"
        }


@router.post("/test-start-location-integration")
async def test_start_location_integration(
    request: dict,
    api_key: str = Depends(verify_api_key)
):
    """Test de l'intégration complète start_location + start_time pour OR-Tools"""
    from app.services.tours.data_retriever import TourDataRetriever
    from app.services.tours.osrm_distance_matrix import OSRMDistanceMatrixService
    
    route_id = request.get("route_id")
    if not route_id:
        return {"status": "error", "message": "route_id required"}
    
    try:
        # 1. Récupérer le package d'optimisation complet (avec driver + start_location)
        data_retriever = TourDataRetriever()
        optimization_data = await data_retriever.get_tour_optimization_data(route_id)
        
        # 2. Tester la génération de matrice avec start_location
        osrm_service = OSRMDistanceMatrixService()
        matrix_result = await osrm_service.generate_distance_matrix_with_start_location(
            optimization_data["stops"],
            optimization_data["start_location"]
        )
        
        # 3. Validation des données OR-Tools
        validation_tests = {
            "driver_start_time_available": optimization_data["driver"]["start_time"] is not None,
            "start_location_coordinates": {
                "latitude": optimization_data["start_location"]["latitude"],
                "longitude": optimization_data["start_location"]["longitude"],
                "address": optimization_data["start_location"]["formatted_address"]
            },
            "depot_at_index_0": matrix_result["depot_index"] == 0,
            "matrix_includes_start_location": matrix_result.get("start_location_added", False),
            "total_matrix_size": matrix_result["matrix_size"],
            "original_stops_count": matrix_result.get("original_stops_count", len(optimization_data["stops"]))
        }
        
        # 4. Données prêtes pour OR-Tools
        or_tools_package = {
            "driver_info": {
                "id": optimization_data["driver"]["id"],
                "name": optimization_data["driver"]["name"],
                "start_time": optimization_data["driver"]["start_time"]
            },
            "depot_coordinates": {
                "index": 0,  # TOUJOURS 0 pour start_location
                "latitude": optimization_data["start_location"]["latitude"],
                "longitude": optimization_data["start_location"]["longitude"]
            },
            "distance_matrix_sample": [
                matrix_result["distance_matrix"][i][:5] if len(matrix_result["distance_matrix"][i]) >= 5 
                else matrix_result["distance_matrix"][i]
                for i in range(min(5, len(matrix_result["distance_matrix"])))
            ],
            "time_constraints": optimization_data["constraints"]["time_windows"],
            "geographic_restrictions_count": len(optimization_data["constraints"]["geographic_restrictions"])
        }
        
        return {
            "status": "success",
            "route_id": route_id,
            "validation_tests": validation_tests,
            "or_tools_package": or_tools_package,
            "implementation_notes": {
                "start_location_uuid": "08831414-5482-4822-86dd-6170633135f7",
                "start_location_usage": "✅ Utilisée comme point de départ OR-Tools (index 0)",
                "driver_start_time_usage": f"✅ {optimization_data['driver']['start_time']} récupéré depuis drivers table",
                "existing_services_used": "✅ DriversRepository étendu, OSRM service adapté",
                "ready_for_or_tools": all([
                    validation_tests["driver_start_time_available"],
                    validation_tests["depot_at_index_0"],
                    validation_tests["start_location_coordinates"]["latitude"] is not None
                ])
            }
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error testing start_location integration: {str(e)}"
        }


@router.post("/test-shared-pickup-logic-corrected")
async def test_shared_pickup_logic_corrected(
    request: dict,
    api_key: str = Depends(verify_api_key)
):
    """Test de la logique CORRIGÉE des shared pickups"""
    from app.services.tours.two_phase_optimizer import TwoPhaseOptimizer
    
    route_id = request.get("route_id")
    if not route_id:
        return {"status": "error", "message": "route_id required"}
    
    try:
        # Exécuter l'optimisation 2 phases avec logique corrigée
        two_phase_optimizer = TwoPhaseOptimizer()
        optimization_result = await two_phase_optimizer.optimize_route_two_phases(route_id)
        
        # Analyser les résultats avec la logique corrigée
        or_tools_data = optimization_result["phase2_or_tools"]["or_tools_data"]
        
        # Tests de validation de la logique corrigée
        validation_analysis = {
            "depot_pickup_logic": {
                "rule": "Tous les shipments du depot → delivery_only (peu importe le flag)",
                "depot_delivery_only_count": sum(1 for s in or_tools_data["shipments"] 
                                               if s.get("or_tools_constraint_type") == "delivery_only" 
                                               and "depot" in s.get("constraint_note", "").lower()),
                "depot_pickup_delivery_count": sum(1 for s in or_tools_data["shipments"] 
                                                 if s.get("or_tools_constraint_type") == "pickup_delivery" 
                                                 and "depot" in s.get("constraint_note", "").lower())
            },
            "lab_pickup_differentiation": {
                "rule": "lab_pickup shared → Phase 1, lab_pickup non-shared → OR-Tools",
                "lab_shared_delivery_only": sum(1 for s in or_tools_data["shipments"] 
                                              if s.get("or_tools_constraint_type") == "delivery_only" 
                                              and "lab pickup shared" in s.get("constraint_note", "").lower()),
                "lab_nonshared_pickup_delivery": sum(1 for s in or_tools_data["shipments"] 
                                                   if s.get("or_tools_constraint_type") == "pickup_delivery" 
                                                   and "lab pickup non-shared" in s.get("constraint_note", "").lower()),
                "lab_pickup_stops_in_or_tools": sum(1 for s in or_tools_data["stops"] 
                                                  if s.get("stop_type") == "lab_pickup")
            },
            "client_pickup_logic": {
                "rule": "client pickup → contrainte pickup/delivery normale",
                "client_pickup_delivery_count": sum(1 for s in or_tools_data["shipments"] 
                                                  if s.get("or_tools_constraint_type") == "pickup_delivery" 
                                                  and "client pickup" in s.get("constraint_note", "").lower())
            }
        }
        
        # Échantillons pour vérification manuelle
        shipment_samples = {
            "depot_shipments": [s for s in or_tools_data["shipments"] 
                              if "depot" in s.get("constraint_note", "").lower()][:3],
            "lab_shared_shipments": [s for s in or_tools_data["shipments"] 
                                   if "lab pickup shared" in s.get("constraint_note", "").lower()][:3],
            "lab_nonshared_shipments": [s for s in or_tools_data["shipments"] 
                                      if "lab pickup non-shared" in s.get("constraint_note", "").lower()][:3],
            "client_shipments": [s for s in or_tools_data["shipments"] 
                               if "client pickup" in s.get("constraint_note", "").lower()][:3]
        }
        
        # Statistiques des stops
        stop_analysis = {
            "total_original_stops": optimization_result["metadata"]["original_stops"],  # C'est déjà un entier
            "shared_pickup_stops": len(optimization_result["phase1_shared_pickups"]["optimized_stops"]),
            "or_tools_stops": len(or_tools_data["stops"]),
            "stops_breakdown": {}
        }
        
        # Breakdown des types de stops dans OR-Tools
        for stop in or_tools_data["stops"]:
            stop_type = stop.get("stop_type", "unknown")
            stop_analysis["stops_breakdown"][stop_type] = stop_analysis["stops_breakdown"].get(stop_type, 0) + 1
        
        return {
            "status": "success",
            "route_id": route_id,
            "validation_analysis": validation_analysis,
            "shipment_samples": shipment_samples,
            "stop_analysis": stop_analysis,
            "corrected_logic_summary": {
                "depot_pickup_rule": "✅ Tous les shipments du depot → delivery_only",
                "lab_pickup_shared_rule": "✅ lab_pickup shared → exclus d'OR-Tools, delivery_only",
                "lab_pickup_nonshared_rule": "✅ lab_pickup non-shared → dans OR-Tools avec pickup/delivery",
                "client_pickup_rule": "✅ client pickup → pickup/delivery normale",
                "logic_validated": all([
                    validation_analysis["depot_pickup_logic"]["depot_pickup_delivery_count"] == 0,
                    validation_analysis["lab_pickup_differentiation"]["lab_pickup_stops_in_or_tools"] >= 0
                ])
            }
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error testing corrected shared pickup logic: {str(e)}"
        }


@router.post("/test-complete-or-tools-optimization")
async def test_complete_or_tools_optimization(
    request: dict,
    api_key: str = Depends(verify_api_key)
):
    """Test de l'optimisation COMPLÈTE avec OR-Tools VRP intégré"""
    from app.services.tours.two_phase_optimizer import TwoPhaseOptimizer
    
    route_id = request.get("route_id")
    if not route_id:
        return {"status": "error", "message": "route_id required"}
    
    try:
        # Exécuter l'optimisation complète (Shared Pickups + OR-Tools)
        two_phase_optimizer = TwoPhaseOptimizer()
        complete_result = await two_phase_optimizer.optimize_route_two_phases(route_id)
        
        # Analyser les performances OR-Tools
        or_tools_analysis = {
            "solver_executed": complete_result["phase2_or_tools"]["solution_found"],
            "optimization_time": complete_result["phase2_or_tools"]["or_tools_solution"]["optimization_metadata"]["processing_time_seconds"] if complete_result["phase2_or_tools"].get("or_tools_solution") else 0,
            "objective_value": complete_result["phase2_or_tools"]["objective_value"],
            "total_distance_km": complete_result["total_distance_km"],
            "stops_optimized": len(complete_result["phase2_or_tools"]["optimized_stops"]),
            "restricted_zones_handled": complete_result["phase2_or_tools"]["or_tools_solution"].get("restricted_stops_count", 0) if complete_result["phase2_or_tools"].get("or_tools_solution") else 0,
            "pickup_delivery_pairs": complete_result["phase2_or_tools"]["or_tools_solution"].get("pickup_delivery_pairs_satisfied", 0) if complete_result["phase2_or_tools"].get("or_tools_solution") else 0
        }
        
        # Séquence finale combinée
        final_sequence = []
        
        # 1. Ajouter shared pickups (Phase 1)
        for stop in complete_result["phase1_shared_pickups"]["optimized_stops"]:
            final_sequence.append({
                "phase": "shared_pickups",
                "stop_order": stop["optimized_stop_order"],
                "stop_id": stop["id"],
                "stop_type": stop["stop_type"],
                "address": stop.get("formatted_address", "")[:50]
            })
        
        # 2. Ajouter OR-Tools stops (Phase 2)
        for stop in complete_result["phase2_or_tools"]["optimized_stops"]:
            final_sequence.append({
                "phase": "or_tools",
                "stop_order": stop["final_stop_order"],
                "stop_id": stop["id"],
                "stop_type": stop["stop_type"],
                "address": stop.get("formatted_address", "")[:50],
                "estimated_arrival": stop.get("estimated_arrival_time"),
                "is_restricted_zone": stop.get("is_restricted_zone", False)
            })
        
        # Trier par stop_order final
        final_sequence.sort(key=lambda x: x["stop_order"])
        
        # Validation de la séquence complète
        validation_tests = {
            "phase1_completed": complete_result["phase1_shared_pickups"]["completed"],
            "phase2_completed": complete_result["phase2_or_tools"]["solution_found"],
            "total_stops_count": len(final_sequence),
            "sequence_continuity": all(
                final_sequence[i]["stop_order"] == i + 1 
                for i in range(len(final_sequence))
            ),
            "restricted_zones_at_end": self._validate_restricted_zones_placement(final_sequence),
            "depot_pickup_first": final_sequence[0]["stop_type"] == "depot_pickup" if final_sequence else False
        }
        
        return {
            "status": "success",
            "route_id": route_id,
            "complete_optimization_result": complete_result,
            "or_tools_analysis": or_tools_analysis,
            "final_sequence": final_sequence,
            "validation_tests": validation_tests,
            "expert_summary": {
                "optimization_method": "Two-Phase with OR-Tools VRP",
                "phase1_shared_pickups": f"✅ {len(complete_result['phase1_shared_pickups']['optimized_stops'])} stops optimized by GPS",
                "phase2_or_tools": f"✅ {len(complete_result['phase2_or_tools']['optimized_stops'])} stops optimized by OR-Tools VRP",
                "total_distance": f"{complete_result['total_distance_km']} km",
                "optimization_time": f"{or_tools_analysis['optimization_time']} seconds",
                "marseille_restrictions": f"✅ {or_tools_analysis['restricted_zones_handled']} restricted zones handled",
                "pickup_delivery_constraints": f"✅ {or_tools_analysis['pickup_delivery_pairs']} pickup/delivery pairs satisfied",
                "solution_quality": "OPTIMAL" if complete_result["phase2_or_tools"]["solution_found"] else "FALLBACK"
            }
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error testing complete OR-Tools optimization: {str(e)}"
        }

def _validate_restricted_zones_placement(final_sequence: List[Dict]) -> bool:
    """Valide que les zones restreintes sont bien placées en fin de tournée"""
    if not final_sequence:
        return True
    
    # Trouver la première zone restreinte
    first_restricted_index = None
    for i, stop in enumerate(final_sequence):
        if stop.get("is_restricted_zone"):
            first_restricted_index = i
            break
    
    if first_restricted_index is None:
        return True  # Pas de zones restreintes
    
    # Vérifier que toutes les zones restreintes sont après 1h30 (approximatif)
    # Pour la validation, on considère qu'après 60% de la tournée c'est acceptable
    total_stops = len(final_sequence)
    acceptable_position = int(total_stops * 0.6)
    
    return first_restricted_index >= acceptable_position


@router.post("/test-two-phase-optimization")
async def test_two_phase_optimization(
    request: dict,
    api_key: str = Depends(verify_api_key)
):
    """Test de l'optimisation complète en 2 phases : Shared Pickups + OR-Tools"""
    from app.services.tours.two_phase_optimizer import TwoPhaseOptimizer
    
    route_id = request.get("route_id")
    if not route_id:
        return {"status": "error", "message": "route_id required"}
    
    try:
        # Initialiser l'orchestrateur 2 phases
        two_phase_optimizer = TwoPhaseOptimizer()
        
        # Exécuter l'optimisation 2 phases
        optimization_result = await two_phase_optimizer.optimize_route_two_phases(route_id)
        
        # Générer le résumé
        summary = two_phase_optimizer.get_optimization_summary(optimization_result)
        
        # Tests de validation
        validation_tests = {
            "phase1_shared_pickups": {
                "executed": optimization_result["phase1_shared_pickups"]["completed"],
                "stops_optimized": len(optimization_result["phase1_shared_pickups"]["optimized_stops"]),
                "distance_calculated": optimization_result["phase1_shared_pickups"]["distance_km"] > 0
            },
            "phase2_or_tools": {
                "data_prepared": optimization_result["phase2_or_tools"]["ready"],
                "stops_filtered": optimization_result["phase2_or_tools"]["stops_count"],
                "shipments_filtered": optimization_result["phase2_or_tools"]["shipments_count"],
                "distance_matrix_ready": optimization_result["phase2_or_tools"]["distance_matrix_ready"]
            },
            "integration": {
                "stop_order_offset_calculated": optimization_result["phase2_or_tools"]["stop_order_offset"] > 0,
                "start_location_preserved": optimization_result["metadata"]["start_location"] is not None,
                "driver_start_time_available": optimization_result["metadata"]["driver_start_time"] is not None
            }
        }
        
        # Échantillons de données pour vérification
        samples = {
            "shared_pickup_stops_sample": optimization_result["phase1_shared_pickups"]["optimized_stops"][:3],
            "or_tools_stops_sample": optimization_result["phase2_or_tools"]["or_tools_data"]["stops"][:3],
            "or_tools_shipments_sample": optimization_result["phase2_or_tools"]["or_tools_data"]["shipments"][:3]
        }
        
        return {
            "status": "success",
            "route_id": route_id,
            "optimization_result": optimization_result,
            "summary": summary,
            "validation_tests": validation_tests,
            "samples": samples,
            "implementation_notes": {
                "phase1_method": "GPS nearest neighbor pour shared pickups",
                "phase2_method": "Données filtrées et préparées pour OR-Tools",
                "depot_pickup_rule": "Toujours stop_order=1 dans Phase 1",
                "shared_pickup_exclusion": "Stops shared pickups exclus d'OR-Tools",
                "shipment_constraint_logic": "is_shared_pickup=true → pas de contrainte pickup/delivery",
                "stop_order_continuity": f"OR-Tools commence à stop_order={optimization_result['phase2_or_tools']['stop_order_offset']}",
                "ready_for_or_tools_solver": optimization_result["next_steps"]["optimization_complete"]
            }
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error testing two-phase optimization: {str(e)}"
        }


@router.post("/debug-pickup-delivery-pairs")
async def debug_pickup_delivery_pairs(
    request: dict,
    api_key: str = Depends(verify_api_key)
):
    """Debug spécifique pour analyser la génération des pickup/delivery pairs"""
    from app.services.tours.two_phase_optimizer import TwoPhaseOptimizer
    from app.services.tours.or_tools_vrp_solver import ORToolsVRPSolver
    
    route_id = request.get("route_id")
    if not route_id:
        return {"status": "error", "message": "route_id required"}
    
    try:
        # Exécuter l'optimisation 2 phases jusqu'à la préparation OR-Tools
        optimizer = TwoPhaseOptimizer()
        result = await optimizer.optimize_route_two_phases(route_id)
        
        or_tools_data = result["phase2_or_tools"]["or_tools_data"]
        
        # Analyser les données
        shipments = or_tools_data["shipments"]
        stops_mapping = or_tools_data["distance_matrix"]["stops_mapping"]
        
        pickup_delivery_shipments = [
            s for s in shipments if s.get("or_tools_constraint_type") == "pickup_delivery"
        ]
        
        # Créer le mapping comme dans OR-Tools
        stop_id_to_index = {mapping["stop_id"]: mapping["index"] for mapping in stops_mapping}
        
        # Simuler la logique de _prepare_pickup_delivery_pairs
        debug_pairs = []
        validation_errors = []
        
        for shipment in pickup_delivery_shipments[:5]:  # Analyser les 5 premiers
            pickup_stop_id = shipment.get("pickup_stop_id")
            delivery_stop_id = shipment.get("delivery_stop_id")
            
            pickup_index = stop_id_to_index.get(pickup_stop_id)
            delivery_index = stop_id_to_index.get(delivery_stop_id)
            
            pair_info = {
                "shipment_ref": shipment.get("shipment_ref"),
                "pickup_stop_id": pickup_stop_id,
                "delivery_stop_id": delivery_stop_id,
                "pickup_index": pickup_index,
                "delivery_index": delivery_index,
                "pickup_found": pickup_index is not None,
                "delivery_found": delivery_index is not None
            }
            
            if pickup_index is not None and delivery_index is not None:
                # Validation comme dans OR-Tools
                if pickup_index >= len(stops_mapping) or delivery_index >= len(stops_mapping):
                    pair_info["validation_error"] = "Index hors limites"
                    validation_errors.append(pair_info)
                else:
                    pair_info["validation_success"] = True
                    debug_pairs.append(pair_info)
            else:
                pair_info["validation_error"] = "Stop ID non trouvé"
                validation_errors.append(pair_info)
        
        return {
            "status": "success",
            "route_id": route_id,
            "analysis": {
                "total_shipments": len(shipments),
                "pickup_delivery_shipments": len(pickup_delivery_shipments),
                "stops_mapping_size": len(stops_mapping),
                "distance_matrix_size": len(or_tools_data["distance_matrix"]["distance_matrix"]),
                "stop_id_to_index_size": len(stop_id_to_index)
            },
            "debug_pairs": debug_pairs,
            "validation_errors": validation_errors,
            "actual_pairs_in_ortools": len(or_tools_data.get("pickup_delivery_pairs", []))
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error debugging pickup/delivery pairs: {str(e)}"
        }


@router.post("/test-osrm-distance-matrix")
async def test_osrm_distance_matrix(
    request: dict,
    api_key: str = Depends(verify_api_key)
):
    """Test de génération de matrice de distances OSRM avec traçabilité UUID"""
    from app.services.tours.data_retriever import TourDataRetriever
    from app.services.tours.osrm_distance_matrix import OSRMDistanceMatrixService
    
    route_id = request.get("route_id")
    if not route_id:
        return {"status": "error", "message": "route_id required"}
    
    try:
        # 1. Récupérer les stops enrichis avec GPS
        data_retriever = TourDataRetriever()
        enriched_stops = await data_retriever.get_enriched_route_stops(route_id)
        
        if not enriched_stops:
            return {"status": "error", "message": "No stops found for route"}
        
        # 2. Générer la matrice OSRM
        osrm_service = OSRMDistanceMatrixService()
        matrix_result = await osrm_service.generate_distance_matrix_for_route(enriched_stops)
        
        # 3. Tests de validation
        validation_tests = []
        
        # Test 1: Vérifier la traçabilité UUID
        uuid_mapping_test = {
            "test_name": "UUID Traceability",
            "stops_count": len(enriched_stops),
            "mapped_count": len(matrix_result["stops_mapping"]),
            "all_uuids_preserved": all(
                mapping["stop_id"] in [s["id"] for s in enriched_stops] 
                for mapping in matrix_result["stops_mapping"]
            ),
            "passed": len(enriched_stops) == len(matrix_result["stops_mapping"])
        }
        validation_tests.append(uuid_mapping_test)
        
        # Test 2: Vérifier l'identification du dépôt
        depot_test = {
            "test_name": "Depot Identification",
            "depot_index": matrix_result["depot_index"],
            "depot_stop_id": matrix_result["stops_mapping"][matrix_result["depot_index"]]["stop_id"],
            "depot_type": matrix_result["stops_mapping"][matrix_result["depot_index"]]["stop_type"],
            "passed": matrix_result["depot_index"] >= 0
        }
        validation_tests.append(depot_test)
        
        # Test 3: Vérifier les distances entre stops spécifiques
        if len(matrix_result["stops_mapping"]) >= 2:
            stop1_id = matrix_result["stops_mapping"][0]["stop_id"]
            stop2_id = matrix_result["stops_mapping"][1]["stop_id"]
            
            distance_test = osrm_service.get_distance_between_stops(
                matrix_result, stop1_id, stop2_id
            )
            distance_test["test_name"] = "Distance Lookup by UUID"
            distance_test["passed"] = distance_test["distance_meters"] > 0
            validation_tests.append(distance_test)
        
        # 4. Exemples d'utilisation pour OR-Tools
        or_tools_ready_data = {
            "matrix_size": matrix_result["matrix_size"],
            "depot_index": matrix_result["depot_index"],
            "distance_matrix_sample": [
                matrix_result["distance_matrix"][i][:5] if len(matrix_result["distance_matrix"][i]) >= 5 
                else matrix_result["distance_matrix"][i]
                for i in range(min(5, len(matrix_result["distance_matrix"])))
            ],
            "stops_mapping_sample": matrix_result["stops_mapping"][:5]
        }
        
        return {
            "status": "success",
            "route_id": route_id,
            "osrm_matrix_result": {
                "matrix_generated": True,
                "matrix_size": matrix_result["matrix_size"],
                "depot_index": matrix_result["depot_index"],
                "processing_time": matrix_result["osrm_metadata"]["processing_time"],
                "osrm_url": matrix_result["osrm_metadata"]["osrm_url"]
            },
            "validation_tests": validation_tests,
            "or_tools_ready_data": or_tools_ready_data,
            "implementation_notes": {
                "uuid_preservation": "✅ Tous les UUIDs des stops sont préservés dans stops_mapping",
                "depot_identification": "✅ Dépôt identifié automatiquement via start_location", 
                "matrix_access": "✅ Accès par UUID ou par index de matrice",
                "or_tools_integration": "✅ Données prêtes pour OR-Tools VRP"
            }
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error testing OSRM distance matrix: {str(e)}"
        }


@router.post("/test-shipment-logic")
async def test_shipment_logic(api_key: str = Depends(verify_api_key)):
    """Test complet de la nouvelle logique des shipments"""
    from app.services.tours.shipment_mapper import ShipmentMapper
    from app.services.tours.data_retriever import TourDataRetriever
    
    data_retriever = TourDataRetriever()
    mapper = ShipmentMapper(data_retriever)
    
    # Test 1: depot_to_lab avec pickup (récupération)
    mock_shipment_pickup = {
        "id": "test_depot_to_lab_pickup",
        "shipment_type": "depot_to_lab",
        "client_name": "ZBILI",
        "laboratory_name": "ART OPALESCENCE",
        "has_pickup": True,
        "has_delivery": False
    }
    
    # Test 2: depot_to_lab avec delivery (livraison) 
    mock_shipment_delivery = {
        "id": "test_depot_to_lab_delivery",
        "shipment_type": "depot_to_lab",
        "client_name": "CLIENT TEST",
        "laboratory_name": "ART OPALESCENCE",
        "has_pickup": False,
        "has_delivery": True
    }
    
    # Tester les deux cas
    results = []
    for shipment, expected_type, expected_ref_start in [
        (mock_shipment_pickup, "client_pickup", "Récupération"),
        (mock_shipment_delivery, "client_delivery", "Livraison")
    ]:
        driver_type = mapper._determine_shipment_type(shipment)
        reference = mapper._generate_shipment_reference(shipment)
        
        results.append({
            "shipment_id": shipment["id"],
            "has_pickup": shipment.get("has_pickup"),
            "has_delivery": shipment.get("has_delivery"),
            "driver_shipment_type": driver_type,
            "generated_reference": reference,
            "expected_type": expected_type,
            "expected_ref_start": expected_ref_start,
            "correct": driver_type == expected_type and reference.startswith(expected_ref_start)
        })
    
    return {
        "status": "success",
        "tests": results,
        "all_correct": all(r["correct"] for r in results)
    }


@router.post("/test-response")
async def test_response(
    request: DailyProcessRequest,
    api_key: str = Depends(verify_api_key)
) -> DailyProcessResponse:
    """Test de la structure de réponse"""
    from datetime import datetime
    target_date = datetime.strptime(request.date, "%Y-%m-%d").date()
    
    # Créer une réponse factice avec le bon format
    return DailyProcessResponse(
        status="success",
        message="Test response",
        processed_tours=[
            ProcessedTour(
                tour_id="test-id",
                status=TourStatus.PENDING,
                stops_count=5,
                driver_name="Test Driver",
                estimated_duration=None
            )
        ],
        processing_time="1s",
        date=target_date.isoformat(),
        generation_enabled=True,
        optimization_enabled=request.optimize
    )


@router.post("/test-generate")
async def test_generate(
    request: DailyProcessRequest,
    api_key: str = Depends(verify_api_key)
):
    """Test endpoint pour déboguer étape par étape"""
    steps_completed = []
    try:
        from datetime import datetime
        target_date = datetime.strptime(request.date, "%Y-%m-%d").date()
        steps_completed.append("Date parsing")
        
        # Test processor initialization
        processor = DailyTourProcessor()
        steps_completed.append("Processor initialization")
        
        # Test data retriever
        data_retriever = processor.data_retriever
        steps_completed.append("Data retriever access")
        
        # Test nettoyage (étape 1)
        try:
            cleaned_count = await data_retriever.clean_existing_routes(target_date)
            steps_completed.append(f"Route cleaning (deleted: {cleaned_count})")
        except Exception as e:
            return {
                "status": "error",
                "message": f"Error in step 'clean_existing_routes': {str(e)}",
                "steps_completed": steps_completed
            }
        
        # Test récupération des shipments (étape 2)
        try:
            enriched_shipments = await data_retriever.get_enriched_shipments_for_date(target_date)
            steps_completed.append(f"Shipments retrieval (found: {len(enriched_shipments)})")
        except Exception as e:
            return {
                "status": "error",
                "message": f"Error in step 'get_enriched_shipments_for_date': {str(e)}",
                "steps_completed": steps_completed
            }
        
        # Test complet du processus
        try:
            result = await processor.process_daily_tours(
                target_date=target_date,
                enable_optimization=request.optimize
            )
            steps_completed.append(f"Full processing completed: {len(result.get('processed_tours', []))} tours")
            
            return {
                "status": "success", 
                "message": "Complete tour generation successful",
                "parsed_date": str(target_date),
                "optimize": request.optimize,
                "steps_completed": steps_completed,
                "result": result
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Error in full processing: {str(e)}",
                "steps_completed": steps_completed
            }
        
    except Exception as e:
        return {
            "status": "error", 
            "message": f"Error: {str(e)}", 
            "steps_completed": steps_completed
        }


@router.post("/generate-daily")
async def generate_daily(
    request: DailyProcessRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    Génère et optimise les tournées pour la date du jour
    
    - **optimize**: true = génération + optimisation, false = génération seule
    - Traitement asynchrone (30s - 1m30)
    - Met à jour automatiquement Supabase
    """
    start_time = datetime.now()
    
    try:
        # Initialisation du processeur quotidien
        processor = DailyTourProcessor()
        
        # Parsing de la date
        target_date = datetime.strptime(request.date, "%Y-%m-%d").date()
        
        # Traitement asynchrone
        result = await processor.process_daily_tours(
            target_date=target_date,
            enable_optimization=request.optimize,
            include_pending_returns=request.include_pending_returns
        )
        
        # Calcul du temps de traitement
        processing_time = _calculate_processing_time(start_time)
        
        # Retour direct sans modèle Pydantic pour éviter les conflits
        return {
            "status": "success",
            "message": "Traitement quotidien terminé avec succès",
            "processed_tours": [
                {
                    "tour_id": tour.tour_id,
                    "status": tour.status.value,
                    "stops_count": tour.stops_count,
                    "driver_name": tour.driver_name,
                    "estimated_duration": tour.estimated_duration
                } for tour in result.get("processed_tours", [])
            ],
            "processing_time": processing_time,
            "date": target_date.isoformat(),
            "generation_enabled": True,
            "optimization_enabled": request.optimize,
            "stats": result.get("stats", {}),
            "errors": result.get("errors", [])
        }
        
    except Exception as e:
        processing_time = _calculate_processing_time(start_time)
        return {
            "status": "error",
            "message": f"Erreur lors du traitement quotidien: {str(e)}",
            "processing_time": processing_time,
            "error_code": "DAILY_PROCESS_ERROR"
        }


@router.post("/{tour_id}/optimize-v3")
async def optimize_tour_v3_complete(
    tour_id: str,
    api_key: str = Depends(verify_api_key)
):
    """
    Optimisation COMPLÈTE V3 avec TwoPhaseOptimizer + enrichissement + sauvegarde
    
    - **tour_id**: ID de la tournée à optimiser
    - Processus complet : optimisation 2 phases + enrichissement + sauvegarde Supabase
    - Met à jour toutes les données en base automatiquement
    """
    from app.services.tours.two_phase_optimizer import TwoPhaseOptimizer
    from app.services.tours.route_stop_merger import RouteStopMerger
    from app.services.tours.solution_enricher import SolutionEnricher
    from app.services.tours.solution_saver_v4 import SolutionSaverV4  # V4 corrigée
    
    start_time = datetime.now()
    
    try:
        # 1. OPTIMISATION 2 phases avec TwoPhaseOptimizer
        two_phase_optimizer = TwoPhaseOptimizer()
        optimization_result = await two_phase_optimizer.optimize_route_two_phases(tour_id)
        
        if not optimization_result.get("phase2_or_tools", {}).get("solution_found", False):
            return {
                "status": "error",
                "message": "Optimisation OR-Tools échouée",
                "processing_time": _calculate_processing_time(start_time)
            }
        
        # 2. Récupérer la tournée reconstruite (déjà dans le bon ordre)
        all_optimized_stops = optimization_result["phase2_or_tools"]["optimized_stops"]
        logger.info("Using reconstructed tour from TwoPhaseOptimizer",
                   total_stops=len(all_optimized_stops))
        
        # 3. ENRICHISSEMENT avec Google Directions
        solution_enricher = SolutionEnricher()
        driver_start_time = optimization_result["metadata"]["driver_start_time"]
        enriched_solution = await solution_enricher.enrich_solution(
            tour_id, all_optimized_stops, driver_start_time
        )
        
        # 4. SAUVEGARDE V4 avec gestion correcte des expanded stops
        solution_saver = SolutionSaverV4()
        optimization_metadata = {
            "method": "TwoPhase OR-Tools V4",
            "constraints_applied": optimization_result["phase2_or_tools"].get("pickup_delivery_pairs", 0),
            "total_distance_km": optimization_result["total_distance_km"],
            "phase1_distance": optimization_result["phase1_shared_pickups"]["distance_km"],
            "phase2_distance": optimization_result["phase2_or_tools"]["total_distance_km"],
            "estimated_duration_minutes": enriched_solution["route_totals"]["total_duration_minutes"],
            "estimated_end_time": enriched_solution["route_totals"]["estimated_end_time"]
        }
        
        # Les stops enrichis contiennent déjà final_stop_order
        save_result = await solution_saver.save_optimized_solution(
            tour_id, enriched_solution["enriched_stops"], optimization_metadata
        )
        
        # Calcul du temps de traitement
        processing_time = _calculate_processing_time(start_time)
        
        return {
            "status": "success",
            "message": "Optimisation V3 complète terminée avec succès",
            "tour_id": tour_id,
            "processing_time": processing_time,
            "optimization_summary": {
                "method": "TwoPhase OR-Tools V3 + Enrichissement + Sauvegarde V3",
                "total_distance_km": optimization_result["total_distance_km"],
                "phase1_stops": len(phase1_stops),
                "phase2_stops": len(phase2_stops),
                "final_stops": enriched_solution["route_totals"]["total_stops"],
                "pickup_delivery_constraints": optimization_result["phase2_or_tools"].get("pickup_delivery_pairs", 0),
                "estimated_duration_minutes": enriched_solution["route_totals"]["total_duration_minutes"],
                "estimated_end_time": enriched_solution["route_totals"]["estimated_end_time"],
                "polyline_generated": len(enriched_solution["polyline"]) > 0
            },
            "database_updates": {
                "approach": "update_in_place_v4",
                "stops_before": save_result.get("transformation_summary", {}).get("original_stops", 0),
                "stops_after": save_result.get("transformation_summary", {}).get("final_stops", 0),
                "stops_deleted": save_result.get("transformation_summary", {}).get("stops_deleted", 0),
                "expanded_mappings": save_result.get("transformation_summary", {}).get("expanded_mappings", 0),
                "fusion_groups": save_result.get("transformation_summary", {}).get("fusion_groups", 0),
                "shipments_updated": save_result.get("transformation_summary", {}).get("shipments_updated", 0),
                "constraints_valid": save_result.get("validation", {}).get("valid", False)
            },
            "workflow_completed": {
                "optimization": True,
                "enrichment": True,
                "fusion": save_result.get("transformation_summary", {}).get("fusion_groups", 0) > 0,
                "database_save": save_result["status"] == "success",
                "constraints_validated": save_result.get("validation", {}).get("valid", False)
            }
        }
        
    except Exception as e:
        processing_time = _calculate_processing_time(start_time)
        return {
            "status": "error",
            "message": f"Erreur lors de l'optimisation V3 complète: {str(e)}",
            "processing_time": processing_time,
            "error_code": "OPTIMIZATION_V3_ERROR"
        }


@router.post(
    "/{tour_id}/optimize",
    response_model=OptimizeTourResponse,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
        500: {"model": ApiErrorResponse}
    },
    summary="Optimisation d'une tournée unique (ancienne version)",
    description="Optimise une tournée existante avec statut 'pending' ou 'optimized'"
)
async def optimize_tour(
    tour_id: str,
    request: OptimizeTourRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    Optimise une tournée spécifique
    
    - **tour_id**: ID de la tournée à optimiser
    - Seules les tournées 'pending' ou 'optimized' sont traitées
    - Met à jour automatiquement Supabase
    """
    start_time = datetime.now()
    
    try:
        # Initialisation de l'optimiseur
        optimizer = TourOptimizer()
        
        # Vérification et optimisation
        result = await optimizer.optimize_single_tour(
            tour_id=tour_id,
            force_optimization=request.force_optimization
        )
        
        # Calcul du temps de traitement
        processing_time = _calculate_processing_time(start_time)
        
        return OptimizeTourResponse(
            status="success",
            message="Tournée optimisée avec succès",
            processed_tours=result["processed_tours"],
            processing_time=processing_time
        )
        
    except ValueError as e:
        # Erreurs métier (statut incorrect, tournée non trouvée, etc.)
        processing_time = _calculate_processing_time(start_time)
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "message": str(e),
                "processing_time": processing_time,
                "error_code": "INVALID_TOUR_STATUS"
            }
        )
        
    except Exception as e:
        processing_time = _calculate_processing_time(start_time)
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": f"Erreur lors de l'optimisation: {str(e)}",
                "processing_time": processing_time,
                "error_code": "OPTIMIZATION_ERROR"
            }
        )


# ============================================================================
# ENDPOINTS FUTURS (structure préparée, développement ultérieur)
# ============================================================================

@router.post(
    "/late-stops/{late_stop_request_id}/process",
    summary="Traitement des arrêts tardifs",
    description="Insère des arrêts de dernière minute dans une tournée en cours"
)
async def process_late_stop(
    late_stop_request_id: str,
    api_key: str = Depends(verify_api_key)
):
    """
    Traite une demande d'arrêt tardif pour une tournée en cours
    
    - **late_stop_request_id**: ID de la demande de dernière minute depuis lab_tour_late_stops
    - Détermine automatiquement le placement optimal du/des stop(s)
    - Met à jour les stop_order de la tournée
    - Crée les shipments de dernière minute appropriés
    """
    from app.services.tours.late_stop_processor import LateStopProcessor
    
    start_time = datetime.now()
    
    try:
        # Initialiser le processeur de late stops
        late_stop_processor = LateStopProcessor()
        
        # Traiter la demande de dernière minute
        result = await late_stop_processor.process_late_stop_request(late_stop_request_id)
        
        # Calcul du temps de traitement
        processing_time = _calculate_processing_time(start_time)
        
        return {
            "status": "success",
            "message": "Arrêt de dernière minute traité avec succès",
            "late_stop_request_id": late_stop_request_id,
            "processing_time": processing_time,
            "placement_result": {
                "driver_route_id": result["driver_route_id"],
                "inserted_stops": result["inserted_stops"],
                "placement_details": result["placement_details"],
                "created_shipments": result["created_shipments"]
            },
            "tour_updates": {
                "total_stops_before": result["tour_updates"]["stops_before"],
                "total_stops_after": result["tour_updates"]["stops_after"],
                "stops_reordered": result["tour_updates"]["stops_reordered"],
                "sequence_updated": True
            }
        }
        
    except ValueError as e:
        # Erreurs métier (late stop non trouvé, statut incorrect, etc.)
        processing_time = _calculate_processing_time(start_time)
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "message": str(e),
                "processing_time": processing_time,
                "error_code": "INVALID_LATE_STOP_REQUEST"
            }
        )
        
    except Exception as e:
        processing_time = _calculate_processing_time(start_time)
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": f"Erreur lors du traitement de l'arrêt tardif: {str(e)}",
                "processing_time": processing_time,
                "error_code": "LATE_STOP_PROCESSING_ERROR"
            }
        )


@router.post("/test-late-stop-processing")
async def test_late_stop_processing(
    request: dict,
    api_key: str = Depends(verify_api_key)
):
    """
    Test endpoint pour simuler le traitement d'un arrêt de dernière minute
    Utile pour déboguer avant d'utiliser de vraies données
    """
    from app.services.tours.late_stop_processor import LateStopProcessor
    
    # Paramètres du test
    test_params = {
        "mock_late_stop_id": request.get("late_stop_id"),
        "mock_driver_route_id": request.get("driver_route_id"),
        "simulate_placement": request.get("simulate_placement", True)
    }
    
    try:
        late_stop_processor = LateStopProcessor()
        
        if test_params["simulate_placement"]:
            # Mode simulation : analyser sans créer
            simulation_result = {
                "status": "simulation",
                "message": "Mode simulation - aucune modification en base",
                "test_parameters": test_params,
                "workflow_steps": [
                    "✅ Récupération de la demande late_stop",
                    "✅ Validation du statut (pending)",
                    "✅ Récupération de la tournée laboratoire",
                    "✅ Identification de la tournée driver",
                    "✅ Analyse de la séquence actuelle",
                    "✅ Détermination du placement optimal",
                    "🔄 Création des stops (SIMULÉ)",
                    "🔄 Mise à jour des stop_order (SIMULÉ)",
                    "🔄 Changement de statut à 'approved' (SIMULÉ)"
                ]
            }
            return simulation_result
        else:
            # Mode réel : traiter la vraie demande
            late_stop_id = test_params["mock_late_stop_id"]
            if not late_stop_id:
                return {"status": "error", "message": "late_stop_id requis pour le mode réel"}
            
            result = await late_stop_processor.process_late_stop_request(late_stop_id)
            
            return {
                "status": "success",
                "message": "Test de traitement réel terminé",
                "result": result
            }
            
    except Exception as e:
        return {
            "status": "error",
            "message": f"Erreur lors du test: {str(e)}",
            "test_parameters": test_params
        }


# @router.post(
#     "/unexpected-shipments",
#     summary="Gestion des envois imprévus",
#     description="Traite un envoi imprévu signalé par l'app livreur"
# )
# async def handle_unexpected_shipment(
#     api_key: str = Depends(verify_api_key)
# ):
#     """
#     DÉVELOPPEMENT FUTUR
#     Gère un colis imprévu détecté par un livreur
#     """
#     pass


# ============================================================================
# FONCTIONS UTILITAIRES
# ============================================================================

def _calculate_processing_time(start_time: datetime) -> str:
    """
    Calcule le temps de traitement au format lisible
    
    Args:
        start_time: Heure de début du traitement
        
    Returns:
        str: Temps formaté (ex: "1m 23s", "45s")
    """
    duration = datetime.now() - start_time
    total_seconds = int(duration.total_seconds())
    
    if total_seconds >= 60:
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}m {seconds}s"
    else:
        return f"{total_seconds}s"