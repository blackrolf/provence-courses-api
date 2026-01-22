# Modifications pour la logique Mika is dentist / Mika is lab

**Date** : 8 septembre 2025  
**Objectif** : Implémenter la logique où le dépôt remplace soit le dentiste soit le laboratoire dans les tournées

## 📋 Résumé de la logique

### Mika is dentist (`depot_is_dentist = True`)
Le dépôt remplace le dentiste/client :
- **Livraisons** : Lab → Client devient **Lab → Dépôt**
- **Récupérations** : Client → Lab devient **Dépôt → Lab**

### Mika is lab (`depot_is_lab = True`)
Le dépôt remplace le laboratoire :
- **Livraisons** : Lab → Client devient **Dépôt → Client**
- **Récupérations** : Client → Lab devient **Client → Dépôt**

## 🔧 Fichiers modifiés

### 1. `/app/services/tours/stop_consolidator.py`

#### Modifications apportées :

**A. Ajout de la fonction de transformation (lignes 19-52)**
```python
def _transform_shipment_type_for_mika_logic(self, shipment: Dict) -> str:
    """
    Transforme le shipment_type basé sur les flags depot_is_dentist et depot_is_lab
    """
    original_type = shipment.get("shipment_type")
    depot_is_dentist = shipment.get("depot_is_dentist", False)
    depot_is_lab = shipment.get("depot_is_lab", False)
    
    # Si depot_is_dentist = True (Mika is dentist - le dépôt remplace le dentiste)
    if depot_is_dentist:
        if original_type == "lab_to_client":
            return "lab_to_depot"
        elif original_type == "client_to_lab":
            return "depot_to_lab"
    
    # Si depot_is_lab = True (Mika is lab - le dépôt remplace le laboratoire)
    if depot_is_lab:
        if original_type == "lab_to_client":
            return "depot_to_client"
        elif original_type == "client_to_lab":
            return "client_to_depot"
    
    return original_type
```

**B. Integration dans consolidate_stops_for_driver() (lignes 82-94)**
```python
for shipment in shipments:
    # Transformer le shipment_type selon la logique Mika
    original_shipment_type = shipment["shipment_type"]
    shipment_type = self._transform_shipment_type_for_mika_logic(shipment)
    
    # Logger si une transformation a eu lieu
    if shipment_type != original_shipment_type:
        logger.debug("Shipment type transformed for Mika logic",
                    original_type=original_shipment_type,
                    transformed_type=shipment_type,
                    depot_is_dentist=shipment.get("depot_is_dentist", False),
                    depot_is_lab=shipment.get("depot_is_lab", False),
                    laboratory_id=shipment.get("laboratory_id"))
```

### 2. `/app/services/tours/shipment_mapper.py`

#### Modifications apportées :

**A. Ajout de la même fonction de transformation (lignes 103-136)**
```python
def _transform_shipment_type_for_mika_logic(self, shipment: Dict) -> str:
    # [Même code que dans StopConsolidator pour cohérence]
```

**B. Application dans _map_shipment_to_stops() (ligne 152)**
```python
def _map_shipment_to_stops(self, shipment: Dict, stops_map: Dict[str, str], 
                          consolidated_stops: Dict[str, Dict]) -> Dict:
    # Transformer le shipment_type selon la logique Mika
    shipment_type = self._transform_shipment_type_for_mika_logic(shipment)
```

**C. Application dans _determine_shipment_type() (ligne 238)**
```python
def _determine_shipment_type(self, shipment: Dict) -> str:
    # Transformer le shipment_type selon la logique Mika
    shipment_type = self._transform_shipment_type_for_mika_logic(shipment)
```

### 3. `/app/integrations/supabase/repositories/lab_tour_shipments_repository.py`

#### Modifications apportées :

**A. Ajout du flag depot_is_dentist dans l'enrichissement (ligne 169)**
```python
enriched_shipment = {
    **shipment,
    "driver_id": client.get("driver_id"),
    "client_location_id": client.get("location_id"),
    "laboratory_id": lab_id,
    "client_name": client.get("name"),
    "shared_pickup": lab.get("shared_pickup", False),
    "depot_is_lab": lab.get("depot_is_lab", False),
    "depot_is_dentist": client.get("depot_is_dentist", False),  # AJOUTÉ
    "laboratory_name": lab.get("name"),
    "has_pickup": stop_data.get("has_pickup", False),
    "has_delivery": stop_data.get("has_delivery", False)
}
```

