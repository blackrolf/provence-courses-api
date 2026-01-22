# 🚨 Guide de gestion d'erreurs - Late Stops API

## Types d'erreurs et codes de retour

### 🔴 Erreurs client (400-499)

#### **400 - INVALID_LATE_STOP_REQUEST**

**Causes possibles:**
- Demande de late stop non trouvée
- Status déjà traité (approved/rejected)
- Aucune action spécifiée (has_pickup et has_delivery = false)

```json
{
  "status": "error",
  "message": "Demande déjà traitée (statut: approved)",
  "processing_time": "0.1s",
  "error_code": "INVALID_LATE_STOP_REQUEST",
  "late_stop_request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Actions front-end:**
```javascript
if (error.error_code === 'INVALID_LATE_STOP_REQUEST') {
    if (error.message.includes('déjà traitée')) {
        showWarning('Cette demande a déjà été traitée.');
        refreshLateStopsList(); // Actualiser la liste
    } else if (error.message.includes('non trouvée')) {
        showError('Demande introuvable. Elle a peut-être été supprimée.');
        redirectToLateStopsList();
    }
}
```

#### **404 - DRIVER_ROUTE_NOT_FOUND**

**Cause:** Aucune tournée driver active pour la date

```json
{
  "status": "error",
  "message": "Aucune tournée driver active trouvée pour la date 2025-09-10",
  "processing_time": "0.3s",
  "error_code": "DRIVER_ROUTE_NOT_FOUND"
}
```

**Actions front-end:**
```javascript
if (error.error_code === 'DRIVER_ROUTE_NOT_FOUND') {
    showError(
        'Aucune tournée active trouvée pour cette date. ' +
        'Vérifiez qu\'une tournée est bien générée et optimisée.'
    );
    suggestCreateTour(); // Proposer de générer une tournée
}
```

### 🔥 Erreurs serveur (500-599)

#### **500 - LATE_STOP_PROCESSING_ERROR**

**Causes possibles:**
- Erreur de base de données
- Problème de connexion Supabase  
- Erreur dans la logique de placement
- Timeout de traitement

```json
{
  "status": "error",
  "message": "Erreur lors du traitement de l'arrêt tardif: Connection timeout",
  "processing_time": "30.0s",
  "error_code": "LATE_STOP_PROCESSING_ERROR"
}
```

**Actions front-end:**
```javascript
if (error.error_code === 'LATE_STOP_PROCESSING_ERROR') {
    if (error.processing_time > 25) {
        showError('Timeout - Le traitement a pris trop de temps. Réessayez.');
    } else {
        showError('Erreur technique lors du traitement. Contactez le support.');
        logError(error); // Log pour debugging
    }
    
    enableRetryButton(); // Permettre de réessayer
}
```

---

## 🛠️ Stratégies de récupération d'erreurs

### Retry automatique

```javascript
class LateStopProcessor {
    async processWithRetry(lateStopId, maxRetries = 3) {
        let lastError;
        
        for (let attempt = 1; attempt <= maxRetries; attempt++) {
            try {
                showProgress(`Tentative ${attempt}/${maxRetries}...`);
                
                const result = await this.processLateStop(lateStopId);
                return result; // Succès
                
            } catch (error) {
                lastError = error;
                
                // Retry seulement pour certains types d'erreurs
                if (this.shouldRetry(error) && attempt < maxRetries) {
                    await this.delay(1000 * attempt); // Backoff exponentiel
                    continue;
                } else {
                    break; // Ne pas retry
                }
            }
        }
        
        // Toutes les tentatives ont échoué
        throw lastError;
    }
    
    shouldRetry(error) {
        const retryableErrors = [
            'LATE_STOP_PROCESSING_ERROR',
            'DATABASE_CONNECTION_ERROR',
            'TIMEOUT_ERROR'
        ];
        
        return retryableErrors.includes(error.error_code);
    }
    
    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}
```

### Validation côté front

```javascript
function validateLateStopRequest(lateStopData) {
    const errors = [];
    
    // Vérifier le statut
    if (lateStopData.status !== 'pending') {
        errors.push(`Statut invalide: ${lateStopData.status}`);
    }
    
    // Vérifier les actions
    if (!lateStopData.has_pickup && !lateStopData.has_delivery) {
        errors.push('Aucune action (pickup/delivery) spécifiée');
    }
    
    // Vérifier la date
    const requestDate = new Date(lateStopData.requested_at);
    const today = new Date();
    if (requestDate.toDateString() !== today.toDateString()) {
        errors.push('Demande pas du jour courant');
    }
    
    if (errors.length > 0) {
        throw new ValidationError(errors);
    }
}
```

---

## 📊 Monitoring et logging

### Métriques importantes

```javascript
class LateStopMetrics {
    track(event, data) {
        const metrics = {
            timestamp: new Date().toISOString(),
            event: event,
            late_stop_id: data.lateStopId,
            processing_time: data.processingTime,
            error_code: data.errorCode,
            retry_count: data.retryCount
        };
        
        // Envoyer aux analytics
        analytics.track('late_stop_' + event, metrics);
    }
}

// Usage
metrics.track('processing_started', { lateStopId: 'abc-123' });
metrics.track('processing_failed', { 
    lateStopId: 'abc-123', 
    errorCode: 'TIMEOUT',
    retryCount: 2 
});
```

### Logs structurés

```javascript
const logger = {
    error: (message, context) => {
        console.error({
            level: 'error',
            message: message,
            context: context,
            timestamp: new Date().toISOString(),
            user_id: getCurrentUserId(),
            session_id: getSessionId()
        });
    }
};

