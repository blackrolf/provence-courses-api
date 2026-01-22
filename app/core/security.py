"""
Gestion de la sécurité API - X-API-KEY
"""

from fastapi import HTTPException, Header, status
from typing import Optional
from app.core.config import settings


# Liste des clés API autorisées (à configurer via variables d'environnement)
def get_valid_api_keys():
    """Récupère les clés API valides depuis la configuration"""
    valid_keys = ["provence-courses-api-key-2025"]  # Clé par défaut
    
    # Ajouter la clé depuis l'environnement si présente
    if settings.api_key:
        valid_keys.append(settings.api_key)
    
    return valid_keys


async def verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-KEY")):
    """
    Vérifie la validité de la clé API dans le header X-API-KEY
    
    Args:
        x_api_key: Clé API fournie dans le header
        
    Raises:
        HTTPException: Si la clé est manquante ou invalide
        
    Returns:
        str: La clé API validée
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-KEY header manquant",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    if x_api_key not in get_valid_api_keys():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="X-API-KEY invalide",
        )
    
    return x_api_key


def get_api_key_from_env() -> str:
    """
    Récupère la clé API depuis les variables d'environnement
    Utile pour les tests ou la configuration dynamique
    """
    return getattr(settings, 'api_key', get_valid_api_keys()[0])