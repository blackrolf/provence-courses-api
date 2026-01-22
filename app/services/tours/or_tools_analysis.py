"""
Analyse complète des besoins OR-Tools vs données disponibles
"""

from typing import Dict, List, Any
import structlog

logger = structlog.get_logger()


class ORToolsRequirementsAnalysis:
    """Analyse des besoins OR-Tools pour Vehicle Routing Problem (VRP)"""
    
    def __init__(self):
        # Structure des données requises par OR-Tools
        self.or_tools_requirements = {
            "nodes": {
                "depot": "Position de départ/retour du véhicule",
                "pickup_nodes": "Noeuds de récupération (labo, dépôt)",
                "delivery_nodes": "Noeuds de livraison (client, labo)",
                "coordinates": "Coordonnées GPS (latitude, longitude)"
            },
            "distance_matrix": {
                "description": "Matrice distances/durées entre tous les noeuds",
                "format": "distances[i][j] = distance du noeud i au noeud j",
                "units": "Mètres ou minutes selon le type"
            },
            "vehicle_routing": {
                "vehicles": "Nombre et capacité des véhicules",
                "depot_index": "Index du noeud dépôt dans la matrice",
                "capacity_constraints": "Capacité maximale par véhicule"
            },
            "pickup_delivery_pairs": {
                "pairs": "Relations (pickup_node, delivery_node)",
                "same_vehicle": "Même véhicule pour pickup et delivery",
                "precedence": "Pickup avant delivery"
            },
            "time_constraints": {
                "time_windows": "Créneaux horaires par noeud",
                "service_times": "Temps de service à chaque noeud",
                "max_duration": "Durée maximale de tournée"
            }
        }
    
    def analyze_current_data_coverage(self, optimization_data: Dict) -> Dict:
        """
        Analyse si nos données actuelles couvrent les besoins OR-Tools
        
        Args:
            optimization_data: Package de données actuelles
            
        Returns:
            Dict: Analyse détaillée avec gaps identifiés
        """
        logger.info("Analyzing OR-Tools data coverage")
        
        analysis = {
            "coverage_summary": {},
            "critical_gaps": [],
            "implementation_ready": False,
            "detailed_analysis": {}
        }
        
        # 1. NODES ANALYSIS
        nodes_analysis = self._analyze_nodes_coverage(optimization_data)
        analysis["detailed_analysis"]["nodes"] = nodes_analysis
        analysis["coverage_summary"]["nodes"] = nodes_analysis["status"]
        
        # 2. DISTANCE MATRIX ANALYSIS
        distance_analysis = self._analyze_distance_matrix_coverage(optimization_data)
        analysis["detailed_analysis"]["distance_matrix"] = distance_analysis
        analysis["coverage_summary"]["distance_matrix"] = distance_analysis["status"]
        
        # 3. VEHICLE CONSTRAINTS ANALYSIS
        vehicle_analysis = self._analyze_vehicle_constraints_coverage(optimization_data)
        analysis["detailed_analysis"]["vehicle_constraints"] = vehicle_analysis
        analysis["coverage_summary"]["vehicle_constraints"] = vehicle_analysis["status"]
        
        # 4. PICKUP/DELIVERY ANALYSIS
        pickup_delivery_analysis = self._analyze_pickup_delivery_coverage(optimization_data)
        analysis["detailed_analysis"]["pickup_delivery"] = pickup_delivery_analysis
        analysis["coverage_summary"]["pickup_delivery"] = pickup_delivery_analysis["status"]
        
        # 5. TIME CONSTRAINTS ANALYSIS
        time_analysis = self._analyze_time_constraints_coverage(optimization_data)
        analysis["detailed_analysis"]["time_constraints"] = time_analysis
        analysis["coverage_summary"]["time_constraints"] = time_analysis["status"]
        
        # Compiler les gaps critiques
        for component, details in analysis["detailed_analysis"].items():
            if details["status"] == "MISSING" or details["status"] == "INCOMPLETE":
                analysis["critical_gaps"].extend(details.get("missing_elements", []))
        
        # Déterminer si prêt pour implémentation
        all_critical = [
            nodes_analysis["status"] in ["COMPLETE", "PARTIAL"],
            distance_analysis["status"] in ["COMPLETE", "PARTIAL"],
            pickup_delivery_analysis["status"] in ["COMPLETE", "PARTIAL"]
        ]
        analysis["implementation_ready"] = all(all_critical)
        
        return analysis
    
    def _analyze_nodes_coverage(self, data: Dict) -> Dict:
        """Analyse la couverture des noeuds OR-Tools"""
        stops = data.get("stops", [])
        
        # Identifier les types de noeuds
        depot_nodes = [s for s in stops if s.get("stop_type", "").startswith("depot")]
        lab_nodes = [s for s in stops if s.get("stop_type", "").startswith("lab")]
        client_nodes = [s for s in stops if s.get("stop_type") == "client"]
        
        # Vérifier les coordonnées GPS
        nodes_with_coords = [s for s in stops if s.get("latitude") and s.get("longitude")]
        
        analysis = {
            "total_nodes": len(stops),
            "depot_nodes": len(depot_nodes),
            "lab_nodes": len(lab_nodes),
            "client_nodes": len(client_nodes),
            "nodes_with_gps": len(nodes_with_coords),
            "gps_coverage": len(nodes_with_coords) / len(stops) if stops else 0,
            "missing_elements": []
        }
        
        # Déterminer le statut
        if analysis["gps_coverage"] == 1.0 and analysis["total_nodes"] > 0:
            analysis["status"] = "COMPLETE"
            analysis["message"] = "✅ Tous les noeuds ont des coordonnées GPS"
        elif analysis["gps_coverage"] > 0.8:
            analysis["status"] = "PARTIAL"
            analysis["message"] = f"⚠️ {analysis['gps_coverage']:.1%} des noeuds ont des GPS"
            analysis["missing_elements"].append(f"{analysis['total_nodes'] - analysis['nodes_with_gps']} noeuds sans GPS")
        else:
            analysis["status"] = "MISSING"
            analysis["message"] = "❌ Données GPS insuffisantes"
            analysis["missing_elements"].append("Coordonnées GPS manquantes pour la majorité des noeuds")
        
        return analysis
    
    def _analyze_distance_matrix_coverage(self, data: Dict) -> Dict:
        """Analyse la couverture de la matrice de distances"""
        stops = data.get("stops", [])
        
        analysis = {
            "nodes_count": len(stops),
            "matrix_size_needed": len(stops) * len(stops),
            "osrm_available": True,  # Supposé disponible dans votre architecture
            "google_directions_available": True,  # Vous avez la clé API
            "missing_elements": []
        }
        
        # OR-Tools a besoin d'une matrice de distances complète
        if analysis["nodes_count"] == 0:
            analysis["status"] = "MISSING"
            analysis["message"] = "❌ Pas de noeuds pour créer la matrice"
            analysis["missing_elements"].append("Noeuds de base manquants")
        elif analysis["nodes_count"] > 1:
            analysis["status"] = "READY_TO_GENERATE"
            analysis["message"] = f"🔄 Matrice {analysis['nodes_count']}x{analysis['nodes_count']} à générer avec OSRM/Google"
            analysis["implementation_needed"] = "Service de génération de matrice de distances"
        else:
            analysis["status"] = "INCOMPLETE"
            analysis["message"] = "⚠️ Un seul noeud, pas de matrice possible"
            analysis["missing_elements"].append("Au moins 2 noeuds requis")
        
        return analysis
    
    def _analyze_vehicle_constraints_coverage(self, data: Dict) -> Dict:
        """Analyse les contraintes véhicules"""
        route = data.get("route", {})
        constraints = data.get("constraints", {})
        
        analysis = {
            "vehicle_count": 1,  # Une route = un véhicule
            "capacity_defined": constraints.get("vehicle_capacity") is not None,
            "depot_identified": False,
            "missing_elements": []
        }
        
        # Identifier le dépôt
        stops = data.get("stops", [])
        depot_stops = [s for s in stops if s.get("stop_type", "").startswith("depot")]
        
        if depot_stops:
            analysis["depot_identified"] = True
            analysis["depot_count"] = len(depot_stops)
        
        # Déterminer le statut
        if analysis["capacity_defined"] and analysis["depot_identified"]:
            analysis["status"] = "COMPLETE"
            analysis["message"] = "✅ Véhicule et dépôt configurés"
        elif analysis["depot_identified"]:
            analysis["status"] = "PARTIAL" 
            analysis["message"] = "⚠️ Dépôt identifié, capacité à définir"
            analysis["missing_elements"].append("Capacité véhicule précise")
        else:
            analysis["status"] = "MISSING"
            analysis["message"] = "❌ Dépôt non identifié"
            analysis["missing_elements"].append("Noeud dépôt de départ/retour")
        
        return analysis
    
    def _analyze_pickup_delivery_coverage(self, data: Dict) -> Dict:
        """Analyse des paires pickup/delivery - CRITIQUE pour votre métier"""
        shipments = data.get("shipments", [])
        
        analysis = {
            "total_shipments": len(shipments),
            "complete_pairs": 0,
            "incomplete_pairs": 0,
            "missing_elements": []
        }
        
        # Vérifier chaque shipment
        for shipment in shipments:
            pickup_id = shipment.get("pickup_stop_id")
            delivery_id = shipment.get("delivery_stop_id")
            
            if pickup_id and delivery_id:
                analysis["complete_pairs"] += 1
            else:
                analysis["incomplete_pairs"] += 1
        
        analysis["completion_rate"] = (analysis["complete_pairs"] / analysis["total_shipments"]) if analysis["total_shipments"] else 0
        
        # Déterminer le statut
        if analysis["completion_rate"] == 1.0 and analysis["total_shipments"] > 0:
            analysis["status"] = "COMPLETE"
            analysis["message"] = f"✅ {analysis['complete_pairs']} paires pickup/delivery complètes"
        elif analysis["completion_rate"] > 0.8:
            analysis["status"] = "PARTIAL"
            analysis["message"] = f"⚠️ {analysis['completion_rate']:.1%} des paires complètes"
            analysis["missing_elements"].append(f"{analysis['incomplete_pairs']} shipments avec références manquantes")
        else:
            analysis["status"] = "MISSING"
            analysis["message"] = "❌ Relations pickup/delivery insuffisantes"
            analysis["missing_elements"].append("Références pickup_stop_id/delivery_stop_id manquantes")
        
        return analysis
    
    def _analyze_time_constraints_coverage(self, data: Dict) -> Dict:
        """Analyse des contraintes temporelles"""
        constraints = data.get("constraints", {})
        
        analysis = {
            "time_windows_defined": bool(constraints.get("time_windows")),
            "service_times_defined": bool(constraints.get("service_times")),
            "geographic_restrictions": len(constraints.get("geographic_restrictions", [])),
            "missing_elements": []
        }
        
        # Déterminer le statut
        if analysis["time_windows_defined"] and analysis["service_times_defined"]:
            analysis["status"] = "COMPLETE"
            analysis["message"] = "✅ Contraintes temporelles complètes"
            if analysis["geographic_restrictions"] > 0:
                analysis["message"] += f" + {analysis['geographic_restrictions']} restrictions géographiques"
        elif analysis["time_windows_defined"] or analysis["service_times_defined"]:
            analysis["status"] = "PARTIAL"
            analysis["message"] = "⚠️ Contraintes temporelles partielles"
            if not analysis["time_windows_defined"]:
                analysis["missing_elements"].append("Créneaux horaires (time_windows)")
            if not analysis["service_times_defined"]:
                analysis["missing_elements"].append("Temps de service par type de stop")
        else:
            analysis["status"] = "OPTIONAL"
            analysis["message"] = "📋 Contraintes temporelles optionnelles"
        
        return analysis
    
    def generate_implementation_roadmap(self, analysis: Dict) -> Dict:
        """Génère une roadmap d'implémentation basée sur l'analyse"""
        
        roadmap = {
            "immediate_tasks": [],
            "short_term_tasks": [],
            "optimization_tasks": [],
            "estimated_complexity": "MEDIUM"
        }
        
        # Tâches immédiates (critiques)
        for gap in analysis["critical_gaps"]:
            if "GPS" in gap or "pickup" in gap.lower() or "delivery" in gap.lower():
                roadmap["immediate_tasks"].append({
                    "task": f"Résoudre: {gap}",
                    "priority": "CRITICAL",
                    "estimated_time": "1-2 jours"
                })
        
        # Tâches court terme
        distance_status = analysis["coverage_summary"].get("distance_matrix")
        if distance_status == "READY_TO_GENERATE":
            roadmap["short_term_tasks"].append({
                "task": "Implémenter générateur de matrice de distances",
                "priority": "HIGH",
                "estimated_time": "2-3 jours",
                "dependencies": ["OSRM ou Google Directions API"]
            })
        
        # Tâches d'optimisation
        time_status = analysis["coverage_summary"].get("time_constraints")
        if time_status in ["PARTIAL", "OPTIONAL"]:
            roadmap["optimization_tasks"].append({
                "task": "Affiner les contraintes temporelles",
                "priority": "MEDIUM",
                "estimated_time": "1-2 jours"
            })
        
        # Estimer la complexité
        critical_count = len([t for t in roadmap["immediate_tasks"]])
        if critical_count == 0:
            roadmap["estimated_complexity"] = "LOW"
        elif critical_count <= 2:
            roadmap["estimated_complexity"] = "MEDIUM"
        else:
            roadmap["estimated_complexity"] = "HIGH"
        
        return roadmap