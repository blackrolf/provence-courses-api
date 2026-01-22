# 🚚 Guide d'intégration Front-End : Ajouts de dernière minute

## Vue d'ensemble

Ce document détaille comment intégrer l'API d'ajouts de dernière minute dans votre application front-end.

### Workflow côté front-end

```mermaid
graph TD
    A[Admin voit demande pending] --> B[Clic "Traiter"]
    B --> C[Appel API process late stop]
    C --> D[Affichage placement proposé]
    D --> E[Confirmation admin]
    E --> F[Tournée mise à jour]
```

---

## 🔧 ÉTAPE 1 : Endpoint principal

### URL
```
POST /tours/late-stops/{late_stop_request_id}/process
```

### Headers requis
```http
Content-Type: application/json
X-API-Key: votre-api-key
```

### Paramètres
- `late_stop_request_id` : UUID de la demande dans `lab_tour_late_stops`

---

## 📊 ÉTAPE 2 : Structure de réponse complète

### Réponse de succès (200)

```json
{
  "status": "success",
  "message": "Arrêt de dernière minute traité avec succès",
  "late_stop_request_id": "550e8400-e29b-41d4-a716-446655440000",
  "processing_time": "2.3s",
  
  "placement_result": {
    "driver_route_id": "route-abc-123",
    "inserted_stops": [
      {
        "id": "stop-new-001",
        "stop_type": "client_pickup",
        "location_id": "loc-456",
        "stop_order": 4,
        "is_late_stop": true,
        "client_actions": "pickup",
        "formatted_address": "123 Rue Example, Marseille"
      }
    ],
    "placement_details": {
      "insertion_points": [
        {
          "inserted_after_stop_id": "stop-003",
          "inserted_before_stop_id": "stop-004",
          "insertion_reason": "Proximité géographique"
        }
      ]
    },
    "created_shipments": [
      {
        "id": "shipment-new-001",
        "shipment_ref": "Late-550e8400",
        "shipment_type": "client_pickup",
        "is_late_shipment": true,
        "pickup_stop_id": "stop-new-001",
        "delivery_stop_id": "stop-lab-dropoff"
      }
    ]
  },
  
  "tour_updates": {
    "total_stops_before": 6,
    "total_stops_after": 7,
    "stops_reordered": 3,
    "sequence_updated": true,
    "affected_stop_ids": [
      "stop-004",
      "stop-005", 
      "stop-006"
    ]
  }
}
```

### Réponse d'erreur (400 - Erreur métier)

```json
{
  "status": "error",
  "message": "Demande déjà traitée (statut: approved)",
  "processing_time": "0.1s",
  "error_code": "INVALID_LATE_STOP_REQUEST",
  "late_stop_request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Réponse d'erreur (500 - Erreur serveur)

```json
{
  "status": "error",
  "message": "Erreur lors du traitement de l'arrêt tardif: Database connection failed",
  "processing_time": "1.2s",
  "error_code": "LATE_STOP_PROCESSING_ERROR"
}
```

---

## 🚀 ÉTAPE 3 : Exemple d'implémentation JavaScript

### Fonction de base

```javascript
async function processLateStop(lateStopRequestId) {
    try {
        const response = await fetch(
            `/api/v1/tours/late-stops/${lateStopRequestId}/process`,
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-API-Key': process.env.API_KEY
                }
            }
        );

        const result = await response.json();
        
        if (result.status === 'success') {
            return handleSuccess(result);
        } else {
            return handleError(result);
        }
        
    } catch (error) {
        console.error('Erreur réseau:', error);
        return { success: false, error: 'Erreur de connexion' };
    }
}

function handleSuccess(result) {
    return {
        success: true,
        driverRouteId: result.placement_result.driver_route_id,
        insertedStops: result.placement_result.inserted_stops,
        stopsReordered: result.tour_updates.stops_reordered,
        processingTime: result.processing_time
    };
}

