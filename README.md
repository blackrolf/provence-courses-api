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
- Docker & Docker Compose (recommandé)
- Compte Supabase avec base de données configurée

---

## Installation rapide avec Docker (Recommandé)

```bash
# 1. Cloner le repository
git clone https://github.com/blackrolf/provence-courses-api.git
cd provence-courses-api

# 2. Configurer les variables d'environnement
cp .env.example .env
nano .env  # Remplir les valeurs

# 3. Lancer avec Docker Compose (API + OSRM)
docker-compose up -d

# 4. Vérifier que tout fonctionne
docker-compose ps
curl http://localhost:8000/docs
```

L'API sera disponible sur http://localhost:8000

---

## Installation manuelle

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

---

## Installation OSRM avec carte PACA

OSRM (Open Source Routing Machine) est nécessaire pour calculer les distances et temps de trajet. Voici comment l'installer avec la carte de la région PACA.

### Option 1 : Installation Docker (Recommandé)

```bash
# Créer le dossier pour les données OSRM
mkdir -p /srv/osrm-data
cd /srv/osrm-data

# Télécharger la carte PACA depuis Geofabrik
wget https://download.geofabrik.de/europe/france/provence-alpes-cote-d-azur-latest.osm.pbf

# Extraire le profil de routing (voiture)
docker run -t -v "${PWD}:/data" osrm/osrm-backend osrm-extract -p /opt/car.lua /data/provence-alpes-cote-d-azur-latest.osm.pbf

# Partitionner les données
docker run -t -v "${PWD}:/data" osrm/osrm-backend osrm-partition /data/provence-alpes-cote-d-azur-latest.osrm

# Personnaliser les données
docker run -t -v "${PWD}:/data" osrm/osrm-backend osrm-customize /data/provence-alpes-cote-d-azur-latest.osrm

# Lancer le serveur OSRM
docker run -d --name osrm-paca \
  -p 5000:5000 \
  -v "${PWD}:/data" \
  --restart unless-stopped \
  osrm/osrm-backend osrm-routed --algorithm mld /data/provence-alpes-cote-d-azur-latest.osrm

# Vérifier que OSRM fonctionne
curl "http://localhost:5000/route/v1/driving/5.3698,43.2965;5.4510,43.5283?overview=false"
```

### Option 2 : Installation native (Ubuntu/Debian)

```bash
# Installer les dépendances
sudo apt install build-essential git cmake pkg-config \
  libbz2-dev libxml2-dev libzip-dev libboost-all-dev \
  lua5.2 liblua5.2-dev libtbb-dev -y

# Cloner et compiler OSRM
git clone https://github.com/Project-OSRM/osrm-backend.git
cd osrm-backend
mkdir build && cd build
cmake ..
make -j$(nproc)
sudo make install

# Télécharger et préparer la carte PACA
mkdir -p /srv/osrm-data && cd /srv/osrm-data
wget https://download.geofabrik.de/europe/france/provence-alpes-cote-d-azur-latest.osm.pbf

osrm-extract -p /usr/local/share/osrm/profiles/car.lua provence-alpes-cote-d-azur-latest.osm.pbf
osrm-partition provence-alpes-cote-d-azur-latest.osrm
osrm-customize provence-alpes-cote-d-azur-latest.osrm

# Lancer OSRM
osrm-routed --algorithm mld provence-alpes-cote-d-azur-latest.osrm
```

### Service systemd pour OSRM

```bash
sudo nano /etc/systemd/system/osrm.service
```

```ini
[Unit]
Description=OSRM Routing Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/srv/osrm-data
ExecStart=/usr/bin/docker run --rm -p 5000:5000 -v /srv/osrm-data:/data osrm/osrm-backend osrm-routed --algorithm mld /data/provence-alpes-cote-d-azur-latest.osrm
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable osrm
sudo systemctl start osrm
```

---

## Dockerisation complète

### Structure Docker

```
provence-courses-api/
├── Dockerfile              # Image de l'API
├── docker-compose.yml      # Orchestration API + OSRM
└── deployment/
    └── docker/
        └── osrm/
            └── Dockerfile  # Image OSRM personnalisée (optionnel)
```

### Dockerfile (API)

Le `Dockerfile` à la racine du projet permet de construire l'image de l'API :

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Installer les dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copier et installer les dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code source
COPY app/ ./app/

# Exposer le port
EXPOSE 8000

# Lancer l'application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### docker-compose.yml

```yaml
version: '3.8'

services:
  api:
    build: .
    container_name: provence-courses-api
    ports:
      - "8000:8000"
    environment:
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_ANON_KEY=${SUPABASE_ANON_KEY}
      - SUPABASE_SERVICE_ROLE_KEY=${SUPABASE_SERVICE_ROLE_KEY}
      - OSRM_URL=http://osrm:5000
      - API_KEY=${API_KEY}
      - GOOGLE_MAPS_API_KEY=${GOOGLE_MAPS_API_KEY:-}
    depends_on:
      - osrm
    restart: unless-stopped
    networks:
      - provence-network

  osrm:
    image: osrm/osrm-backend
    container_name: osrm-paca
    ports:
      - "5000:5000"
    volumes:
      - ./osrm-data:/data
    command: osrm-routed --algorithm mld /data/provence-alpes-cote-d-azur-latest.osrm
    restart: unless-stopped
    networks:
      - provence-network

networks:
  provence-network:
    driver: bridge
```

### Commandes Docker utiles

```bash
# Construire et lancer
docker-compose up -d --build

# Voir les logs
docker-compose logs -f api
docker-compose logs -f osrm

# Arrêter
docker-compose down

# Reconstruire l'API après modifications
docker-compose up -d --build api

# Entrer dans le conteneur API
docker exec -it provence-courses-api bash

# Vérifier l'état
docker-compose ps
```

### Préparation des données OSRM pour Docker Compose

Avant de lancer `docker-compose up`, préparer les données OSRM :

```bash
# Créer le dossier
mkdir -p osrm-data && cd osrm-data

# Télécharger la carte PACA
wget https://download.geofabrik.de/europe/france/provence-alpes-cote-d-azur-latest.osm.pbf

# Préparer les données (une seule fois)
docker run -t -v "${PWD}:/data" osrm/osrm-backend osrm-extract -p /opt/car.lua /data/provence-alpes-cote-d-azur-latest.osm.pbf
docker run -t -v "${PWD}:/data" osrm/osrm-backend osrm-partition /data/provence-alpes-cote-d-azur-latest.osrm
docker run -t -v "${PWD}:/data" osrm/osrm-backend osrm-customize /data/provence-alpes-cote-d-azur-latest.osrm

cd ..

# Maintenant lancer docker-compose
docker-compose up -d
```

---

## Utilisation

### Mode développement (sans Docker)

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

### Configuration Nginx (reverse proxy)

```bash
sudo cp deployment/nginx/api.provence-courses.fr /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/api.provence-courses.fr /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

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

## Monitoring

```bash
# Logs en temps réel (systemd)
./monitor_logs.sh
sudo journalctl -u provence-courses-api -f

# Logs Docker
docker-compose logs -f

# Statut
sudo systemctl status provence-courses-api  # systemd
docker-compose ps                            # Docker
```

## Licence

Propriétaire - Tous droits réservés - Provence Courses
