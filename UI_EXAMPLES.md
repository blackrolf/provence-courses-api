# 🎨 Exemples d'interface utilisateur - Late Stops

## Vue d'ensemble des composants suggérés

```
📋 Liste des demandes pending
├── 🔄 Processeur de late stop
├── 📍 Visualiseur de placement
├── ✅ Confirmation de traitement
└── 🚨 Gestion d'erreurs
```

---

## 🗂️ Liste des demandes de dernière minute

### Design suggéré

```jsx
function LateStopsList({ lateStops, onProcess }) {
    return (
        <div className="late-stops-container">
            <div className="header">
                <h2>🚨 Demandes de dernière minute</h2>
                <span className="count">{lateStops.length} en attente</span>
                <button className="refresh-btn" onClick={onRefresh}>
                    🔄 Actualiser
                </button>
            </div>
            
            <div className="late-stops-list">
                {lateStops.map(lateStop => (
                    <LateStopCard 
                        key={lateStop.id}
                        lateStop={lateStop}
                        onProcess={() => onProcess(lateStop)}
                    />
                ))}
            </div>
        </div>
    );
}

function LateStopCard({ lateStop, onProcess }) {
    const urgencyLevel = getUrgencyLevel(lateStop.requested_at);
    
    return (
        <div className={`late-stop-card urgency-${urgencyLevel}`}>
            <div className="card-header">
                <div className="client-info">
                    <h3>{lateStop.client_name}</h3>
                    <span className="lab-name">{lateStop.laboratory_name}</span>
                </div>
                <div className="urgency-badge">
                    {urgencyLevel === 'high' && '🔴 URGENT'}
                    {urgencyLevel === 'medium' && '🟡 Normal'}
                    {urgencyLevel === 'low' && '🟢 Différé'}
                </div>
            </div>
            
            <div className="card-body">
                <div className="actions-requested">
                    {lateStop.has_pickup && (
                        <div className="action-item">
                            📦 <strong>Ramassage</strong> requis
                        </div>
                    )}
                    {lateStop.has_delivery && (
                        <div className="action-item">
                            🚚 <strong>Livraison</strong> requise
                        </div>
                    )}
                </div>
                
                {lateStop.urgent_instructions && (
                    <div className="instructions">
                        <strong>Instructions:</strong>
                        <p>{lateStop.urgent_instructions}</p>
                    </div>
                )}
                
                <div className="metadata">
                    <span className="requested-time">
                        Demandé il y a {getTimeAgo(lateStop.requested_at)}
                    </span>
                </div>
            </div>
            
            <div className="card-actions">
                <button 
                    className="process-btn primary"
                    onClick={onProcess}
                >
                    ⚡ Traiter maintenant
                </button>
                <button className="details-btn secondary">
                    👁️ Détails
                </button>
            </div>
        </div>
    );
}
```

### CSS suggéré

```css
.late-stops-container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 20px;
}

.late-stop-card {
    background: white;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    border-left: 4px solid #ddd;
    transition: all 0.3s ease;
}

.late-stop-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 16px rgba(0,0,0,0.15);
}

.urgency-high {
    border-left-color: #ff4444;
    background: linear-gradient(90deg, #fff5f5 0%, white 10%);
}

.urgency-medium {
    border-left-color: #ffaa00;
    background: linear-gradient(90deg, #fffaf0 0%, white 10%);
}

.urgency-low {
    border-left-color: #00aa44;
}

.card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 16px;
}

.client-info h3 {
    margin: 0;
    font-size: 1.2em;
    color: #333;
}

.lab-name {
    color: #666;
    font-size: 0.9em;
}

.urgency-badge {
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.8em;
    font-weight: bold;
}

.action-item {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
    padding: 8px;
    background: #f8f9fa;
    border-radius: 6px;
}

.process-btn {
    background: linear-gradient(45deg, #ff6b6b, #ff8e53);
    color: white;
    border: none;
    padding: 12px 24px;
    border-radius: 8px;
    font-weight: bold;
    cursor: pointer;
    transition: all 0.3s ease;
}

.process-btn:hover {
    transform: scale(1.05);
    box-shadow: 0 4px 12px rgba(255,107,107,0.4);
}
```

---

## ⚡ Processeur de late stop avec états

