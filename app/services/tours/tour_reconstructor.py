"""
Service de reconstruction correcte de la tournée après optimisation
Garantit l'ordre correct : depot_pickup → shared pickups → reste de la tournée
"""

import structlog
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = structlog.get_logger()


class TourReconstructor:
    """
    Reconstruit correctement une tournée après les phases d'optimisation
    
    Règles strictes :
    1. depot_pickup TOUJOURS en position 1 (si présent)
    2. Tous les shared pickups groupés au début (positions 2+)
    3. Le reste de la tournée suit
    4. Pas de duplications ni de trous dans la séquence
    """
    
    def __init__(self):
        pass
    
    def reconstruct_optimized_tour(self, 
                                  phase1_stops: List[Dict], 
                                  phase2_stops: List[Dict],
                                  all_original_stops: List[Dict]) -> List[Dict]:
        """
        Reconstruit la tournée complète avec l'ordre correct
        
        Args:
            phase1_stops: Stops optimisés par SharedPickupOptimizer
            phase2_stops: Stops optimisés par OR-Tools
            all_original_stops: Tous les stops originaux (pour récupérer ceux oubliés)
            
        Returns:
            List[Dict]: Tournée reconstruite avec ordre correct
        """
        logger.info("Starting tour reconstruction",
                   phase1_count=len(phase1_stops),
                   phase2_count=len(phase2_stops),
                   original_count=len(all_original_stops))
        
        # 1. Identifier et extraire le depot_pickup
        depot_pickup = self._extract_depot_pickup(phase1_stops, phase2_stops, all_original_stops)
        
        # 2. Identifier TOUS les shared pickups (sauf depot déjà extrait)
        all_shared_pickups = self._extract_all_shared_pickups(
            phase1_stops, phase2_stops, all_original_stops, 
            exclude_depot=depot_pickup is not None
        )
        
        # 3. Identifier les stops réguliers (non-shared)
        regular_stops = self._extract_regular_stops(phase2_stops, all_original_stops)
        
        # 4. Construire la séquence finale
        final_sequence = []
        current_order = 1
        
        # Depot pickup en PREMIER (si présent)
        if depot_pickup:
            depot_pickup["final_stop_order"] = current_order
            final_sequence.append(depot_pickup)
            current_order += 1
            logger.info("Depot pickup placed at position 1",
                       stop_id=depot_pickup["id"][:8])
        
        # Tous les shared pickups ensuite (lab_pickups)
        for shared_pickup in all_shared_pickups:
            shared_pickup["final_stop_order"] = current_order
            final_sequence.append(shared_pickup)
            current_order += 1
        
        logger.info("Shared pickups placed",
                   count=len(all_shared_pickups),
                   positions=f"{1 if not depot_pickup else 2}-{current_order-1}")
        
        # Le reste de la tournée (stops réguliers)
        for stop in regular_stops:
            stop["final_stop_order"] = current_order
            final_sequence.append(stop)
            current_order += 1
        
        # 5. Validation finale
        validation = self._validate_reconstruction(final_sequence, all_original_stops)
        
        if not validation["valid"]:
            logger.error("Tour reconstruction validation failed",
                        issues=validation["issues"])
        
        logger.info("Tour reconstruction completed",
                   total_stops=len(final_sequence),
                   depot_first=depot_pickup is not None,
                   shared_pickups_grouped=len(all_shared_pickups),
                   validation=validation)
        
        return final_sequence
    
    def _extract_depot_pickup(self, phase1_stops: List[Dict], 
                             phase2_stops: List[Dict],
                             all_original_stops: List[Dict]) -> Optional[Dict]:
        """
        Extrait le depot_pickup depuis n'importe quelle source
        Il DOIT être is_shared_pickup_stop=true
        """
        # Chercher d'abord dans Phase1 (devrait y être)
        for stop in phase1_stops:
            if stop.get("stop_type") == "depot_pickup":
                logger.info("Depot pickup found in Phase1", stop_id=stop["id"][:8])
                return stop
        
        # Si pas dans Phase1, chercher dans Phase2 (erreur probable)
        for stop in phase2_stops:
            if stop.get("stop_type") == "depot_pickup":
                logger.warning("Depot pickup found in Phase2 (should be in Phase1!)",
                             stop_id=stop["id"][:8],
                             is_shared=stop.get("is_shared_pickup_stop"))
                return stop
        
        # Dernier recours : chercher dans les stops originaux
        for stop in all_original_stops:
            if (stop.get("stop_type") == "depot_pickup" and 
                stop.get("is_shared_pickup_stop")):
                logger.error("Depot pickup not in optimization phases! Found in original stops",
                           stop_id=stop["id"][:8])
                return stop
        
        logger.info("No depot_pickup found in tour")
        return None
    
    def _extract_all_shared_pickups(self, phase1_stops: List[Dict],
                                   phase2_stops: List[Dict],
                                   all_original_stops: List[Dict],
                                   exclude_depot: bool) -> List[Dict]:
        """
        Extrait TOUS les shared pickups (lab_pickup avec is_shared_pickup_stop=true)
        """
        shared_pickups = []
        seen_ids = set()
        
        # Phase1 devrait contenir tous les shared pickups
        for stop in phase1_stops:
            if (stop.get("is_shared_pickup_stop") and 
                stop["id"] not in seen_ids):
                
                # Exclure le depot si déjà traité
                if exclude_depot and stop.get("stop_type") == "depot_pickup":
                    continue
                    
                shared_pickups.append(stop)
                seen_ids.add(stop["id"])
        
        # Vérifier si des shared pickups sont dans Phase2 (ne devrait pas arriver)
        phase2_shared_count = 0
        for stop in phase2_stops:
            if (stop.get("is_shared_pickup_stop") and 
                stop["id"] not in seen_ids):
                
                if exclude_depot and stop.get("stop_type") == "depot_pickup":
                    continue
                
                logger.warning("Shared pickup found in Phase2!",
                             stop_id=stop["id"][:8],
                             stop_type=stop.get("stop_type"))
                shared_pickups.append(stop)
                seen_ids.add(stop["id"])
                phase2_shared_count += 1
        
        if phase2_shared_count > 0:
            logger.error("Shared pickups incorrectly in Phase2",
                        count=phase2_shared_count,
                        total_shared=len(shared_pickups))
        
        # Trier les shared pickups par optimized_stop_order si disponible
        shared_pickups.sort(key=lambda x: x.get("optimized_stop_order", 999))
        
        return shared_pickups
    
    def _extract_regular_stops(self, phase2_stops: List[Dict],
                              all_original_stops: List[Dict]) -> List[Dict]:
        """
        Extrait les stops réguliers (non-shared) depuis Phase2
        """
        regular_stops = []
        
        for stop in phase2_stops:
            # Ignorer les shared pickups (ne devraient pas y être)
            if stop.get("is_shared_pickup_stop"):
                continue
            
            # Ignorer le depot_pickup s'il est là par erreur
            if stop.get("stop_type") == "depot_pickup":
                continue
            
            regular_stops.append(stop)
        
        # Trier par final_stop_order ou stop_order
        regular_stops.sort(key=lambda x: x.get("final_stop_order", x.get("stop_order", 999)))
        
        return regular_stops
    
    def _validate_reconstruction(self, final_sequence: List[Dict],
                                all_original_stops: List[Dict]) -> Dict:
        """
        Valide la reconstruction de la tournée
        """
        issues = []
        
        # 1. Vérifier depot_pickup en position 1
        if final_sequence and final_sequence[0].get("stop_type") != "depot_pickup":
            # C'est OK si pas de depot_pickup du tout
            has_depot = any(s.get("stop_type") == "depot_pickup" for s in final_sequence)
            if has_depot:
                issues.append("Depot pickup not in position 1")
        
        # 2. Vérifier que tous les shared pickups sont au début
        last_shared_index = -1
        first_regular_index = -1
        
        for i, stop in enumerate(final_sequence):
            if stop.get("is_shared_pickup_stop"):
                last_shared_index = i
            elif first_regular_index == -1:
                first_regular_index = i
        
        if last_shared_index > first_regular_index and first_regular_index != -1:
            issues.append(f"Shared pickups not grouped at start (last at {last_shared_index+1})")
        
        # 3. Vérifier la continuité des ordres
        for i, stop in enumerate(final_sequence):
            expected_order = i + 1
            actual_order = stop.get("final_stop_order")
            if actual_order != expected_order:
                issues.append(f"Order discontinuity at position {i+1}: expected {expected_order}, got {actual_order}")
                break
        
        # 4. Vérifier qu'on n'a pas perdu de stops
        original_ids = {s["id"] for s in all_original_stops}
        final_ids = {s["id"] for s in final_sequence}
        missing_ids = original_ids - final_ids
        
        if missing_ids:
            issues.append(f"Missing {len(missing_ids)} stops from original tour")
            logger.warning("Missing stops detected",
                         count=len(missing_ids),
                         sample_ids=list(missing_ids)[:3])
        
        # 5. Vérifier les duplications
        seen = set()
        duplicates = []
        for stop in final_sequence:
            if stop["id"] in seen:
                duplicates.append(stop["id"])
            seen.add(stop["id"])
        
        if duplicates:
            issues.append(f"Duplicate stops found: {len(duplicates)}")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "stats": {
                "total_stops": len(final_sequence),
                "shared_pickups": sum(1 for s in final_sequence if s.get("is_shared_pickup_stop")),
                "depot_first": final_sequence[0].get("stop_type") == "depot_pickup" if final_sequence else False,
                "missing_stops": len(missing_ids) if missing_ids else 0,
                "duplicate_stops": len(duplicates)
            }
        }


class TourReconstructorError(Exception):
    """Exception levée lors d'erreurs de reconstruction"""
    pass