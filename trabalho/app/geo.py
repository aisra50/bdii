"""Calculo de distancia geografica (Cassandra nao possui geo nativo).

Usado pela consulta 6.4: dado um ponto (lat, lon) e um raio em km, filtramos
os eventos candidatos na aplicacao com a formula de Haversine.
"""
from math import radians, sin, cos, asin, sqrt

RAIO_TERRA_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia em km entre dois pontos (lat/lon em graus) sobre a esfera."""
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * RAIO_TERRA_KM * asin(sqrt(a))