```jsx
function LateStopProcessor({ lateStop, onSuccess, onError, onCancel }) {
    const [state, setState] = useState('confirm'); // confirm, processing, success, error
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);
    const [progress, setProgress] = useState(0);

    const handleConfirm = async () => {
        setState('processing');
        setProgress(0);
        
        // Simulation du progress
        const progressInterval = setInterval(() => {
            setProgress(prev => Math.min(prev + 10, 90));
        }, 200);

        try {
            const result = await processLateStop(lateStop.id);
            
            clearInterval(progressInterval);
            setProgress(100);
            setResult(result);
            setState('success');
            
            setTimeout(() => onSuccess(result), 1500);
            
        } catch (err) {
            clearInterval(progressInterval);
            setError(err);
            setState('error');
        }
    };

    return (
        <div className="late-stop-processor-modal">
            <div className="modal-overlay" onClick={onCancel} />
            
            <div className="modal-content">
                {state === 'confirm' && (
                    <ConfirmationView 
                        lateStop={lateStop}
                        onConfirm={handleConfirm}
                        onCancel={onCancel}
                    />
                )}
                
                {state === 'processing' && (
                    <ProcessingView 
                        progress={progress}
                        lateStop={lateStop}
                    />
                )}
                
                {state === 'success' && (
                    <SuccessView 
                        result={result}
                        lateStop={lateStop}
                    />
                )}
                
                {state === 'error' && (
                    <ErrorView 
                        error={error}
                        onRetry={handleConfirm}
                        onCancel={onCancel}
                    />
                )}
            </div>
        </div>
    );
}

function ConfirmationView({ lateStop, onConfirm, onCancel }) {
    return (
        <div className="confirmation-view">
            <div className="modal-header">
                <h2>⚡ Traitement de dernière minute</h2>
            </div>
            
            <div className="modal-body">
                <div className="client-summary">
                    <h3>{lateStop.client_name}</h3>
                    <p className="lab-name">{lateStop.laboratory_name}</p>
                </div>
                
                <div className="actions-summary">
                    <h4>Actions à effectuer :</h4>
                    {lateStop.has_pickup && (
                        <div className="action-preview">
                            📦 Ajouter un <strong>point de ramassage</strong>
                        </div>
                    )}
                    {lateStop.has_delivery && (
                        <div className="action-preview">
                            🚚 Créer/utiliser un <strong>point de livraison</strong>
                        </div>
                    )}
                </div>
                
                {lateStop.urgent_instructions && (
                    <div className="instructions-box">
                        <h4>Instructions spéciales :</h4>
                        <p>{lateStop.urgent_instructions}</p>
                    </div>
                )}
                
                <div className="impact-warning">
                    ⚠️ <strong>Impact :</strong> La tournée sera modifiée et les stops réorganisés automatiquement.
                </div>
            </div>
            
            <div className="modal-actions">
                <button className="cancel-btn" onClick={onCancel}>
                    ❌ Annuler
                </button>
                <button className="confirm-btn" onClick={onConfirm}>
                    ✅ Confirmer le traitement
                </button>
            </div>
        </div>
    );
}

function ProcessingView({ progress, lateStop }) {
    const steps = [
        'Analyse de la demande',
        'Recherche de la tournée',
        'Calcul du placement optimal',
        'Création des nouveaux stops',
        'Réorganisation de la séquence',
        'Sauvegarde des modifications'
    ];
    
    const currentStep = Math.floor(progress / 100 * steps.length);
    
    return (
        <div className="processing-view">
            <div className="modal-header">
                <h2>🔄 Traitement en cours...</h2>
            </div>
            
            <div className="modal-body">
                <div className="progress-circle">
                    <svg className="progress-ring" width="120" height="120">
                        <circle
                            className="progress-ring-circle"
                            stroke="#4CAF50"
                            strokeWidth="6"
                            fill="transparent"
                            r="52"
                            cx="60"
                            cy="60"
                            strokeDasharray={`${2 * Math.PI * 52}`}
                            strokeDashoffset={`${2 * Math.PI * 52 * (1 - progress / 100)}`}
                        />
                    </svg>
                    <div className="progress-text">
                        {Math.round(progress)}%
                    </div>
                </div>
                
                <div className="steps-progress">
                    {steps.map((step, index) => (
                        <div 
                            key={index}
                            className={`step ${index <= currentStep ? 'completed' : 'pending'}`}
                        >
                            <div className="step-icon">
                                {index < currentStep ? '✅' : index === currentStep ? '⚡' : '⏳'}
                            </div>
                            <div className="step-text">{step}</div>
                        </div>
                    ))}
                </div>
                
                <div className="processing-client">
                    <p>Client : <strong>{lateStop.client_name}</strong></p>
                </div>
            </div>
        </div>
    );
}

function SuccessView({ result, lateStop }) {
    const { placement_result, tour_updates } = result;
    
    return (
        <div className="success-view">
            <div className="modal-header">
                <h2>✅ Traitement réussi !</h2>
            </div>
            
            <div className="modal-body">
                <div className="success-summary">
                    <div className="stat-card">
                        <div className="stat-number">{placement_result.inserted_stops.length}</div>
                        <div className="stat-label">Stops ajoutés</div>
                    </div>
                    
                    <div className="stat-card">
                        <div className="stat-number">{tour_updates.stops_reordered}</div>
                        <div className="stat-label">Stops réorganisés</div>
                    </div>
                    
                    <div className="stat-card">
                        <div className="stat-number">{result.processing_time}</div>
                        <div className="stat-label">Temps de traitement</div>
                    </div>
                </div>
                
                <div className="placement-details">
                    <h4>📍 Nouveaux stops créés :</h4>
                    {placement_result.inserted_stops.map((stop, index) => (
                        <div key={stop.id} className="inserted-stop">
                            <div className="stop-icon">
                                {stop.stop_type.includes('pickup') ? '📦' : '🚚'}
                            </div>
                            <div className="stop-details">
                                <strong>{getStopTypeLabel(stop.stop_type)}</strong>
                                <span className="stop-position">Position {stop.stop_order}</span>
                            </div>
                        </div>
                    ))}
                </div>
                
                <div className="tour-impact">
                    <h4>🔄 Impact sur la tournée :</h4>
                    <p>
                        Tournée mise à jour : {tour_updates.total_stops_before} → {tour_updates.total_stops_after} stops
                    </p>
                </div>
            </div>
            
            <div className="modal-actions">
                <button className="view-tour-btn">
                    🗺️ Voir la tournée mise à jour
                </button>
            </div>
        </div>
    );
}
```

