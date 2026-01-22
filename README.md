# Provence Courses API

API FastAPI pour l'optimisation des tournées de livraison utilisant OR-Tools VRP solver.

## Description

Cette API gère la génération, l'optimisation et la gestion des tournées pour un système logistique de livraison. Elle utilise :
- **OR-Tools** : Résolution de problèmes VRP (Vehicle Routing Problem)
- **OSRM** : Calcul des matrices de distances en temps réel
- **Supabase** : Base de données PostgreSQL et authentification
- **Google Maps API** : Fallback pour les calculs de distances

## Prérequis

- Python 3.10+
- Serveur OSRM (pour les calculs de distances)
- Compte Supabase avec base de données configurée

## Installation

### 1. Cloner le repository

```bash
git clone https://github.com/blackrolf/provence-courses-api.git
cd provence-courses-api
```

### 2. Créer l'environnement virtuel

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 4. Configurer les variables d'environnement

```bash
cp .env.example .env
nano .env  # Éditer et remplir les valeurs
```

**Variables requises :**
| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | URL de votre instance Supabase |
| `SUPABASE_ANON_KEY` | Clé anonyme Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | Clé service role Supabase |
| `OSRM_URL` | URL du serveur OSRM (ex: http://localhost:5000) |
| `API_KEY` | Clé d'authentification pour l'API |

**Variables optionnelles :**
| Variable | Description |
|----------|-------------|
| `GOOGLE_MAPS_API_KEY` | Clé API Google Maps (fallback) |

## Utilisation

### Mode développement

```bash
source venv/bin/activate
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Mode production (systemd)

1. Copier le fichier service :
```bash
sudo cp deployment/systemd/provence-courses-api.service /etc/systemd/system/
sudo systemctl daemon-reload
```

2. Éditer le service pour adapter les chemins :
```bash
sudo nano /etc/systemd/system/provence-courses-api.service
```

3. Démarrer le service :
```bash
sudo systemctl enable provence-courses-api
sudo systemctl start provence-courses-api
```

4. Vérifier le statut :
```bash
sudo systemctl status provence-courses-api
sudo journalctl -u provence-courses-api -f  # Logs en temps réel
```

### Configuration Nginx (optionnel)

```bash
sudo cp deployment/nginx/api.provence-courses.fr /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/api.provence-courses.fr /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## Architecture

```
app/
├── main.py                 # Point d'entrée FastAPI
├── api/v1/routes/          # Endpoints API
│   └── tours.py            # Routes de gestion des tournées
├── core/                   # Configuration et sécurité
│   ├── config.py           # Settings Pydantic
│   └── security.py         # Authentification API
├── integrations/           # Services externes
│   ├── supabase/           # Client Supabase + repositories
│   ├── osrm/               # Client OSRM
│   └── google/             # Client Google Maps
├── models/                 # Modèles de données
│   ├── domain/             # Entités métier
│   ├── requests/           # Schémas de requêtes
│   └── responses/          # Schémas de réponses
└── services/tours/         # Logique métier
    ├── or_tools_vrp_solver.py      # Solveur VRP
    ├── two_phase_optimizer.py      # Orchestrateur 2 phases
    ├── osrm_distance_matrix.py     # Matrice de distances
    ├── solution_saver_v4.py        # Persistance solutions
    └── ...                         # Autres services
```

## Endpoints principaux

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `POST` | `/api/v1/tours/generate` | Générer les tournées du jour |
| `POST` | `/api/v1/tours/optimize/{route_id}` | Optimiser une tournée |
| `GET` | `/api/v1/tours/{route_id}` | Récupérer une tournée |
| `DELETE` | `/api/v1/tours/{route_id}` | Supprimer une tournée |

## Documentation API

Une fois l'API lancée :
- **Swagger UI** : http://localhost:8000/docs
- **ReDoc** : http://localhost:8000/redoc

## Tests

```bash
source venv/bin/activate
python3 -m pytest                    # Tous les tests
python3 -m pytest -v                 # Mode verbeux
python3 -m pytest tests/unit/        # Tests unitaires uniquement
```

## Déploiement sur nouveau VPS

1. **Préparer le serveur** :
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-venv python3-pip nginx -y
```

2. **Cloner et configurer** :
```bash
cd /srv
git clone https://github.com/blackrolf/provence-courses-api.git
cd provence-courses-api
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env  # Configurer les variables
```

3. **Configurer systemd et nginx** (voir sections ci-dessus)

4. **Configurer OSRM** (si nécessaire) :
```bash
# Voir documentation OSRM pour l'installation
# L'API s'attend à OSRM sur OSRM_URL
```

## Monitoring

```bash
# Logs en temps réel
./monitor_logs.sh
# ou
sudo journalctl -u provence-courses-api -f

# Statut du service
sudo systemctl status provence-courses-api
```

## Licence

Propriétaire - Tous droits réservés - Provence Courses
