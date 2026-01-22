# 📋 Spécification technique des réponses API - Late Stops

## Structure détaillée des réponses

### 🟢 Réponse de succès complète

```typescript
interface LateStopSuccessResponse {
  status: "success";
  message: string;
  late_stop_request_id: string;
  processing_time: string;
  
  placement_result: {
    driver_route_id: string;
    inserted_stops: InsertedStop[];
    placement_details: PlacementDetail[];
    created_shipments: CreatedShipment[];
  };
  
  tour_updates: {
    total_stops_before: number;
    total_stops_after: number;
    stops_reordered: number;
    sequence_updated: boolean;
  };
}

interface InsertedStop {
  id: string;                    // UUID du nouveau stop créé
  stop_type: StopType;           // Type de stop créé
  location_id: string;           // UUID de la location
  stop_order: number;            // Position finale dans la séquence
  is_late_stop: true;            // Toujours true pour les late stops
  client_actions?: ClientAction; // "pickup", "delivery", "both" ou null
  created_at: string;            // ISO timestamp
}

interface CreatedShipment {
  id: string;                    // UUID du shipment créé
  shipment_ref: string;          // Référence générée (ex: "Late-550e8400")
  shipment_type: string;         // Type déterminé par la logique métier
  is_late_shipment: true;        // Toujours true pour les late shipments
  pickup_stop_id: string | null; // UUID du stop de pickup
  delivery_stop_id: string | null; // UUID du stop de delivery
}

type StopType = "client_pickup" | "client_delivery" | "lab_dropoff" | "depot_dropoff";
type ClientAction = "pickup" | "delivery" | "both";
```

---

## 📊 Exemples concrets par cas d'usage

### CAS 1: Ramassage uniquement (has_pickup = true, has_delivery = false)

```json
{
  "status": "success",
  "message": "Arrêt de dernière minute traité avec succès",
  "late_stop_request_id": "550e8400-e29b-41d4-a716-446655440000",
  "processing_time": "1.8s",
  
  "placement_result": {
    "driver_route_id": "75085272-84d1-4c5f-af45-123456789abc",
    "inserted_stops": [
      {
        "id": "new-stop-001",
        "stop_type": "client_pickup",
        "location_id": "loc-client-urgent",
        "stop_order": 4,
        "is_late_stop": true,
        "client_actions": "pickup",
        "created_at": "2025-09-10T14:30:00Z"
      }
    ],
    "placement_details": [
      {
        "inserted_after_stop_id": "stop-003",
        "inserted_before_stop_id": "stop-004",
        "insertion_reason": "Proximité géographique - milieu de tournée"
      }
    ],
    "created_shipments": [
      {
        "id": "shipment-new-001",
        "shipment_ref": "Late-550e8400",
        "shipment_type": "client_pickup",
        "is_late_shipment": true,
        "pickup_stop_id": "new-stop-001",
        "delivery_stop_id": "existing-lab-dropoff-id"
      }
    ]
  },
  
  "tour_updates": {
    "total_stops_before": 6,
    "total_stops_after": 7,
    "stops_reordered": 3,
    "sequence_updated": true
  }
}
```

### CAS 2: Livraison uniquement (has_pickup = false, has_delivery = true)

#### Sous-cas A: Lab dropoff n'existe pas encore

```json
{
  "placement_result": {
    "inserted_stops": [
      {
        "id": "new-lab-dropoff-001",
        "stop_type": "lab_dropoff",
        "location_id": "lab-location-id",
        "stop_order": 6,
        "is_late_stop": true,
        "client_actions": null
      }
    ],
    "created_shipments": [
      {
        "shipment_type": "client_to_lab",
        "pickup_stop_id": "existing-client-pickup-stop",
        "delivery_stop_id": "new-lab-dropoff-001"
      }
    ]
  },
  
  "tour_updates": {
    "total_stops_before": 5,
    "total_stops_after": 6,
    "stops_reordered": 1
  }
}
```

#### Sous-cas B: Lab dropoff existe déjà

```json
{
  "placement_result": {
    "inserted_stops": [],  // Aucun nouveau stop créé
    "created_shipments": [
      {
        "shipment_type": "client_to_lab",
        "pickup_stop_id": "existing-client-pickup-stop",
        "delivery_stop_id": "existing-lab-dropoff-id"  // Utilise l'existant
      }
    ]
  },
  
  "tour_updates": {
    "total_stops_before": 6,
    "total_stops_after": 6,  // Même nombre de stops
    "stops_reordered": 0     // Aucune réorganisation
  }
}
```

### CAS 3: Ramassage ET livraison (has_pickup = true, has_delivery = true)