---

## 📍 Visualiseur de placement (avant/après)

```jsx
function PlacementVisualizer({ beforeStops, afterStops, insertedStops }) {
    return (
        <div className="placement-visualizer">
            <div className="visualization-header">
                <h3>📍 Visualisation du placement</h3>
            </div>
            
            <div className="before-after-container">
                <div className="stops-column">
                    <h4>Avant</h4>
                    <div className="stops-sequence">
                        {beforeStops.map((stop, index) => (
                            <StopVisualization 
                                key={stop.id}
                                stop={stop}
                                order={index + 1}
                                isOriginal={true}
                            />
                        ))}
                    </div>
                </div>
                
                <div className="arrow-column">
                    <div className="transformation-arrow">
                        ➡️
                        <span className="transformation-label">
                            +{insertedStops.length} stops
                        </span>
                    </div>
                </div>
                
                <div className="stops-column">
                    <h4>Après</h4>
                    <div className="stops-sequence">
                        {afterStops.map((stop, index) => {
                            const isInserted = insertedStops.some(is => is.id === stop.id);
                            const isReordered = !isInserted && beforeStops.findIndex(bs => bs.id === stop.id) !== index;
                            
                            return (
                                <StopVisualization 
                                    key={stop.id}
                                    stop={stop}
                                    order={index + 1}
                                    isInserted={isInserted}
                                    isReordered={isReordered}
                                />
                            );
                        })}
                    </div>
                </div>
            </div>
        </div>
    );
}

function StopVisualization({ stop, order, isOriginal, isInserted, isReordered }) {
    const getStopIcon = (stopType) => {
        const icons = {
            'depot_pickup': '🏭',
            'client_pickup': '📦',
            'client_delivery': '🚚',
            'lab_pickup': '🧪',
            'lab_dropoff': '🧪',
            'depot_dropoff': '🏭'
        };
        return icons[stopType] || '📍';
    };
    
    let className = 'stop-visualization';
    if (isInserted) className += ' inserted';
    if (isReordered) className += ' reordered';
    if (isOriginal) className += ' original';
    
    return (
        <div className={className}>
            <div className="stop-order">{order}</div>
            <div className="stop-content">
                <div className="stop-icon">{getStopIcon(stop.stop_type)}</div>
                <div className="stop-details">
                    <div className="stop-type">{getStopTypeLabel(stop.stop_type)}</div>
                    <div className="stop-address">{stop.formatted_address?.substring(0, 30)}...</div>
                </div>
            </div>
            {isInserted && <div className="inserted-badge">NOUVEAU</div>}
            {isReordered && <div className="reordered-badge">DÉPLACÉ</div>}
        </div>
    );
}
```

