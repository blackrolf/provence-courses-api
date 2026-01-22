# Intégration Frontend - API d'Optimisation des Tournées

## Vue d'ensemble

L'API d'optimisation des tournées a été simplifiée avec une nouvelle logique de fusion par UUID. Ce document explique comment intégrer les appels d'optimisation dans votre frontend.

## Points Importants

### ⚠️ Temps de Traitement
- **Durée typique** : 2-5 minutes pour une route complète
- **Processus complexe** : OR-Tools + Google Directions + Mise à jour Supabase
- **Recommandation** : Interface asynchrone avec indicateurs de progression

### 🔄 Disponibilité de l'API
- **Vérifier la santé** de l'API avant les appels longs
- **Gérer les timeouts** et reconnexions
- **Afficher l'état** du traitement à l'utilisateur

---

## 1. Endpoints Disponibles

### 🚀 Génération + Optimisation Complète
```http
POST /api/v1/tours/generate-and-optimize
```

**Usage** : Génère une nouvelle tournée ET l'optimise directement.

**Body** :
```json
{
  "driver_id": "uuid-driver",
  "date": "2025-01-15",
  "include_late_stops": true
}
```

**Réponse** (après 2-5 minutes) :
```json
{
  "status": "success",
  "route_id": "uuid-route",
  "generation_applied": true,
  "optimization_applied": true,
  "fusion_applied": true,
  "enrichment_applied": true,
  "supabase_updated": true,
  "final_stops_count": 25,
  "processing_summary": {
    "generation_time_seconds": 45.2,
    "optimization_time_seconds": 180.7,
    "total_time_seconds": 225.9
  },
  "optimization_summary": {
    "original_stops": 29,
    "final_stops_after_fusion": 25,
    "stops_merged": 4,
    "total_distance_km": 95.3,
    "estimated_duration_minutes": 480
  }
}
```

### 🔧 Optimisation Uniquement
```http
POST /api/v1/tours/{route_id}/optimize
```

**Usage** : Optimise une tournée existante.

**Réponse** :
```json
{
  "status": "success",
  "route_id": "uuid-route",
  "optimization_applied": true,
  "fusion_applied": true,
  "enrichment_applied": true,
  "supabase_updated": true,
  "final_stops_count": 25,
  "optimization_summary": {
    "original_stops": 29,
    "or_tools_stops_count": 33,
    "final_stops_after_fusion": 25,
    "stops_merged": 4,
    "total_distance_km": 95.3,
    "estimated_duration_minutes": 480
  }
}
```

---

## 2. Vérification de la Santé de l'API

### Health Check Endpoint
```http
GET /api/v1/health
```

**Réponse** :
```json
{
  "status": "healthy",
  "timestamp": "2025-01-15T10:30:00Z",
  "services": {
    "supabase": "connected",
    "osrm": "available",
    "google_maps": "configured"
  }
}
```

### Implémentation Frontend (JavaScript)
```javascript
async function checkApiHealth() {
  try {
    const response = await fetch('/api/v1/health', {
      method: 'GET',
      timeout: 5000 // 5 secondes max
    });
    
    if (!response.ok) {
      throw new Error(`API Health Check Failed: ${response.status}`);
    }
    
    const health = await response.json();
    return health.status === 'healthy';
  } catch (error) {
    console.warn('API Health Check Failed:', error);
    return false;
  }
}
```

---

## 3. Appel d'Optimisation avec Gestion d'État

### Interface Utilisateur Recommandée

```jsx
function OptimizationPanel({ routeId, onOptimizationComplete }) {
  const [status, setStatus] = useState('idle'); // idle, checking, optimizing, success, error
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState(null);

  const optimizeRoute = async () => {
    try {
      // 1. Vérifier la santé de l'API
      setStatus('checking');
      const isHealthy = await checkApiHealth();
      
      if (!isHealthy) {
        setError('API indisponible. Veuillez réessayer plus tard.');
        setStatus('error');
        return;
      }

      // 2. Lancer l'optimisation
      setStatus('optimizing');
      setProgress({ step: 'Initialisation...', percentage: 0 });

      const response = await fetch(`/api/v1/tours/${routeId}/optimize`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        // Timeout de 10 minutes
        signal: AbortSignal.timeout(600000)
      });

      if (!response.ok) {
        throw new Error(`Erreur ${response.status}: ${response.statusText}`);
      }

      const result = await response.json();
      
      if (result.status === 'success') {
        setStatus('success');
        onOptimizationComplete(result);
      } else {
        setError(result.message || 'Erreur d\'optimisation');
        setStatus('error');
      }

    } catch (error) {
      console.error('Optimization Error:', error);
      setError(error.message);
      setStatus('error');
    }
  };

  return (
    <div className="optimization-panel">
      {/* Bouton d'optimisation */}
      <button 
        onClick={optimizeRoute}
        disabled={status === 'checking' || status === 'optimizing'}
        className="optimize-btn"
      >
        {status === 'checking' && 'Vérification...'}
        {status === 'optimizing' && 'Optimisation en cours...'}
        {status === 'idle' && 'Optimiser la Tournée'}
        {status === 'success' && 'Optimisation Terminée ✓'}
        {status === 'error' && 'Réessayer'}
      </button>

      {/* Indicateur de progression */}
      {status === 'optimizing' && (
        <div className="progress-indicator">
          <div className="spinner"></div>
          <p>Optimisation en cours... (2-5 minutes)</p>
          <div className="progress-steps">
            <div className="step">🔄 OR-Tools</div>
            <div className="step">🔀 Fusion des stops</div>
            <div className="step">📍 Google Directions</div>
            <div className="step">💾 Mise à jour</div>
          </div>
        </div>
      )}

      {/* Résultats */}
      {status === 'success' && progress && (
        <div className="success-summary">
          <h4>✅ Optimisation Réussie</h4>
          <p><strong>Stops finaux :</strong> {progress.final_stops_count}</p>
          <p><strong>Distance :</strong> {progress.total_distance_km} km</p>
          <p><strong>Durée estimée :</strong> {progress.estimated_duration_minutes} min</p>
          {progress.stops_merged > 0 && (
            <p><strong>Stops fusionnés :</strong> {progress.stops_merged}</p>
          )}
        </div>
      )}

      {/* Erreurs */}
      {status === 'error' && error && (
        <div className="error-message">
          <h4>❌ Erreur d'Optimisation</h4>
          <p>{error}</p>
        </div>
      )}
    </div>
  );
}
```

