"""
Service de fusion des stops dupliqués après optimisation OR-Tools
Fusionne les stops consécutifs avec même location_id/coordonnées
"""

import structlog
from typing import Dict, List, Any, Tuple
from collections import defaultdict

logger = structlog.get_logger()


class RouteStopMerger:
    """
    Service de fusion des stops dupliqués dans une route optimisée
    
    OR-Tools utilise 1 nœud = 1 action, mais physiquement le chauffeur
    va au même endroit une seule fois pour faire toutes les actions.
    
    Logique de fusion :
    - Stops consécutifs (qui se suivent)
    - Même location_id ET même latitude/longitude
    - Clients: fusion en client_actions ["pickup", "delivery", "both"]  
    - Labs/Depot: fusion des actions similaires consécutives
    """
    
    def __init__(self):
        # Tolérance GPS pour considérer 2 coordonnées identiques (mètres)
        self.GPS_TOLERANCE_METERS = 10
        
    def merge_consecutive_client_stops(self, optimized_stops: List[Dict]) -> List[Dict]:
        """
        Fusionne les stops consécutifs selon les spécifications :
        - Lab pickup consécutifs du même labo → 1 stop
        - Lab dropoff consécutifs du même labo → 1 stop  
        - Clients consécutifs même location → 1 stop avec bon client_actions
        - Remapping des shipments vers les nouveaux stops
        
        Args:
            optimized_stops: Liste des stops optimisés
            
        Returns:
            List[Dict]: Stops fusionnés avec remapping
        """
        logger.info("Merging consecutive stops by specifications", stops_count=len(optimized_stops))
        
        if not optimized_stops:
            return []
        
        merged_stops = []
        i = 0
        
        while i < len(optimized_stops):
            current_stop = optimized_stops[i]
            consecutive_group = [current_stop]
            
            # Chercher les stops consécutifs à fusionner
            j = i + 1
            while j < len(optimized_stops):
                next_stop = optimized_stops[j]
                
                if self._should_merge_stops(current_stop, next_stop):
                    consecutive_group.append(next_stop)
                    j += 1
                else:
                    break
            
            # Fusionner le groupe ou garder le stop seul
            if len(consecutive_group) > 1:
                merged_stop = self._merge_stop_group(consecutive_group)
                merged_stops.append(merged_stop)
                logger.debug("Merged consecutive stops", 
                           location=current_stop.get("formatted_address", "")[:50],
                           stop_type=current_stop.get("stop_type"),
                           count=len(consecutive_group))
            else:
                merged_stops.append(current_stop)
            
            i = j
        
        # Recalculer les stop orders
        for idx, stop in enumerate(merged_stops):
            stop["final_stop_order"] = idx + 1
        
        logger.info("Consecutive stops merging completed", 
                   original_count=len(optimized_stops),
                   merged_count=len(merged_stops))
        
        return merged_stops
    
    def _should_merge_stops(self, stop1: Dict, stop2: Dict) -> bool:
        """
        Détermine si 2 stops consécutifs doivent être fusionnés
        
        Règles :
        - Lab pickup + lab pickup même labo même location → OUI
        - Lab dropoff + lab dropoff même labo même location → OUI  
        - Client + client même location → OUI
        - Autres cas → NON
        """
        # Même location_id requis
        if stop1.get("location_id") != stop2.get("location_id"):
            return False
        
        stop1_type = stop1.get("stop_type")
        stop2_type = stop2.get("stop_type")
        
        # Lab pickup consécutifs du même labo
        if (stop1_type == "lab_pickup" and stop2_type == "lab_pickup"):
            # Vérifier même laboratory_id si disponible
            lab1 = stop1.get("laboratory_id")
            lab2 = stop2.get("laboratory_id") 
            return lab1 and lab2 and lab1 == lab2
        
        # Lab dropoff consécutifs du même labo
        if (stop1_type == "lab_dropoff" and stop2_type == "lab_dropoff"):
            lab1 = stop1.get("laboratory_id")
            lab2 = stop2.get("laboratory_id")
            return lab1 and lab2 and lab1 == lab2
        
        # Clients consécutifs même location
        if (stop1_type == "client" and stop2_type == "client"):
            return True
        
        return False
    
    def _merge_stop_group(self, stop_group: List[Dict]) -> Dict:
        """
        Fusionne un groupe de stops consécutifs
        """
        first_stop = stop_group[0]
        stop_type = first_stop.get("stop_type")
        
        if stop_type == "client":
            return self._merge_client_group(stop_group)
        elif stop_type in ["lab_pickup", "lab_dropoff"]:
            return self._merge_lab_group(stop_group, stop_type)
        else:
            # Fallback - garder le premier stop
            logger.warning("Unknown stop type for merging", stop_type=stop_type)
            return first_stop
    
    def _merge_client_group(self, client_stops: List[Dict]) -> Dict:
        """
        Fusionne des stops clients - détermine le bon client_actions
        """
        first_stop = client_stops[0].copy()
        
        # Analyser les actions de tous les stops
        actions = set()
        all_shipment_refs = []
        all_stop_ids = []
        
        for stop in client_stops:
            # Récupérer l'action depuis client_actions ou shipment_ref
            client_action = stop.get("client_actions")
            if client_action:
                if client_action == "both":
                    actions.add("pickup")
                    actions.add("delivery")
                else:
                    actions.add(client_action)
            
            # Analyser shipment_ref pour détecter pickup/delivery (vérifier que ce n'est pas None)
            shipment_ref = stop.get("shipment_ref") or ""
            if shipment_ref and ("Récupération" in shipment_ref or "pickup" in shipment_ref.lower()):
                actions.add("pickup")
            elif shipment_ref and ("Livraison" in shipment_ref or "delivery" in shipment_ref.lower()):
                actions.add("delivery")
            
            if shipment_ref:
                all_shipment_refs.append(shipment_ref)
            
            all_stop_ids.append(stop["id"])
        
        # Déterminer client_actions final
        if "pickup" in actions and "delivery" in actions:
            final_client_actions = "both"
        elif "pickup" in actions:
            final_client_actions = "pickup"
        elif "delivery" in actions:
            final_client_actions = "delivery"
        else:
            final_client_actions = "delivery"  # Défaut
        
        # Mettre à jour le stop fusionné
        first_stop.update({
            "client_actions": final_client_actions,
            "merged_shipment_refs": all_shipment_refs,
            "merged_stop_ids": all_stop_ids,
            "merged_from_count": len(client_stops)
        })
        
        logger.debug("Client stops merged",
                   client_actions=final_client_actions,
                   merged_count=len(client_stops),
                   location=first_stop.get("formatted_address", "")[:50])
        
        return first_stop
    
    def _merge_lab_group(self, lab_stops: List[Dict], stop_type: str) -> Dict:
        """
        Fusionne des stops lab (pickup ou dropoff) du même laboratoire
        """
        first_stop = lab_stops[0].copy()
        
        all_shipment_refs = []
        all_stop_ids = []
        
        for stop in lab_stops:
            shipment_ref = stop.get("shipment_ref")
            if shipment_ref:
                all_shipment_refs.append(shipment_ref)
            
            all_stop_ids.append(stop["id"])
        
        # Mettre à jour le stop fusionné
        first_stop.update({
            "merged_shipment_refs": all_shipment_refs,
            "merged_stop_ids": all_stop_ids,
            "merged_from_count": len(lab_stops)
        })
        
        logger.debug("Lab stops merged",
                   stop_type=stop_type,
                   laboratory_id=first_stop.get("laboratory_id"),
                   merged_count=len(lab_stops))
        
        return first_stop
    
    def merge_consecutive_duplicate_stops(self, optimized_stops: List[Dict]) -> Dict:
        """
        Fusionne les stops dupliqués consécutifs d'une route optimisée
        
        Args:
            optimized_stops: Liste des stops optimisés par OR-Tools
            
        Returns:
            Dict: Résultat avec stops fusionnés et métadonnées
        """
        logger.info("Starting consecutive duplicate stops merging", 
                   original_stops=len(optimized_stops))
        
        if not optimized_stops:
            return {
                "merged_stops": [],
                "merge_summary": {
                    "original_stops": 0,
                    "merged_stops": 0,
                    "duplicates_merged": 0,
                    "merge_groups": []
                }
            }
        
        # 1. Analyser les duplicata consécutifs
        duplicate_groups = self._identify_consecutive_duplicates(optimized_stops)
        
        # 2. Fusionner les groupes de duplicata
        merged_stops = self._merge_duplicate_groups(optimized_stops, duplicate_groups)
        
        # 3. Recalculer les stop_order
        final_stops = self._recalculate_stop_orders(merged_stops)
        
        # 4. Créer le résumé
        merge_summary = {
            "original_stops": len(optimized_stops),
            "merged_stops": len(final_stops),
            "duplicates_merged": len(optimized_stops) - len(final_stops),
            "merge_groups": len(duplicate_groups),
            "merge_details": duplicate_groups
        }
        
        logger.info("Consecutive duplicate stops merging completed",
                   original_stops=merge_summary["original_stops"],
                   merged_stops=merge_summary["merged_stops"],
                   duplicates_merged=merge_summary["duplicates_merged"],
                   merge_groups=merge_summary["merge_groups"])
        
        return {
            "merged_stops": final_stops,
            "merge_summary": merge_summary
        }
    
    def _identify_consecutive_duplicates(self, stops: List[Dict]) -> List[Dict]:
        """
        Identifie les groupes de stops consécutifs dupliqués
        
        Args:
            stops: Liste des stops optimisés
            
        Returns:
            List[Dict]: Groupes de duplicata avec indices
        """
        logger.info("Identifying consecutive duplicate groups")
        
        duplicate_groups = []
        current_group = None
        
        for i in range(len(stops)):
            stop = stops[i]
            
            # Vérifier si ce stop fait partie d'un groupe consécutif
            if i > 0:
                prev_stop = stops[i-1]
                
                # Critères de fusion : même location_id ET coordonnées proches
                is_duplicate = self._are_stops_duplicate(prev_stop, stop)
                
                if is_duplicate:
                    # Démarrer ou continuer un groupe
                    if current_group is None:
                        current_group = {
                            "location_id": stop["location_id"],
                            "coordinates": [stop["latitude"], stop["longitude"]],
                            "formatted_address": stop["formatted_address"],
                            "indices": [i-1, i],  # Inclure le stop précédent
                            "stop_types": [prev_stop["stop_type"], stop["stop_type"]],
                            "stop_ids": [prev_stop["id"], stop["id"]]
                        }
                    else:
                        # Continuer le groupe existant
                        current_group["indices"].append(i)
                        current_group["stop_types"].append(stop["stop_type"])
                        current_group["stop_ids"].append(stop["id"])
                else:
                    # Fin du groupe (si il y en avait un)
                    if current_group is not None:
                        duplicate_groups.append(current_group)
                        current_group = None
            
        # Ajouter le dernier groupe s'il existe
        if current_group is not None:
            duplicate_groups.append(current_group)
        
        logger.info("Consecutive duplicate groups identified",
                   groups_count=len(duplicate_groups),
                   details=[{
                       "location": group["formatted_address"][:50],
                       "indices": group["indices"],
                       "types": group["stop_types"]
                   } for group in duplicate_groups])
        
        return duplicate_groups
    
    def _are_stops_duplicate(self, stop1: Dict, stop2: Dict) -> bool:
        """
        Vérifie si 2 stops sont dupliqués (même location + coordonnées)
        
        Args:
            stop1: Premier stop
            stop2: Deuxième stop
            
        Returns:
            bool: True si les stops sont dupliqués
        """
        # 1. Même location_id (si disponible)
        location_match = (
            stop1.get("location_id") is not None and
            stop2.get("location_id") is not None and
            stop1["location_id"] == stop2["location_id"]
        )
        
        # 2. Coordonnées proches (tolérance GPS)
        coords_match = self._are_coordinates_close(
            stop1["latitude"], stop1["longitude"],
            stop2["latitude"], stop2["longitude"]
        )
        
        # Les 2 critères doivent être respectés
        return location_match and coords_match
    
    def _are_coordinates_close(self, lat1: float, lon1: float, lat2: float, lon2: float) -> bool:
        """
        Vérifie si 2 coordonnées sont proches (tolérance GPS)
        
        Args:
            lat1, lon1: Première coordonnée
            lat2, lon2: Deuxième coordonnée
            
        Returns:
            bool: True si les coordonnées sont proches
        """
        # Distance euclidienne approximative (suffisante pour 10m)
        lat_diff = abs(lat1 - lat2)
        lon_diff = abs(lon1 - lon2)
        
        # 1 degré ≈ 111km, donc 10m ≈ 0.00009 degré
        tolerance_degrees = 0.0001
        
        return lat_diff < tolerance_degrees and lon_diff < tolerance_degrees
    
    def _merge_duplicate_groups(self, stops: List[Dict], duplicate_groups: List[Dict]) -> List[Dict]:
        """
        Fusionne les groupes de stops dupliqués
        
        Args:
            stops: Liste originale des stops
            duplicate_groups: Groupes de duplicata identifiés
            
        Returns:
            List[Dict]: Stops avec duplicata fusionnés
        """
        logger.info("Merging duplicate groups", groups_count=len(duplicate_groups))
        
        # Marquer les indices à ignorer (stops fusionnés)
        indices_to_skip = set()
        merged_stops = []
        
        for group in duplicate_groups:
            # Récupérer tous les stops du groupe
            group_stops = [stops[i] for i in group["indices"]]
            
            # Fusionner le groupe
            merged_stop = self._merge_group_stops(group_stops, group)
            
            # Ajouter le stop fusionné à la position du premier stop du groupe
            first_index = group["indices"][0]
            
            # Marquer les autres indices comme à ignorer
            for idx in group["indices"][1:]:
                indices_to_skip.add(idx)
            
            # Remplacer le premier stop par le stop fusionné
            group["merged_stop"] = merged_stop
            group["first_index"] = first_index
        
        # Reconstruire la liste avec stops fusionnés
        for i, stop in enumerate(stops):
            if i in indices_to_skip:
                continue  # Ignorer les stops fusionnés
            
            # Vérifier si ce stop fait partie d'un groupe (premier stop)
            merged_stop = None
            for group in duplicate_groups:
                if group["first_index"] == i:
                    merged_stop = group["merged_stop"]
                    break
            
            if merged_stop:
                merged_stops.append(merged_stop)
            else:
                merged_stops.append(stop)
        
        logger.info("Duplicate groups merged successfully",
                   original_count=len(stops),
                   merged_count=len(merged_stops))
        
        return merged_stops
    
    def _merge_group_stops(self, group_stops: List[Dict], group_info: Dict) -> Dict:
        """
        Fusionne un groupe de stops en un seul stop
        
        Args:
            group_stops: Stops du groupe à fusionner
            group_info: Informations du groupe
            
        Returns:
            Dict: Stop fusionné
        """
        first_stop = group_stops[0]
        stop_types = [stop["stop_type"] for stop in group_stops]
        
        logger.debug("Merging group stops", 
                    location=first_stop["formatted_address"][:50],
                    stop_types=stop_types,
                    stops_count=len(group_stops))
        
        # Déterminer le type de fusion selon les stop_types
        if all(st == "client" for st in stop_types):
            # Fusion de clients : analyser les actions
            merged_stop = self._merge_client_stops(group_stops, group_info)
        elif all(st == "lab_pickup" for st in stop_types):
            # Fusion de lab pickups
            merged_stop = self._merge_lab_stops(group_stops, "lab_pickup")
        elif all(st == "lab_dropoff" for st in stop_types):
            # Fusion de lab dropoffs
            merged_stop = self._merge_lab_stops(group_stops, "lab_dropoff")
        elif all(st == "depot_dropoff" for st in stop_types):
            # Fusion de depot dropoffs
            merged_stop = self._merge_depot_stops(group_stops)
        else:
            # Types mixtes : fusion générale
            logger.warning("Mixed stop types in group", stop_types=stop_types)
            merged_stop = self._merge_mixed_stops(group_stops)
        
        return merged_stop
    
    def _merge_client_stops(self, client_stops: List[Dict], group_info: Dict) -> Dict:
        """
        Fusionne des stops clients en analysant les actions (pickup/delivery)
        
        Args:
            client_stops: Stops clients à fusionner
            group_info: Informations du groupe
            
        Returns:
            Dict: Stop client fusionné avec client_actions
        """
        first_stop = client_stops[0]
        
        # Analyser les actions via shipment_action ou shipment_ref
        actions = set()
        shipment_refs = []
        
        for stop in client_stops:
            # Récupérer l'action du shipment (si disponible)
            action = stop.get("shipment_action")
            if action:
                actions.add(action)
            
            # Récupérer shipment_ref
            ref = stop.get("shipment_ref")
            if ref:
                shipment_refs.append(ref)
        
        # Déterminer client_actions
        if "pickup" in actions and "delivery" in actions:
            client_actions = "both"
        elif "pickup" in actions:
            client_actions = "pickup"
        elif "delivery" in actions:
            client_actions = "delivery"
        else:
            client_actions = "delivery"  # Défaut pour clients
        
        # Créer le stop fusionné
        merged_stop = first_stop.copy()
        merged_stop.update({
            "client_actions": client_actions,
            "merged_shipment_refs": shipment_refs,
            "merged_stop_ids": [stop["id"] for stop in client_stops],
            "merged_from_count": len(client_stops),
            "merge_type": "client"
        })
        
        logger.debug("Client stops merged",
                    client_actions=client_actions,
                    shipment_refs=len(shipment_refs),
                    merged_count=len(client_stops))
        
        return merged_stop
    
    def _merge_lab_stops(self, lab_stops: List[Dict], stop_type: str) -> Dict:
        """
        Fusionne des stops lab (pickup ou dropoff)
        
        Args:
            lab_stops: Stops lab à fusionner
            stop_type: "lab_pickup" ou "lab_dropoff"
            
        Returns:
            Dict: Stop lab fusionné
        """
        first_stop = lab_stops[0]
        shipment_refs = []
        
        for stop in lab_stops:
            ref = stop.get("shipment_ref")
            if ref:
                shipment_refs.append(ref)
        
        merged_stop = first_stop.copy()
        merged_stop.update({
            "merged_shipment_refs": shipment_refs,
            "merged_stop_ids": [stop["id"] for stop in lab_stops],
            "merged_from_count": len(lab_stops),
            "merge_type": stop_type
        })
        
        logger.debug("Lab stops merged",
                    stop_type=stop_type,
                    merged_count=len(lab_stops))
        
        return merged_stop
    
    def _merge_depot_stops(self, depot_stops: List[Dict]) -> Dict:
        """
        Fusionne des stops depot dropoff
        
        Args:
            depot_stops: Stops depot à fusionner
            
        Returns:
            Dict: Stop depot fusionné
        """
        first_stop = depot_stops[0]
        shipment_refs = []
        
        for stop in depot_stops:
            ref = stop.get("shipment_ref")
            if ref:
                shipment_refs.append(ref)
        
        merged_stop = first_stop.copy()
        merged_stop.update({
            "merged_shipment_refs": shipment_refs,
            "merged_stop_ids": [stop["id"] for stop in depot_stops],
            "merged_from_count": len(depot_stops),
            "merge_type": "depot_dropoff"
        })
        
        logger.debug("Depot stops merged", merged_count=len(depot_stops))
        
        return merged_stop
    
    def _merge_mixed_stops(self, mixed_stops: List[Dict]) -> Dict:
        """
        Fusionne des stops de types mixtes (fallback)
        
        Args:
            mixed_stops: Stops mixtes à fusionner
            
        Returns:
            Dict: Stop fusionné (générique)
        """
        first_stop = mixed_stops[0]
        shipment_refs = []
        stop_types = [stop["stop_type"] for stop in mixed_stops]
        
        for stop in mixed_stops:
            ref = stop.get("shipment_ref")
            if ref:
                shipment_refs.append(ref)
        
        merged_stop = first_stop.copy()
        merged_stop.update({
            "merged_shipment_refs": shipment_refs,
            "merged_stop_ids": [stop["id"] for stop in mixed_stops],
            "merged_stop_types": stop_types,
            "merged_from_count": len(mixed_stops),
            "merge_type": "mixed"
        })
        
        logger.warning("Mixed stops merged (fallback)",
                      stop_types=stop_types,
                      merged_count=len(mixed_stops))
        
        return merged_stop
    
    def _recalculate_stop_orders(self, merged_stops: List[Dict]) -> List[Dict]:
        """
        Recalcule les stop_order après fusion (1, 2, 3, ...)
        
        Args:
            merged_stops: Stops fusionnés
            
        Returns:
            List[Dict]: Stops avec stop_order recalculés
        """
        for i, stop in enumerate(merged_stops):
            stop["stop_order"] = i + 1
            stop["final_stop_order"] = i + 1
        
        logger.info("Stop orders recalculated", total_stops=len(merged_stops))
        
        return merged_stops


class RouteStopMergerError(Exception):
    """Exception levée lors d'erreurs de fusion des stops"""
    pass