// Usage lors d'erreurs
logger.error('Late stop processing failed', {
    late_stop_id: 'abc-123',
    error_code: 'LATE_STOP_PROCESSING_ERROR',
    api_response: errorResponse,
    retry_count: 2
});
```

---

## 🎯 UX/UI pour la gestion d'erreurs

### Messages utilisateur

```javascript
const ERROR_MESSAGES = {
    'INVALID_LATE_STOP_REQUEST': {
        title: 'Demande invalide',
        message: 'Cette demande ne peut pas être traitée.',
        icon: '⚠️',
        actions: ['Actualiser la liste', 'Retour']
    },
    
    'DRIVER_ROUTE_NOT_FOUND': {
        title: 'Tournée introuvable',
        message: 'Aucune tournée active pour cette date.',
        icon: '🚫',
        actions: ['Générer tournée', 'Changer de date']
    },
    
    'LATE_STOP_PROCESSING_ERROR': {
        title: 'Erreur technique',
        message: 'Un problème technique s\'est produit.',
        icon: '🔥',
        actions: ['Réessayer', 'Contacter support']
    }
};

function showErrorDialog(errorCode, errorData) {
    const config = ERROR_MESSAGES[errorCode] || {
        title: 'Erreur',
        message: 'Une erreur inattendue s\'est produite.',
        icon: '❌',
        actions: ['OK']
    };
    
    return showDialog({
        title: `${config.icon} ${config.title}`,
        message: config.message,
        details: errorData.message,
        actions: config.actions
    });
}
```

### États de chargement et d'erreur

```jsx
function LateStopProcessor({ lateStopId }) {
    const [state, setState] = useState('idle'); // idle, loading, success, error
    const [error, setError] = useState(null);
    const [retryCount, setRetryCount] = useState(0);
    
    const handleProcess = async () => {
        setState('loading');
        setError(null);
        
        try {
            const result = await processLateStop(lateStopId);
            setState('success');
            onSuccess(result);
            
        } catch (err) {
            setState('error');
            setError(err);
        }
    };
    
    const handleRetry = () => {
        setRetryCount(prev => prev + 1);
        handleProcess();
    };
    
    return (
        <div className="late-stop-processor">
            {state === 'loading' && (
                <div className="loading-state">
                    <Spinner />
                    <p>Traitement en cours...</p>
                    {retryCount > 0 && <p>Tentative {retryCount + 1}</p>}
                </div>
            )}
            
            {state === 'error' && (
                <ErrorDisplay 
                    error={error}
                    onRetry={handleRetry}
                    canRetry={shouldRetry(error)}
                />
            )}
            
            {state === 'success' && (
                <SuccessMessage />
            )}
        </div>
    );
}
```

---

## 🔧 Debugging et diagnostics

### Informations de debug à collecter

```javascript
function collectDebugInfo(error, context) {
    return {
        // Informations d'erreur
        error_code: error.error_code,
        error_message: error.message,
        processing_time: error.processing_time,
        
        // Contexte de la demande
        late_stop_id: context.lateStopId,
        user_id: getCurrentUserId(),
        timestamp: new Date().toISOString(),
        
        // Informations système
        browser: navigator.userAgent,
        viewport: `${window.innerWidth}x${window.innerHeight}`,
        connection: navigator.connection?.effectiveType,
        
        // État de l'application
        current_route: window.location.pathname,
        app_version: process.env.REACT_APP_VERSION,
        
        // Données de la demande (sanitized)
        request_data: sanitizeForLogging(context.requestData)
    };
}
```

### Mode debug pour développement

```javascript
const DEBUG_MODE = process.env.NODE_ENV === 'development';

if (DEBUG_MODE) {
    // Console logs détaillés
    console.group('🚨 Late Stop Error Debug');
    console.log('Error:', error);
    console.log('Context:', context);
    console.log('Stack trace:', error.stack);
    console.groupEnd();
    
    // Mock responses pour testing
    if (error.error_code === 'MOCK_ERROR') {
        return mockSuccessResponse();
    }
}
```

---

## 📋 Checklist de gestion d'erreurs

### ✅ Côté front-end

1. **Validation préventive**
   - [ ] Vérifier le statut avant traitement
   - [ ] Valider les données de la demande
   - [ ] Vérifier les permissions utilisateur

2. **Gestion des erreurs**
   - [ ] Intercepter tous les codes d'erreur
   - [ ] Messages utilisateur appropriés
   - [ ] Actions de récupération disponibles

3. **Retry et fallback**
   - [ ] Retry automatique pour erreurs temporaires
   - [ ] Backoff exponentiel
   - [ ] Limite de tentatives

4. **Monitoring**
   - [ ] Logging des erreurs
   - [ ] Métriques de performance
   - [ ] Alertes pour erreurs critiques

### 🔧 Tests d'erreurs

```javascript
describe('Late Stop Error Handling', () => {
    test('should handle invalid late stop request', async () => {
        mockApi.post.mockRejectedValue({
            error_code: 'INVALID_LATE_STOP_REQUEST',
            message: 'Demande déjà traitée'
        });
        
        const result = await processLateStop('invalid-id');
        expect(result.success).toBe(false);
        expect(result.errorCode).toBe('INVALID_LATE_STOP_REQUEST');
    });
    
    test('should retry on server errors', async () => {
        mockApi.post
            .mockRejectedValueOnce({ error_code: 'LATE_STOP_PROCESSING_ERROR' })
            .mockResolvedValue({ status: 'success' });
        
        const result = await processWithRetry('test-id');
        expect(result.success).toBe(true);
        expect(mockApi.post).toHaveBeenCalledTimes(2);
    });
});
```

Cette approche de gestion d'erreurs couvre-t-elle vos besoins ? Y a-t-il des scénarios spécifiques que vous souhaitez ajouter ?