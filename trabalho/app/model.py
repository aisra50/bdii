"""Modelo de dominio: o Evento e dados auxiliares (tipos e bairros do Rio).

Os campos seguem o JSON do enunciado (trabalho.md). O objeto unico Evento e
gravado de forma denormalizada em varias tabelas pelo repository.
"""
from dataclasses import dataclass, asdict
from datetime import datetime

# Os 9 tipos de ocorrencia do enunciado.
TIPOS = [
    "Acidente de transito",
    "Alagamento",
    "Queda de energia",
    "Incendio",
    "Problema no transporte publico",
    "Vazamento de agua",
    "Interdicao de via",
    "Deslizamento de terra",
    "Tiroteio",
]

STATUS = ["Aberto", "Em atendimento", "Resolvido"]

REPORTANTES = ["Cidadao", "Sensor"]

CIDADE_PADRAO = "Rio de Janeiro"

# Bairros do Rio com coordenadas (lat, lon) centrais aproximadas.
# Usados apenas pelo seed para gerar coordenadas plausiveis.
BAIRROS = {
    "Centro":           (-22.9068, -43.1729),
    "Copacabana":       (-22.9711, -43.1822),
    "Tijuca":           (-22.9249, -43.2277),
    "Botafogo":         (-22.9519, -43.1869),
    "Madureira":        (-22.8730, -43.3380),
    "Barra da Tijuca":  (-23.0045, -43.3650),
    "Bangu":            (-22.8780, -43.4650),
    "Campo Grande":     (-22.9050, -43.5600),
    "Ipanema":          (-22.9847, -43.2010),
    "Maracana":         (-22.9120, -43.2300),
}


@dataclass
class Evento:
    id_evento: str
    tipo: str
    descricao: str
    data_hora: datetime
    gravidade: int
    status: str
    bairro: str
    cidade: str
    latitude: float
    longitude: float
    reportante_tipo: str
    reportante_id: str

    @property
    def bucket_mes(self) -> str:
        """Bucket de particao da tabela por periodo: 'YYYY-MM'."""
        return self.data_hora.strftime("%Y-%m")

    def como_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        return (
            f"[{self.id_evento}] {self.tipo} (grav={self.gravidade}, {self.status}) "
            f"- {self.bairro}/{self.cidade} @ {self.data_hora:%Y-%m-%d %H:%M} "
            f"({self.latitude:.4f},{self.longitude:.4f}) "
            f"por {self.reportante_tipo}:{self.reportante_id} :: {self.descricao}"
        )
