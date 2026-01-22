"""
Service de reconstruction V2 - Avec garantie de conformité des UUID
"""

import structlog
from typing import Dict, List, Any, Optional, Set
from datetime import datetime
from .uuid_tracker import UUIDTracker, UUIDTrackerError

logger = structlog.get_logger()


class TourReconstructorV2:
    """
    Reconstructeur V2 avec garantie absolue de conformité des UUID
    
    Garantit :
    1. Tous les UUID originaux sont préservés
    2. Aucun expanded ID dans le résultat final
    3. Depot pickup TOUJOURS en position 1
    4. Shared pickups groupés au début
    5. Traçabilité complète des transformations
    """
    
    def __init__(self):
        self.uuid_tracker = UUIDTracker()
    
    def reconstruct_with_uuid_conformity(self, 
                                       original_stops: List[Dict],
                                       original_shipments: List[Dict],
                                       phase1_stops: List[Dict], 
                                       phase2_stops: List[Dict]) -> Dict:
        """
        Reconstruction avec garantie de conformité UUID
        
        Args:
            original_stops: Stops originaux de la base (référence absolue)
            original_shipments: Shipments originaux
            phase1_stops: Stops optimisés Phase 1
            phase2_stops: Stops optimisés Phase 2 (peuvent contenir expanded)
            
        Returns:
            Dict: Résultat avec tournée reconstruite et rapport de conformité
        """
        logger.info("Starting UUID-conformant tour reconstruction",
                   original_stops=len(original_stops),
                   phase1_stops=len(phase1_stops),
                   phase2_stops=len(phase2_stops))
        
        # 1. Initialiser le tracking
        self.uuid_tracker.initialize_tracking(original_stops, original_shipments)
        
        # 2. Analyser et nettoyer les données d'entrée
        cleaned_data = self._clean_input_data(phase1_stops, phase2_stops, original_stops)
        
        # 3. Conversion sécurisée expanded → real
        converted_data = self._safe_expanded_to_real_conversion(
            cleaned_data["phase1_cleaned"],
            cleaned_data["phase2_cleaned"],
            original_stops
        )
        
        # 4. Reconstruction avec règles strictes
        reconstructed_tour = self._reconstruct_with_strict_rules(
            converted_data["phase1_real"],
            converted_data["phase2_real"]
        )
        
        # 5. Validation finale de conformité
        conformity_report = self.uuid_tracker.validate_final_state(reconstructed_tour)
        
        # 6. Génération du plan de sauvegarde
        save_plan = self._generate_save_plan(reconstructed_tour, converted_data["conversion_map"])
        
        result = {
            "reconstructed_tour": reconstructed_tour,
            "conformity_report": conformity_report,
            "conversion_summary": converted_data["conversion_summary"],
            "save_plan": save_plan,
            "audit_report": self.uuid_tracker.get_audit_report(),
            "success": conformity_report["valid"]
        }
        
        if result["success"]:
            logger.info("UUID-conformant reconstruction SUCCESS",
                       final_stops=len(reconstructed_tour),
                       conformity=conformity_report["statistics"]["conformity_percentage"])
        else:
            logger.error("UUID-conformant reconstruction FAILED",
                        issues=conformity_report["issues"])
        
        return result
    
    def _clean_input_data(self, phase1_stops: List[Dict], phase2_stops: List[Dict],
                         original_stops: List[Dict]) -> Dict:
        """
        Nettoie et valide les données d'entrée
        """
        logger.info("Cleaning input data for reconstruction")
        
        # Créer l'ensemble des UUID originaux pour validation
        original_uuids = {s["id"] for s in original_stops}
        
        # Nettoyer Phase 1 (normalement que des UUID originaux)
        phase1_cleaned = []
        phase1_issues = []
        
        for stop in phase1_stops:
            stop_id = stop["id"]
            if stop_id in original_uuids or "_expanded_" in stop_id:
                phase1_cleaned.append(stop)
            else:
                phase1_issues.append(f"Unknown UUID in Phase1: {stop_id[:8]}")
        
        # Nettoyer Phase 2 (peut contenir expanded)
        phase2_cleaned = []
        phase2_issues = []
        
        for stop in phase2_stops:
            stop_id = stop["id"]
            if stop_id in original_uuids or "_expanded_" in stop_id:
                phase2_cleaned.append(stop)
            else:
                phase2_issues.append(f"Unknown UUID in Phase2: {stop_id[:8]}")
        
        cleaning_report = {
            "phase1_cleaned": phase1_cleaned,
            "phase2_cleaned": phase2_cleaned,
            "issues": phase1_issues + phase2_issues,
            "statistics": {
                "phase1_original": len(phase1_stops),
                "phase1_cleaned": len(phase1_cleaned),
                "phase2_original": len(phase2_stops),
                "phase2_cleaned": len(phase2_cleaned),
                "total_issues": len(phase1_issues) + len(phase2_issues)
            }
        }
        
        if cleaning_report["issues"]:
            logger.warning("Data cleaning found issues",
                         issues_count=len(cleaning_report["issues"]),
                         sample_issues=cleaning_report["issues"][:3])
        
        return cleaning_report
    
    def _safe_expanded_to_real_conversion(self, phase1_stops: List[Dict], 
                                        phase2_stops: List[Dict],
                                        original_stops: List[Dict]) -> Dict:
        """
        Conversion sécurisée expanded → real avec traçabilité
        """
        logger.info("Starting safe expanded to real conversion")
        
        # Créer le mapping original pour récupérer les données
        original_data_map = {s["id"]: s for s in original_stops}
        
        # Traiter Phase 1 (normalement pas d'expanded)
        phase1_real = []
        for stop in phase1_stops:
            if "_expanded_" not in stop["id"]:
                phase1_real.append(stop)
            else:
                logger.warning("Expanded ID found in Phase1", stop_id=stop["id"][:20])
                real_id = stop["id"].split("_expanded_")[0]
                if real_id in original_data_map:
                    converted_stop = self._merge_expanded_with_original(
                        stop, original_data_map[real_id]
                    )
                    phase1_real.append(converted_stop)
        
        # Traiter Phase 2 (peut contenir many expanded)
        phase2_real = []
        conversion_map = {}
        
        # Grouper les expanded par real_id
        expanded_groups = {}
        real_stops = []
        
        for stop in phase2_stops:
            if "_expanded_" in stop["id"]:
                real_id = stop["id"].split("_expanded_")[0]
                if real_id not in expanded_groups:
                    expanded_groups[real_id] = []
                expanded_groups[real_id].append(stop)
                conversion_map[stop["id"]] = real_id
            else:
                real_stops.append(stop)
        
        # Convertir chaque groupe expanded → real
        for real_id, expanded_list in expanded_groups.items():
            if real_id in original_data_map:
                # Fusionner tous les expanded vers le real original
                merged_stop = self._merge_multiple_expanded_to_real(
                    expanded_list, original_data_map[real_id]
                )
                phase2_real.append(merged_stop)
                
                # Logger la conversion
                logger.debug("Converted expanded group to real",
                           real_id=real_id[:8],
                           expanded_count=len(expanded_list))
        
        # Ajouter les stops déjà réels
        phase2_real.extend(real_stops)
        
        conversion_summary = {
            "phase1_conversions": 0,
            "phase2_conversions": len(expanded_groups),
            "total_expanded_converted": sum(len(group) for group in expanded_groups.values()),
            "conversion_map": conversion_map
        }
        
        logger.info("Expanded to real conversion completed",
                   phase1_real=len(phase1_real),
                   phase2_real=len(phase2_real),
                   conversions=conversion_summary["phase2_conversions"])
        
        return {
            "phase1_real": phase1_real,
            "phase2_real": phase2_real,
            "conversion_summary": conversion_summary,
            "conversion_map": conversion_map
        }
    
    def _merge_expanded_with_original(self, expanded_stop: Dict, original_stop: Dict) -> Dict:
        """
        Fusionne un stop expanded avec son original en préservant les données importantes
        """
        # Partir de l'original comme base
        merged = original_stop.copy()
        
        # Préserver les données d'optimisation de l'expanded
        optimization_fields = [
            "final_stop_order", "optimized_stop_order", "stop_order",
            "estimated_arrival_time", "estimated_departure_time",
            "distance_from_previous", "duration_from_previous",
            "client_actions", "optimized"
        ]
        
        for field in optimization_fields:
            if field in expanded_stop:
                merged[field] = expanded_stop[field]
        
        # Marquer comme converti
        merged["_converted_from_expanded"] = True
        merged["_conversion_timestamp"] = datetime.now().isoformat()
        
        return merged
    
    def _merge_multiple_expanded_to_real(self, expanded_list: List[Dict], 
                                       original_stop: Dict) -> Dict:
        """
        Fusionne plusieurs stops expanded du même real_id vers l'original
        """
        # Trier par ordre final pour garder le meilleur
        expanded_list.sort(key=lambda x: x.get("final_stop_order", x.get("stop_order", 999)))
        
        # Utiliser le premier (meilleur ordre) comme base
        best_expanded = expanded_list[0]
        
        # Fusionner avec l'original
        merged = self._merge_expanded_with_original(best_expanded, original_stop)
        
        # Ajouter les métadonnées de fusion
        merged["_merged_from_expanded_count"] = len(expanded_list)
        merged["_merged_expanded_ids"] = [s["id"] for s in expanded_list]
        
        return merged
    
    def _reconstruct_with_strict_rules(self, phase1_real: List[Dict], 
                                     phase2_real: List[Dict]) -> List[Dict]:
        """
        Reconstruction avec règles strictes garanties - CONCATÉNATION PURE Phase1 + Phase2
        
        RÈGLE ABSOLUE : Phase 1 (shared pickups) + Phase 2 (regular stops)
        PAS de tri global ! Respecter l'ordre de chaque phase.
        """
        logger.info("Reconstructing with strict concatenation rules")
        
        # 1. Extraire le depot_pickup de Phase 1
        depot_pickup = None
        remaining_phase1 = []
        
        for stop in phase1_real:
            if stop.get("stop_type") == "depot_pickup":
                if depot_pickup is None:
                    depot_pickup = stop
                    logger.info("Depot pickup found for position 1", stop_id=stop["id"][:8])
                else:
                    logger.warning("Multiple depot pickups found", 
                                 existing=depot_pickup["id"][:8],
                                 duplicate=stop["id"][:8])
            else:
                remaining_phase1.append(stop)
        
        # 2. 🆕 PRÉSERVER L'ORDRE PHASE 1 (shared pickups) - PAS de tri !
        # Les shared pickups sont déjà optimisés par Phase 1, respecter cet ordre
        shared_pickups = sorted(remaining_phase1, 
                               key=lambda x: x.get("optimized_stop_order", x.get("stop_order", 999)))
        
        # 3. 🆕 PRÉSERVER L'ORDRE PHASE 2 (regular stops) - PAS de tri global !
        # Les regular stops sont déjà optimisés par OR-Tools, respecter cet ordre
        regular_stops = sorted(phase2_real,
                              key=lambda x: x.get("final_stop_order", x.get("stop_order", 999)))
        
        # 4. 🎯 CONCATÉNATION STRICTE : Depot + Phase1 + Phase2
        final_sequence = []
        current_order = 1
        
        # Position 1 : Depot pickup (obligatoire si présent)
        if depot_pickup:
            depot_pickup["final_stop_order"] = current_order
            final_sequence.append(depot_pickup)
            current_order += 1
            logger.info("Depot pickup placed at position 1")
        
        # Positions suivantes : TOUS les shared pickups (Phase 1) EN BLOC
        for shared_pickup in shared_pickups:
            shared_pickup["final_stop_order"] = current_order
            final_sequence.append(shared_pickup)
            current_order += 1
        
        phase1_end_position = current_order - 1
        logger.info("Phase 1 (shared pickups) placed in BLOCK", 
                   count=len(shared_pickups),
                   positions=f"{2 if depot_pickup else 1}-{phase1_end_position}")
        
        # Positions finales : TOUS les regular stops (Phase 2) EN BLOC
        for regular_stop in regular_stops:
            regular_stop["final_stop_order"] = current_order
            final_sequence.append(regular_stop)
            current_order += 1
        
        phase2_start_position = phase1_end_position + 1
        phase2_end_position = current_order - 1
        logger.info("Phase 2 (regular stops) placed in BLOCK", 
                   count=len(regular_stops),
                   positions=f"{phase2_start_position}-{phase2_end_position}")
        
        # 5. Validation finale de la séquence
        self._validate_final_sequence(final_sequence)
        
        # 6. 🆕 VÉRIFICATION SPÉCIALE : Pas de shared pickups dans Phase 2
        self._validate_phase_separation(final_sequence, len(shared_pickups) + (1 if depot_pickup else 0))
        
        logger.info("Strict concatenation reconstruction completed",
                   depot_pickup=depot_pickup is not None,
                   phase1_stops=len(shared_pickups),
                   phase2_stops=len(regular_stops),
                   total_stops=len(final_sequence))
        
        return final_sequence
    
    def _validate_final_sequence(self, final_sequence: List[Dict]):
        """
        Valide la séquence finale selon les règles strictes
        """
        if not final_sequence:
            return
        
        # Vérifier depot_pickup en position 1 (si présent)
        if final_sequence[0].get("stop_type") != "depot_pickup":
            # Vérifier s'il y a un depot_pickup ailleurs
            depot_elsewhere = any(s.get("stop_type") == "depot_pickup" for s in final_sequence[1:])
            if depot_elsewhere:
                logger.error("Depot pickup not in position 1!")
                raise UUIDTrackerError("Depot pickup found but not in position 1")
        
        # Vérifier continuité des ordres
        for i, stop in enumerate(final_sequence):
            expected = i + 1
            actual = stop.get("final_stop_order")
            if actual != expected:
                logger.error("Order discontinuity detected",
                           position=i+1,
                           expected=expected,
                           actual=actual)
                raise UUIDTrackerError(f"Order discontinuity at position {i+1}")
        
        # Vérifier pas d'expanded IDs
        expanded_ids = [s["id"] for s in final_sequence if "_expanded_" in s["id"]]
        if expanded_ids:
            logger.error("Expanded IDs in final sequence", count=len(expanded_ids))
            raise UUIDTrackerError(f"Expanded IDs remain in final sequence: {len(expanded_ids)}")
        
        logger.info("Final sequence validation PASSED",
                   total_stops=len(final_sequence),
                   depot_first=final_sequence[0].get("stop_type") == "depot_pickup")
    
    def _validate_phase_separation(self, final_sequence: List[Dict], phase1_end_index: int):
        """
        Valide que les phases sont bien séparées (shared pickups AVANT regular stops)
        
        Args:
            final_sequence: Séquence finale reconstruite
            phase1_end_index: Index de fin de la Phase 1 (position du dernier shared pickup)
        """
        if not final_sequence or phase1_end_index <= 0:
            return
        
        logger.info("Validating phase separation",
                   phase1_end_index=phase1_end_index,
                   total_stops=len(final_sequence))
        
        # Vérifier que les shared pickups sont TOUS au début
        shared_pickup_violations = []
        regular_stop_violations = []
        
        for i, stop in enumerate(final_sequence):
            position = i + 1
            is_shared = stop.get("is_shared_pickup_stop", False)
            stop_type = stop.get("stop_type", "unknown")
            
            if position <= phase1_end_index:
                # Zone Phase 1 : doit contenir SEULEMENT depot_pickup OU shared pickups
                if not (stop_type == "depot_pickup" or is_shared):
                    regular_stop_violations.append({
                        "position": position,
                        "stop_id": stop["id"][:8],
                        "stop_type": stop_type,
                        "is_shared": is_shared,
                        "issue": "Regular stop in Phase 1 zone"
                    })
            else:
                # Zone Phase 2 : NE DOIT PAS contenir de shared pickups
                if is_shared or stop_type == "depot_pickup":
                    shared_pickup_violations.append({
                        "position": position,
                        "stop_id": stop["id"][:8], 
                        "stop_type": stop_type,
                        "is_shared": is_shared,
                        "issue": "Shared pickup in Phase 2 zone"
                    })
        
        # Reporter les violations
        total_violations = len(shared_pickup_violations) + len(regular_stop_violations)
        
        if total_violations > 0:
            logger.error("Phase separation validation FAILED",
                        shared_pickup_violations=len(shared_pickup_violations),
                        regular_stop_violations=len(regular_stop_violations),
                        total_violations=total_violations)
            
            # Logger les détails des violations
            for violation in shared_pickup_violations:
                logger.error("Phase violation", **violation)
            
            for violation in regular_stop_violations:
                logger.error("Phase violation", **violation)
            
            raise UUIDTrackerError(f"Phase separation failed: {total_violations} violations detected")
        
        logger.info("Phase separation validation PASSED",
                   phase1_zone=f"1-{phase1_end_index}",
                   phase2_zone=f"{phase1_end_index+1}-{len(final_sequence)}")
    
    def _generate_save_plan(self, reconstructed_tour: List[Dict], 
                           conversion_map: Dict) -> Dict:
        """
        Génère un plan de sauvegarde sécurisé
        """
        save_plan = {
            "total_stops": len(reconstructed_tour),
            "shipment_updates_needed": len(conversion_map),
            "update_operations": []
        }
        
        # Planifier les updates de shipments pour les conversions
        for expanded_id, real_id in conversion_map.items():
            save_plan["update_operations"].append({
                "operation": "update_shipment_references",
                "from_id": expanded_id,
                "to_id": real_id,
                "fields": ["pickup_stop_id", "delivery_stop_id"]
            })
        
        # Planifier les updates des stop_order
        for i, stop in enumerate(reconstructed_tour, 1):
            save_plan["update_operations"].append({
                "operation": "update_stop_order",
                "stop_id": stop["id"],
                "new_order": i,
                "estimated_arrival": stop.get("estimated_arrival_time")
            })
        
        return save_plan


class TourReconstructorV2Error(Exception):
    """Exception levée lors d'erreurs de reconstruction V2"""
    pass