function handleError(result) {
    return {
        success: false,
        errorCode: result.error_code,
        message: result.message
    };
}
```

---

## 🎨 ÉTAPE 4 : Interface utilisateur suggérée

### Composant de traitement

```jsx
function LateStopProcessor({ lateStopRequest, onSuccess, onError }) {
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);

    const handleProcess = async () => {
        setLoading(true);
        
        try {
            const response = await processLateStop(lateStopRequest.id);
            
            if (response.success) {
                setResult(response);
                onSuccess(response);
            } else {
                onError(response);
            }
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="late-stop-processor">
            <div className="request-info">
                <h3>Demande de dernière minute</h3>
                <p><strong>Client:</strong> {lateStopRequest.client_name}</p>
                <p><strong>Actions:</strong> 
                    {lateStopRequest.has_pickup && " 📦 Ramassage"}
                    {lateStopRequest.has_delivery && " 🚚 Livraison"}
                </p>
                <p><strong>Instructions:</strong> {lateStopRequest.urgent_instructions}</p>
            </div>

            {result && (
                <div className="placement-result">
                    <h4>✅ Placement effectué</h4>
                    <p>Stops ajoutés: {result.insertedStops.length}</p>
                    <p>Stops réorganisés: {result.stopsReordered}</p>
                    <p>Temps de traitement: {result.processingTime}</p>
                </div>
            )}

            <button 
                onClick={handleProcess} 
                disabled={loading}
                className="process-btn"
            >
                {loading ? "Traitement..." : "Traiter la demande"}
            </button>
        </div>
    );
}
```

---

## 📋 ÉTAPE 5 : Gestion des cas d'usage

### Cas 1: Ramassage uniquement (has_pickup = true)

**Attente front-end:**
```json
{
  "placement_result": {
    "inserted_stops": [
      {
        "stop_type": "client_pickup",
        "client_actions": "pickup"
      }
    ]
  }
}
```

### Cas 2: Livraison uniquement (has_delivery = true)

**Attente front-end:**
```json
{
  "placement_result": {
    "inserted_stops": [
      {
        "stop_type": "lab_dropoff", // ou "depot_dropoff" selon flags
        "client_actions": null
      }
    ]
  }
}
```

### Cas 3: Ramassage ET livraison

**Attente front-end:**
```json
{
  "placement_result": {
    "inserted_stops": [
      {
        "stop_type": "client_pickup",
        "client_actions": "pickup",
        "stop_order": 4
      },
      {
        "stop_type": "lab_dropoff",
        "client_actions": null,
        "stop_order": 7
      }
    ]
  }
}
```

### Cas 4: Dropoff existe déjà

**Attente front-end:**
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
        "pickup_stop_id": "stop-new-001",
        "delivery_stop_id": "stop-existing-dropoff"
      }
    ]
  }
}
```

---

## ⚠️ ÉTAPE 6 : Gestion d'erreurs complète

### Types d'erreurs possibles

```javascript
const ERROR_HANDLERS = {
    'INVALID_LATE_STOP_REQUEST': (error) => {
        // Demande déjà traitée, non trouvée, etc.
        showError('Cette demande a déjà été traitée ou n\'existe pas.');
        refreshLateStopsList();
    },
    
    'LATE_STOP_PROCESSING_ERROR': (error) => {
        // Erreur technique de traitement
        showError('Erreur technique lors du traitement. Réessayez.');
        logError(error);
    },
    
    'DRIVER_ROUTE_NOT_FOUND': (error) => {
        // Pas de tournée active pour ce jour
        showError('Aucune tournée active trouvée pour ce jour.');
    }
};

function handleApiError(result) {
    const handler = ERROR_HANDLERS[result.error_code];
    if (handler) {
        handler(result);
    } else {
        showError(`Erreur: ${result.message}`);
    }
}
```

---

## 🔄 ÉTAPE 7 : Mise à jour de l'interface après traitement

### Actualisation des données

```javascript
async function onLateStopProcessed(result) {
    // 1. Mettre à jour la liste des demandes pending
    await refreshPendingLateStops();
    
    // 2. Actualiser la tournée du driver
    await refreshDriverRoute(result.driverRouteId);
    
    // 3. Mettre à jour la vue carte/planning
    await updateRouteVisualization(result.placement_result);
    
    // 4. Notification de succès
    showSuccessMessage(
        `Arrêt ajouté avec succès. ${result.stopsReordered} stops réorganisés.`
    );
}
```

---

## 🧪 ÉTAPE 8 : Endpoint de test

### Pour déboguer l'intégration

```javascript
async function testLateStopProcessing(lateStopId, simulationMode = true) {
    const response = await fetch('/api/v1/tours/test-late-stop-processing', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-API-Key': process.env.API_KEY
        },
        body: JSON.stringify({
            late_stop_id: lateStopId,
            simulate_placement: simulationMode
        })
    });

    return await response.json();
}

// Usage pour simulation
const simulationResult = await testLateStopProcessing('test-id', true);
console.log('Workflow steps:', simulationResult.workflow_steps);
```

---

## 📱 ÉTAPE 9 : Exemples d'UI/UX

### Notification de succès
```
✅ Arrêt de dernière minute traité
📍 Ajouté à la position 4 (entre Stop 3 et Stop 4)
⏱️ 3 autres stops réorganisés
🕐 Traitement terminé en 2.3s
```

### Visualisation du placement
```
Tournée mise à jour:
1. 🏭 Dépôt (départ)
2. 🏠 Client A (livraison)  
3. 🧪 Labo B (ramassage)
4. 🆕 Client URGENT (ramassage) ← NOUVEAU
5. 🏠 Client C (ramassage)      ← Repositionné
6. 🧪 Labo B (retour)          ← Repositionné  
7. 🏭 Dépôt (retour)           ← Repositionné
```

---

## 🎯 Points clés pour l'intégration

1. **Une seule requête** : Le front n'envoie que l'ID, l'API fait tout
2. **Réponse complète** : Toutes les infos pour mettre à jour l'interface
3. **Gestion robuste** : Erreurs métier vs techniques bien séparées
4. **Traçabilité** : Tous les éléments créés sont flaggés `is_late_*`
5. **Performance** : Traitement rapide (2-5 secondes typical)

Est-ce que cette structure répond à vos besoins ? Voulez-vous que je détaille certains aspects ?