---

## 4. Polling pour Suivi en Temps Réel (Optionnel)

Si vous voulez suivre le progrès en temps réel, vous pouvez implémenter un système de polling :

### Endpoint de Statut (à implémenter)
```http
GET /api/v1/tours/{route_id}/optimization-status
```

### Implémentation Polling
```javascript
async function pollOptimizationStatus(routeId, onProgress) {
  const pollInterval = 5000; // 5 secondes
  
  const poll = async () => {
    try {
      const response = await fetch(`/api/v1/tours/${routeId}/optimization-status`);
      const status = await response.json();
      
      onProgress(status);
      
      if (status.status === 'completed' || status.status === 'error') {
        return status;
      }
      
      // Continuer le polling
      setTimeout(poll, pollInterval);
    } catch (error) {
      onProgress({ status: 'error', message: error.message });
    }
  };
  
  poll();
}
```

---

## 5. Gestion des Erreurs Communes

### Erreurs Possibles

| Code | Erreur | Solution |
|------|---------|----------|
| `400` | Route invalide | Vérifier l'ID de la route |
| `404` | Route introuvable | Générer d'abord la route |
| `408` | Timeout | Réessayer, l'API peut être surchargée |
| `500` | Erreur serveur | Vérifier les logs, contacter le support |
| `503` | Service indisponible | L'API est en maintenance |

### Retry Logic
```javascript
async function optimizeWithRetry(routeId, maxRetries = 2) {
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await optimizeRoute(routeId);
    } catch (error) {
      if (attempt === maxRetries) {
        throw error; // Dernière tentative échouée
      }
      
      // Attendre avant de réessayer (backoff exponentiel)
      const delay = Math.pow(2, attempt) * 1000;
      await new Promise(resolve => setTimeout(resolve, delay));
    }
  }
}
```

---

## 6. CSS pour l'Interface

```css
.optimization-panel {
  padding: 20px;
  border: 1px solid #ddd;
  border-radius: 8px;
  background: #f9f9f9;
}

.optimize-btn {
  background: #007bff;
  color: white;
  border: none;
  padding: 12px 24px;
  border-radius: 6px;
  font-size: 16px;
  cursor: pointer;
  width: 100%;
}

.optimize-btn:disabled {
  background: #6c757d;
  cursor: not-allowed;
}

.progress-indicator {
  margin-top: 20px;
  text-align: center;
}

.spinner {
  border: 4px solid #f3f3f3;
  border-top: 4px solid #007bff;
  border-radius: 50%;
  width: 50px;
  height: 50px;
  animation: spin 1s linear infinite;
  margin: 0 auto 15px;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.progress-steps {
  display: flex;
  justify-content: space-between;
  margin-top: 15px;
}

.step {
  padding: 8px 12px;
  background: #e9ecef;
  border-radius: 4px;
  font-size: 14px;
}

.success-summary {
  background: #d4edda;
  color: #155724;
  padding: 15px;
  border-radius: 6px;
  margin-top: 15px;
}

.error-message {
  background: #f8d7da;
  color: #721c24;
  padding: 15px;
  border-radius: 6px;
  margin-top: 15px;
}
```

---

## 7. Checklist d'Intégration

### ✅ Avant de Commencer
- [ ] API accessible et health check OK
- [ ] Clés Google Maps configurées (pour enrichissement)
- [ ] Timeout appropriés configurés (10 minutes)
- [ ] Interface utilisateur avec indicateurs de progression

### ✅ Fonctionnalités Recommandées
- [ ] Health check avant optimisation
- [ ] Indicateur de progression pendant l'optimisation
- [ ] Affichage des résultats (distance, durée, stops fusionnés)
- [ ] Gestion d'erreurs avec retry logic
- [ ] Possibilité d'annuler une optimisation en cours

### ✅ Tests
- [ ] Test avec route simple (< 10 stops)
- [ ] Test avec route complexe (> 20 stops)
- [ ] Test de gestion d'erreur (route inexistante)
- [ ] Test de timeout / API indisponible

---

## Support

Pour toute question technique :
- **Logs API** : Consulter `/api/v1/logs` 
- **Documentation** : Ce fichier + code source
- **Debugging** : Activer les logs détaillés côté API

L'API est maintenant **simplifiée et robuste** ! 🚀