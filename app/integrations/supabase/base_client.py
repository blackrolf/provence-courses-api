"""
Client HTTP de base pour Supabase - opérations CRUD fondamentales
"""

import requests
import structlog
from typing import Dict, List, Optional, Any
from app.core.config import settings

logger = structlog.get_logger()


class SupabaseBaseClient:
    """Client HTTP de base pour les opérations CRUD Supabase"""
    
    def __init__(self):
        self.base_url = settings.supabase_url
        self.service_key = settings.supabase_service_role_key
        self.anon_key = settings.supabase_anon_key
        
        # Headers par défaut avec service role (accès complet)
        self.headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": "application/json"
        }
    
    def test_connection(self) -> Dict[str, Any]:
        """Test de connexion à Supabase"""
        try:
            response = requests.get(
                f"{self.base_url}/rest/v1/drivers",
                headers=self.headers,
                params={"limit": 1}
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "status": "success",
                    "message": "Connexion Supabase réussie",
                    "data_sample": data
                }
            else:
                return {
                    "status": "error",
                    "message": f"Erreur HTTP {response.status_code}: {response.text}"
                }
                
        except Exception as e:
            return {
                "status": "error",
                "message": f"Erreur de connexion: {str(e)}"
            }
    
    def select(self, table: str, columns: str = "*", **filters) -> Dict[str, Any]:
        """
        Sélectionner des données d'une table
        
        Args:
            table: Nom de la table
            columns: Colonnes à sélectionner (défaut: "*")
            **filters: Filtres à appliquer (ex: id="eq.123", name="ilike.*test*")
        """
        try:
            url = f"{self.base_url}/rest/v1/{table}"
            params = {"select": columns}
            
            # Ajouter les filtres
            for key, value in filters.items():
                if value.startswith("eq.") or value.startswith("ilike.") or value.startswith("in."):
                    params[key] = value
                else:
                    # Égalité par défaut
                    params[key] = f"eq.{value}"
            
            response = requests.get(url, headers=self.headers, params=params)
            
            if response.status_code == 200:
                return {
                    "status": "success",
                    "data": response.json()
                }
            else:
                return {
                    "status": "error",
                    "message": f"Erreur {response.status_code}: {response.text}"
                }
                
        except Exception as e:
            return {
                "status": "error",
                "message": f"Erreur lors de la sélection: {str(e)}"
            }
    
    def insert(self, table: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Insérer des données dans une table
        
        Args:
            table: Nom de la table
            data: Données à insérer
        """
        try:
            url = f"{self.base_url}/rest/v1/{table}"
            
            # Headers avec Prefer pour récupérer les données insérées
            insert_headers = {
                **self.headers,
                "Prefer": "return=representation"
            }
            
            response = requests.post(url, headers=insert_headers, json=data)
            
            if response.status_code in [200, 201]:
                # Gérer les réponses vides
                if response.text.strip():
                    return {
                        "status": "success",
                        "data": response.json()
                    }
                else:
                    return {
                        "status": "success",
                        "data": [],
                        "message": "Insertion réussie (pas de données retournées)"
                    }
            else:
                return {
                    "status": "error",
                    "message": f"Erreur {response.status_code}: {response.text}"
                }
                
        except Exception as e:
            return {
                "status": "error",
                "message": f"Erreur lors de l'insertion: {str(e)}"
            }
    
    def update(self, table: str, data: Dict[str, Any], **filters) -> Dict[str, Any]:
        """
        Mettre à jour des données dans une table
        
        Args:
            table: Nom de la table
            data: Données à mettre à jour
            **filters: Filtres pour identifier les lignes (ex: id="123")
        """
        try:
            url = f"{self.base_url}/rest/v1/{table}"
            params = {}
            
            # Ajouter les filtres
            for key, value in filters.items():
                if isinstance(value, str) and value.startswith("eq."):
                    params[key] = value
                else:
                    params[key] = f"eq.{value}"
            
            response = requests.patch(url, headers=self.headers, params=params, json=data)
            
            if response.status_code in [200, 204]:
                # 200: OK with data, 204: No Content (successful update)
                data = response.json() if response.status_code == 200 and response.text else []
                return {
                    "status": "success",
                    "data": data
                }
            else:
                return {
                    "status": "error",
                    "message": f"Erreur {response.status_code}: {response.text}"
                }
                
        except Exception as e:
            return {
                "status": "error",
                "message": f"Erreur lors de la mise à jour: {str(e)}"
            }
    
    def delete(self, table: str, **filters) -> Dict[str, Any]:
        """
        Supprimer des données d'une table
        
        Args:
            table: Nom de la table
            **filters: Filtres pour identifier les lignes (ex: id="123")
        """
        try:
            url = f"{self.base_url}/rest/v1/{table}"
            params = {}
            
            # Ajouter les filtres
            for key, value in filters.items():
                if isinstance(value, str) and value.startswith("eq."):
                    params[key] = value
                else:
                    params[key] = f"eq.{value}"
            
            # Ajouter le header Prefer pour retourner les lignes supprimées
            headers_with_prefer = self.headers.copy()
            headers_with_prefer["Prefer"] = "return=representation"
            
            response = requests.delete(url, headers=headers_with_prefer, params=params)
            
            if response.status_code == 200:
                return {
                    "status": "success",
                    "data": response.json()
                }
            else:
                return {
                    "status": "error",
                    "message": f"Erreur {response.status_code}: {response.text}"
                }
                
        except Exception as e:
            return {
                "status": "error",
                "message": f"Erreur lors de la suppression: {str(e)}"
            }
    
    def execute_rpc(self, function_name: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Exécute une fonction RPC Supabase
        
        Args:
            function_name: Nom de la fonction RPC
            params: Paramètres de la fonction
        """
        try:
            url = f"{self.base_url}/rpc/{function_name}"
            
            response = requests.post(
                url, 
                headers=self.headers, 
                json=params or {}
            )
            
            if response.status_code == 200:
                return {
                    "status": "success",
                    "data": response.json()
                }
            else:
                return {
                    "status": "error",
                    "message": f"Erreur RPC {response.status_code}: {response.text}"
                }
                
        except Exception as e:
            return {
                "status": "error",
                "message": f"Erreur lors de l'exécution RPC: {str(e)}"
            }


# Instance globale
supabase_base_client = SupabaseBaseClient()