```json
{
  "placement_result": {
    "inserted_stops": [
      {
        "id": "new-pickup-stop",
        "stop_type": "client_pickup",
        "stop_order": 4,
        "client_actions": "pickup"
      },
      {
        "id": "new-dropoff-stop",
        "stop_type": "lab_dropoff", 
        "stop_order": 8,
        "client_actions": null
      }
    ],
    "created_shipments": [
      {
        "shipment_type": "client_to_lab",
        "pickup_stop_id": "new-pickup-stop",
        "delivery_stop_id": "new-dropoff-stop"
      }
    ]
  },
  
  "tour_updates": {
    "total_stops_before": 6,
    "total_stops_after": 8,  // +2 stops
    "stops_reordered": 4
  }
}
```

### CAS 4: Client avec depot_is_lab = true

```json
{
  "placement_result": {
    "inserted_stops": [
      {
        "stop_type": "client_pickup"
      }
    ],
    "created_shipments": [
      {
        "shipment_type": "client_to_depot",  // Pas client_to_lab !
        "pickup_stop_id": "new-pickup-stop",
        "delivery_stop_id": "existing-depot-dropoff"
      }
    ]
  }
}
```

---

## 🔴 Réponses d'erreur détaillées

### Erreur 400 - Demande invalide

```json
{
  "status": "error",
  "message": "Demande déjà traitée (statut: approved)",
  "processing_time": "0.2s",
  "error_code": "INVALID_LATE_STOP_REQUEST",
  "late_stop_request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Autres messages possibles:**
- `"Demande de late stop non trouvée: {id}"`
- `"Aucune action (pickup/delivery) spécifiée dans la demande"`

### Erreur 404 - Ressource non trouvée

```json
{
  "status": "error",
  "message": "Aucune tournée driver active trouvée pour la date 2025-09-10",
  "processing_time": "0.5s",
  "error_code": "DRIVER_ROUTE_NOT_FOUND"
}
```

### Erreur 500 - Erreur serveur

```json
{
  "status": "error",
  "message": "Erreur lors du traitement de l'arrêt tardif: Database connection failed",
  "processing_time": "1.2s",
  "error_code": "LATE_STOP_PROCESSING_ERROR"
}
```

---

## 🎯 Champs importants pour le front-end

### Pour l'interface utilisateur

```javascript
// Résumé à afficher à l'admin
const summary = {
  success: response.status === "success",
  stopsAdded: response.placement_result?.inserted_stops?.length || 0,
  stopsReordered: response.tour_updates?.stops_reordered || 0,
  processingTime: response.processing_time,
  routeId: response.placement_result?.driver_route_id
};

// Pour mettre à jour la vue carte/planning
const placementInfo = response.placement_result.placement_details.map(detail => ({
  afterStopId: detail.inserted_after_stop_id,
  beforeStopId: detail.inserted_before_stop_id,
  reason: detail.insertion_reason
}));
```

### Pour la synchronisation des données

```javascript
// IDs des éléments créés (pour rafraîchissement ciblé)
const newElementIds = {
  stops: response.placement_result.inserted_stops.map(s => s.id),
  shipments: response.placement_result.created_shipments.map(s => s.id),
  routeId: response.placement_result.driver_route_id
};

// Validation côté front
const isValidResponse = (
  response.status === "success" &&
  response.placement_result.inserted_stops.length > 0 &&
  response.tour_updates.sequence_updated === true
);
```

---

## 🧪 Réponse de l'endpoint de test

```json
{
  "status": "simulation",
  "message": "Mode simulation - aucune modification en base",
  "test_parameters": {
    "mock_late_stop_id": "test-123",
    "simulate_placement": true
  },
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
```

---

## 📋 Checklist d'intégration front-end

### ✅ Vérifications obligatoires

1. **Validation de la réponse**
   ```javascript
   if (response.status !== "success") {
     handleError(response);
     return;
   }
   ```

2. **Extraction des données clés**
   ```javascript
   const { driver_route_id, inserted_stops } = response.placement_result;
   const { stops_reordered } = response.tour_updates;
   ```

3. **Mise à jour de l'interface**
   ```javascript
   await refreshDriverRoute(driver_route_id);
   showSuccessMessage(`${inserted_stops.length} stops ajoutés, ${stops_reordered} réorganisés`);
   ```

4. **Gestion des cas edge**
   - Vérifier si `inserted_stops` est vide (dropoff existant)
   - Valider que `stops_reordered >= 0`
   - S'assurer que `processing_time` est raisonnable (< 30s)

### 🔄 Flux de données recommandé

```
Front demande → API traite → Réponse complète → Refresh interface → Notification utilisateur
```

Cette spécification couvre-t-elle tous vos besoins ? Y a-t-il des aspects spécifiques que vous souhaitez que je détaille davantage ?