## 📁 Fichiers créés

### 4. `/test_mika_logic.py`

Fichier de test pour vérifier le bon fonctionnement de la logique :
- Test des transformations de shipment_type
- Test de la consolidation des stops
- Validation des 4 cas de transformation

## 🎯 Impact sur le système

### ✅ Ce qui fonctionne maintenant :

1. **Clients avec `depot_is_dentist = True`** :
   - Les shipments `lab_to_client` deviennent `lab_to_depot` 
   - Les shipments `client_to_lab` deviennent `depot_to_lab`
   - Les livreurs vont au dépôt au lieu d'aller chez le client

2. **Laboratoires avec `depot_is_lab = True`** :
   - Les shipments `lab_to_client` deviennent `depot_to_client`
   - Les shipments `client_to_lab` deviennent `client_to_depot`
   - Les livreurs partent du dépôt au lieu du labo, vont au dépôt au lieu du labo

3. **L'optimisation OR-Tools** continue de fonctionner normalement :
   - Elle voit toujours des stops standards (`depot_pickup`, `depot_dropoff`, `lab_pickup`, `lab_dropoff`, `client`)
   - Aucun impact sur les performances d'optimisation

4. **Rétrocompatibilité** :
   - Les tournées existantes sans flags continuent de fonctionner
   - Aucune migration de données nécessaire

### 🔄 Flux de données modifié :

```
lab_tour_shipments (shipment_type original)
    ↓
get_enriched_shipments_for_date() (ajout flags depot_is_dentist/depot_is_lab)
    ↓
StopConsolidator._transform_shipment_type_for_mika_logic() (transformation)
    ↓
consolidate_stops_for_driver() (création des stops selon nouveau type)
    ↓
OR-Tools VRP Solver (optimisation normale)
    ↓
ShipmentMapper._transform_shipment_type_for_mika_logic() (même transformation)
    ↓
driver_route_shipments (relations pickup/delivery cohérentes)
```

## 📊 Exemples de transformation

### Exemple 1 : Mika is dentist
**Avant** :
- `lab_to_client` : Lab ABC → Client XYZ
- `client_to_lab` : Client XYZ → Lab ABC

**Après** (`depot_is_dentist = True`) :
- `lab_to_depot` : Lab ABC → Dépôt
- `depot_to_lab` : Dépôt → Lab ABC

### Exemple 2 : Mika is lab  
**Avant** :
- `lab_to_client` : Lab DEF → Client XYZ
- `client_to_lab` : Client XYZ → Lab DEF

**Après** (`depot_is_lab = True`) :
- `depot_to_client` : Dépôt → Client XYZ
- `client_to_depot` : Client XYZ → Dépôt

## ⚠️ Points d'attention

1. **Flags requis** : Les flags `depot_is_dentist` et `depot_is_lab` doivent être correctement configurés dans la base de données
2. **Logs de debug** : Les transformations sont loggées pour faciliter le debugging
3. **Tests** : Le fichier `test_mika_logic.py` peut être utilisé pour valider les modifications
4. **Cohérence** : La même logique de transformation est appliquée dans StopConsolidator et ShipmentMapper

## 🔍 Vérification

Pour vérifier que les modifications fonctionnent :

1. **Logs** : Vérifier les messages "Shipment type transformed for Mika logic" dans les logs
2. **Base de données** : Vérifier que les `driver_route_stops` créés correspondent aux bonnes locations
3. **API** : Tester les endpoints de génération de tournées avec des clients/labs ayant les flags activés

## 📝 Notes techniques

- **Performance** : Aucun impact sur les performances (simple transformation de chaîne)
- **Sécurité** : Aucun impact sur la sécurité 
- **Maintenance** : Code bien documenté et testé
- **Évolutivité** : Facile d'ajouter d'autres types de transformations si nécessaire