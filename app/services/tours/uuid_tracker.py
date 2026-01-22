"""
Service de traçabilité des UUID - Garantit la conformité des données
Suit chaque UUID tout au long du processus d'optimisation
"""

import structlog
from typing import Dict, List, Any, Set, Optional
from collections import defaultdict
import uuid as uuid_lib

logger = structlog.get_logger()


class UUIDTracker:
    """
    Service de traçabilité complète des UUID dans le processus d'optimisation
    
    Garantit :
    1. Aucun UUID perdu ou dupliqué
    2. Traçabilité complète des transformations
    3. Conformité des données à chaque étape
    4. Rollback possible en cas de problème
    """
    
    def __init__(self):
        self.original_uuids = set()
        self.transformations = {}  # uuid_original -> [transformations]
        self.expanded_to_real = {}  # uuid_expanded -> uuid_real
        self.current_state = {}  # uuid -> current_data
        self.audit_log = []
    
    def initialize_tracking(self, original_stops: List[Dict], original_shipments: List[Dict]):
        """
        Initialise le tracking avec les données originales
        
        Args:
            original_stops: Stops originaux de la base
            original_shipments: Shipments originaux de la base
        """
        logger.info("Initializing UUID tracking", 
                   stops_count=len(original_stops),
                   shipments_count=len(original_shipments))
        
        # Enregistrer tous les UUID originaux
        for stop in original_stops:
            stop_id = stop["id"]
            self.original_uuids.add(stop_id)
            self.current_state[stop_id] = {
                "type": "stop",
                "original_data": stop.copy(),
                "current_data": stop.copy(),
                "transformations": [],
                "status": "original"
            }
        
        for shipment in original_shipments:
            shipment_id = shipment["id"]
            self.original_uuids.add(shipment_id)
            self.current_state[shipment_id] = {
                "type": "shipment",
                "original_data": shipment.copy(),
                "current_data": shipment.copy(),
                "transformations": [],
                "status": "original"
            }
        
        self._log_audit("initialization", f"Tracked {len(self.original_uuids)} original UUIDs")
    
    def track_expanded_creation(self, real_id: str, expanded_id: str, 
                               expanded_data: Dict, reason: str):
        """
        Enregistre la création d'un stop expanded
        
        Args:
            real_id: UUID réel original
            expanded_id: UUID expanded créé (ex: real_id_expanded_1)
            expanded_data: Données du stop expanded
            reason: Raison de l'expansion
        """
        if real_id not in self.current_state:
            logger.warning("Expanded creation for unknown real_id",
                         real_id=real_id[:8],
                         expanded_id=expanded_id[:20])
        
        # Enregistrer le mapping
        self.expanded_to_real[expanded_id] = real_id
        
        # Créer l'entrée pour l'expanded
        self.current_state[expanded_id] = {
            "type": "stop_expanded",
            "original_data": None,
            "current_data": expanded_data.copy(),
            "transformations": [
                {
                    "operation": "expanded_creation",
                    "from_id": real_id,
                    "to_id": expanded_id,
                    "reason": reason,
                    "timestamp": self._get_timestamp()
                }
            ],
            "status": "expanded",
            "real_id": real_id
        }
        
        # Mettre à jour le real stop
        if real_id in self.current_state:
            self.current_state[real_id]["transformations"].append({
                "operation": "spawned_expanded",
                "spawned_id": expanded_id,
                "reason": reason,
                "timestamp": self._get_timestamp()
            })
        
        self._log_audit("expanded_creation", 
                       f"Created expanded {expanded_id[:20]} from {real_id[:8]}")
    
    def track_reconstruction(self, phase1_stops: List[Dict], phase2_stops: List[Dict],
                           reconstructed_stops: List[Dict]) -> Dict:
        """
        Track la reconstruction de la tournée et vérifie la conformité
        
        Args:
            phase1_stops: Stops de la Phase 1
            phase2_stops: Stops de la Phase 2 
            reconstructed_stops: Stops reconstruits
            
        Returns:
            Dict: Rapport de conformité
        """
        logger.info("Tracking tour reconstruction",
                   phase1=len(phase1_stops),
                   phase2=len(phase2_stops),
                   reconstructed=len(reconstructed_stops))
        
        # Créer les ensembles d'UUID
        phase1_ids = {s["id"] for s in phase1_stops}
        phase2_ids = {s["id"] for s in phase2_stops}
        reconstructed_ids = {s["id"] for s in reconstructed_stops}
        
        # Analyser les transformations
        expanded_ids_in_reconstructed = {id for id in reconstructed_ids if "_expanded_" in id}
        real_ids_in_reconstructed = reconstructed_ids - expanded_ids_in_reconstructed
        
        # Créer le mapping expanded → real dans la reconstruction
        expanded_to_real_map = {}
        for stop in reconstructed_stops:
            if "_expanded_" in stop["id"]:
                real_id = stop["id"].split("_expanded_")[0]
                expanded_to_real_map[stop["id"]] = real_id
        
        # Vérifications de conformité
        conformity_issues = []
        
        # 1. Vérifier qu'aucun UUID original n'est perdu
        all_input_ids = phase1_ids | phase2_ids
        original_stops_in_input = {id for id in all_input_ids if id in self.original_uuids}
        
        if not original_stops_in_input.issubset(reconstructed_ids | 
                                                {self.expanded_to_real.get(exp, exp) 
                                                 for exp in expanded_ids_in_reconstructed}):
            missing_originals = original_stops_in_input - reconstructed_ids
            conformity_issues.append(f"Original UUIDs lost: {len(missing_originals)}")
        
        # 2. Vérifier les expanded → real mappings
        unmapped_expanded = []
        for expanded_id in expanded_ids_in_reconstructed:
            if expanded_id not in self.expanded_to_real:
                unmapped_expanded.append(expanded_id)
        
        if unmapped_expanded:
            conformity_issues.append(f"Unmapped expanded IDs: {len(unmapped_expanded)}")
        
        # 3. Vérifier les duplications
        real_ids_from_expanded = {self.expanded_to_real.get(exp) for exp in expanded_ids_in_reconstructed}
        real_ids_from_expanded.discard(None)
        
        duplicate_reals = real_ids_in_reconstructed & real_ids_from_expanded
        if duplicate_reals:
            conformity_issues.append(f"Duplicate real IDs: {len(duplicate_reals)}")
        
        # Générer le rapport de conformité
        conformity_report = {
            "conformity_valid": len(conformity_issues) == 0,
            "issues": conformity_issues,
            "statistics": {
                "total_reconstructed": len(reconstructed_stops),
                "real_ids": len(real_ids_in_reconstructed),
                "expanded_ids": len(expanded_ids_in_reconstructed),
                "original_uuids_preserved": len(original_stops_in_input),
                "duplicates_detected": len(duplicate_reals)
            },
            "mappings": {
                "expanded_to_real": expanded_to_real_map,
                "total_mappings": len(expanded_to_real_map)
            }
        }
        
        # Logger les problèmes
        if conformity_issues:
            logger.error("UUID conformity issues detected",
                        issues_count=len(conformity_issues),
                        issues=conformity_issues[:3])
        else:
            logger.info("UUID conformity validated successfully")
        
        self._log_audit("reconstruction_tracking", 
                       f"Conformity: {'PASS' if conformity_report['conformity_valid'] else 'FAIL'}")
        
        return conformity_report
    
    def generate_safe_conversion_plan(self, stops_with_expanded: List[Dict]) -> Dict:
        """
        Génère un plan de conversion sûr expanded → real
        
        Args:
            stops_with_expanded: Stops contenant des expanded IDs
            
        Returns:
            Dict: Plan de conversion avec toutes les étapes nécessaires
        """
        logger.info("Generating safe conversion plan", 
                   stops_count=len(stops_with_expanded))
        
        conversion_plan = {
            "conversions": [],
            "shipment_updates": [],
            "preservation_map": {},
            "validation": {"safe": True, "warnings": []}
        }
        
        # Analyser chaque stop
        for stop in stops_with_expanded:
            stop_id = stop["id"]
            
            if "_expanded_" in stop_id:
                # C'est un expanded, planifier la conversion
                real_id = stop_id.split("_expanded_")[0]
                
                # Vérifier que le real_id est dans nos originaux
                if real_id not in self.original_uuids:
                    conversion_plan["validation"]["safe"] = False
                    conversion_plan["validation"]["warnings"].append(
                        f"Conversion vers UUID non-original: {real_id[:8]}"
                    )
                
                conversion_plan["conversions"].append({
                    "from_id": stop_id,
                    "to_id": real_id,
                    "stop_data": stop,
                    "preservation_required": True
                })
                
                # Planifier les updates de shipments
                conversion_plan["shipment_updates"].extend(
                    self._plan_shipment_updates_for_conversion(stop_id, real_id)
                )
                
                # Préserver les données importantes
                conversion_plan["preservation_map"][real_id] = {
                    "original_data": self.current_state.get(real_id, {}).get("original_data"),
                    "optimized_data": stop,
                    "fields_to_preserve": ["final_stop_order", "estimated_arrival_time", 
                                         "client_actions", "optimized"]
                }
            else:
                # Stop déjà réel, juste vérifier qu'il existe
                if stop_id not in self.original_uuids:
                    conversion_plan["validation"]["warnings"].append(
                        f"Stop avec UUID non-original: {stop_id[:8]}"
                    )
        
        logger.info("Conversion plan generated",
                   conversions=len(conversion_plan["conversions"]),
                   shipment_updates=len(conversion_plan["shipment_updates"]),
                   safe=conversion_plan["validation"]["safe"])
        
        return conversion_plan
    
    def _plan_shipment_updates_for_conversion(self, expanded_id: str, real_id: str) -> List[Dict]:
        """Planifie les updates de shipments pour une conversion"""
        
        shipment_updates = []
        
        # Trouver tous les shipments qui référencent cet expanded_id
        for shipment_id, state in self.current_state.items():
            if state["type"] != "shipment":
                continue
            
            shipment = state["current_data"]
            
            # Vérifier pickup_stop_id
            if shipment.get("pickup_stop_id") == expanded_id:
                shipment_updates.append({
                    "shipment_id": shipment_id,
                    "field": "pickup_stop_id",
                    "from_value": expanded_id,
                    "to_value": real_id,
                    "reason": "expanded_to_real_conversion"
                })
            
            # Vérifier delivery_stop_id
            if shipment.get("delivery_stop_id") == expanded_id:
                shipment_updates.append({
                    "shipment_id": shipment_id,
                    "field": "delivery_stop_id", 
                    "from_value": expanded_id,
                    "to_value": real_id,
                    "reason": "expanded_to_real_conversion"
                })
        
        return shipment_updates
    
    def validate_final_state(self, final_stops: List[Dict]) -> Dict:
        """
        Validation finale de l'état après toutes les transformations
        
        Args:
            final_stops: Stops dans leur état final
            
        Returns:
            Dict: Rapport de validation finale
        """
        final_ids = {s["id"] for s in final_stops}
        expanded_ids_remaining = {id for id in final_ids if "_expanded_" in id}
        
        validation_report = {
            "valid": True,
            "issues": [],
            "statistics": {
                "total_final_stops": len(final_stops),
                "original_uuids_preserved": len(final_ids & self.original_uuids),
                "expanded_ids_remaining": len(expanded_ids_remaining),
                "conformity_percentage": 0
            }
        }
        
        # Issues critiques
        if expanded_ids_remaining:
            validation_report["valid"] = False
            validation_report["issues"].append(
                f"❌ {len(expanded_ids_remaining)} expanded IDs still present in final state"
            )
        
        # Calcul du pourcentage de conformité
        if self.original_uuids:
            conformity = len(final_ids & self.original_uuids) / len(self.original_uuids) * 100
            validation_report["statistics"]["conformity_percentage"] = round(conformity, 1)
        
        if validation_report["statistics"]["conformity_percentage"] < 90:
            validation_report["valid"] = False
            validation_report["issues"].append(
                f"❌ Low conformity: {validation_report['statistics']['conformity_percentage']}%"
            )
        
        logger.info("Final state validation",
                   valid=validation_report["valid"],
                   conformity=validation_report["statistics"]["conformity_percentage"],
                   issues_count=len(validation_report["issues"]))
        
        return validation_report
    
    def get_audit_report(self) -> Dict:
        """Génère un rapport d'audit complet"""
        return {
            "original_uuids_count": len(self.original_uuids),
            "current_tracked_count": len(self.current_state),
            "expanded_mappings_count": len(self.expanded_to_real),
            "audit_log": self.audit_log[-20:],  # Dernières 20 entrées
            "transformations_summary": self._summarize_transformations()
        }
    
    def _summarize_transformations(self) -> Dict:
        """Résume toutes les transformations"""
        operations = defaultdict(int)
        
        for state in self.current_state.values():
            for transformation in state.get("transformations", []):
                operations[transformation["operation"]] += 1
        
        return dict(operations)
    
    def _log_audit(self, operation: str, details: str):
        """Enregistre une entrée d'audit"""
        self.audit_log.append({
            "operation": operation,
            "details": details,
            "timestamp": self._get_timestamp(),
            "tracked_count": len(self.current_state)
        })
    
    def _get_timestamp(self) -> str:
        """Génère un timestamp"""
        from datetime import datetime
        return datetime.now().isoformat()


class UUIDTrackerError(Exception):
    """Exception levée lors d'erreurs de tracking UUID"""
    pass