---

## 🚨 Composants de gestion d'erreurs

```jsx
function ErrorDisplay({ error, onRetry, onDismiss, canRetry = true }) {
    const getErrorIcon = (errorCode) => {
        const icons = {
            'INVALID_LATE_STOP_REQUEST': '⚠️',
            'DRIVER_ROUTE_NOT_FOUND': '🚫',
            'LATE_STOP_PROCESSING_ERROR': '🔥'
        };
        return icons[errorCode] || '❌';
    };
    
    const getErrorColor = (errorCode) => {
        if (errorCode === 'INVALID_LATE_STOP_REQUEST') return 'warning';
        if (errorCode === 'DRIVER_ROUTE_NOT_FOUND') return 'info';
        return 'error';
    };
    
    return (
        <div className={`error-display ${getErrorColor(error.error_code)}`}>
            <div className="error-header">
                <div className="error-icon">{getErrorIcon(error.error_code)}</div>
                <h3>Erreur de traitement</h3>
            </div>
            
            <div className="error-body">
                <div className="error-message">
                    {error.message}
                </div>
                
                {error.processing_time && (
                    <div className="error-details">
                        Temps écoulé : {error.processing_time}
                    </div>
                )}
                
                <div className="error-code">
                    Code d'erreur : {error.error_code}
                </div>
            </div>
            
            <div className="error-actions">
                {canRetry && (
                    <button className="retry-btn" onClick={onRetry}>
                        🔄 Réessayer
                    </button>
                )}
                
                <button className="dismiss-btn" onClick={onDismiss}>
                    ❌ Fermer
                </button>
                
                {error.error_code === 'LATE_STOP_PROCESSING_ERROR' && (
                    <button className="support-btn">
                        🆘 Contacter le support
                    </button>
                )}
            </div>
        </div>
    );
}
```

---

## 🎯 Notifications toast

```jsx
function useToast() {
    const [toasts, setToasts] = useState([]);
    
    const addToast = (message, type = 'info', duration = 5000) => {
        const id = Date.now();
        const toast = { id, message, type, duration };
        
        setToasts(prev => [...prev, toast]);
        
        setTimeout(() => {
            setToasts(prev => prev.filter(t => t.id !== id));
        }, duration);
    };
    
    return { toasts, addToast };
}

function ToastContainer({ toasts }) {
    return (
        <div className="toast-container">
            {toasts.map(toast => (
                <Toast key={toast.id} toast={toast} />
            ))}
        </div>
    );
}

function Toast({ toast }) {
    const icons = {
        success: '✅',
        error: '❌',
        warning: '⚠️',
        info: 'ℹ️'
    };
    
    return (
        <div className={`toast toast-${toast.type}`}>
            <div className="toast-icon">{icons[toast.type]}</div>
            <div className="toast-message">{toast.message}</div>
        </div>
    );
}

// Usage
function LateStopHandler() {
    const { addToast } = useToast();
    
    const handleSuccess = (result) => {
        addToast(
            `Arrêt ajouté avec succès ! ${result.stopsReordered} stops réorganisés.`,
            'success'
        );
    };
    
    const handleError = (error) => {
        addToast(
            `Erreur: ${error.message}`,
            'error',
            8000 // Plus long pour les erreurs
        );
    };
}
```

Ces exemples d'UI couvrent tous les aspects de l'expérience utilisateur pour les late stops. Ils sont conçus pour être intuitifs, informatifs et robustes en cas d'erreur.

<function_calls>
<invoke name="TodoWrite">
<parameter name="todos">[{"content": "Cr\u00e9er le guide d'int\u00e9gration front-end", "status": "completed", "activeForm": "Cr\u00e9ant le guide d'int\u00e9gration front-end"}, {"content": "Documenter la structure exacte des r\u00e9ponses API", "status": "completed", "activeForm": "Documentant la structure exacte des r\u00e9ponses API"}, {"content": "Cr\u00e9er des exemples de requ\u00eates avec donn\u00e9es r\u00e9elles", "status": "completed", "activeForm": "Cr\u00e9ant des exemples de requ\u00eates avec donn\u00e9es r\u00e9elles"}, {"content": "Documenter la gestion d'erreurs", "status": "completed", "activeForm": "Documentant la gestion d'erreurs"}, {"content": "Ajouter des exemples d'interface utilisateur", "status": "completed", "activeForm": "Ajoutant des exemples d'interface utilisateur"}]