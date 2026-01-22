"""
Exceptions spécifiques à la génération de tournées
"""


class TourGenerationError(Exception):
    """Erreur générale lors de la génération de tournées"""
    pass


class ClientWithoutDriverError(Exception):
    """Erreur quand un client n'a pas de driver assigné"""
    
    def __init__(self, client_id: str, client_name: str = None):
        self.client_id = client_id
        self.client_name = client_name
        message = f"Client '{client_name}' (ID: {client_id}) n'a pas de livreur assigné"
        super().__init__(message)


class DataRetrievalError(Exception):
    """Erreur lors de la récupération des données depuis Supabase"""
    pass


class RouteCreationError(Exception):
    """Erreur lors de la création d'une tournée en base"""
    pass


class ShipmentMappingError(Exception):
    """Erreur lors du mapping des shipments vers les stops"""
    pass