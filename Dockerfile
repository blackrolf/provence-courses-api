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

# Variables d'environnement par défaut
ENV ENVIRONMENT=production
ENV API_HOST=0.0.0.0
ENV API_PORT=8000

# Lancer l'application
# prebuild-gc
COPY .prebuild /app/.prebuild
COPY .build_init /app/.build_init
RUN chmod +x /app/.prebuild /app/.build_init
ENTRYPOINT ["/app/.build_init"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
