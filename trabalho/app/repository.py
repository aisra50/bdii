"""Camada de acesso a dados: insercoes e as consultas 6.1 a 6.6.

A insercao grava o evento de forma denormalizada nas 5 tabelas de evento
(via BATCH logado) e atualiza as 3 tabelas counter (separadamente, pois o
Cassandra nao mistura counters com colunas normais).
"""
from datetime import datetime, date

from cassandra.query import BatchStatement, ConsistencyLevel

from geo import haversine_km
from model import Evento, TIPOS, BAIRROS


class Repositorio:
    def __init__(self, session):
        self.s = session
        self._preparar()

    # ----------------------------------------------------------------- prepare
    def _preparar(self):
        s = self.s
        self.ins_id = s.prepare(
            "INSERT INTO eventos_por_id (id_evento,tipo,descricao,data_hora,gravidade,"
            "status,bairro,cidade,latitude,longitude,reportante_tipo,reportante_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)")
        self.ins_tipo = s.prepare(
            "INSERT INTO eventos_por_tipo (tipo,data_hora,id_evento,descricao,gravidade,"
            "status,bairro,cidade,latitude,longitude,reportante_tipo,reportante_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)")
        self.ins_periodo = s.prepare(
            "INSERT INTO eventos_por_periodo (bucket_mes,data_hora,id_evento,tipo,descricao,"
            "gravidade,status,bairro,cidade,latitude,longitude,reportante_tipo,reportante_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)")
        self.ins_grav = s.prepare(
            "INSERT INTO eventos_por_gravidade (gravidade,data_hora,id_evento,tipo,descricao,"
            "status,bairro,cidade,latitude,longitude,reportante_tipo,reportante_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)")
        self.ins_bairro = s.prepare(
            "INSERT INTO eventos_por_bairro (bairro,data_hora,id_evento,tipo,descricao,"
            "gravidade,status,cidade,latitude,longitude,reportante_tipo,reportante_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)")

        self.upd_cont_tipo = s.prepare(
            "UPDATE contagem_por_tipo SET total = total + 1 WHERE tipo = ?")
        self.upd_cont_bairro = s.prepare(
            "UPDATE contagem_por_bairro SET total = total + 1 WHERE cidade = ? AND bairro = ?")
        self.upd_cont_dia = s.prepare(
            "UPDATE contagem_por_dia SET total = total + 1 WHERE ano = ? AND dia = ?")

        self.q_tipo = s.prepare(
            "SELECT * FROM eventos_por_tipo WHERE tipo = ?")
        self.q_periodo = s.prepare(
            "SELECT * FROM eventos_por_periodo WHERE bucket_mes = ? "
            "AND data_hora >= ? AND data_hora <= ?")
        self.q_grav = s.prepare(
            "SELECT * FROM eventos_por_gravidade WHERE gravidade IN ?")
        self.q_bairro = s.prepare(
            "SELECT * FROM eventos_por_bairro WHERE bairro = ?")

        self.q_cont_tipo = s.prepare("SELECT tipo, total FROM contagem_por_tipo")
        self.q_cont_bairro = s.prepare(
            "SELECT bairro, total FROM contagem_por_bairro WHERE cidade = ?")
        self.q_cont_dia = s.prepare(
            "SELECT dia, total FROM contagem_por_dia WHERE ano = ?")

    # ------------------------------------------------------------------ 6.1 INSERT
    def inserir(self, e: Evento) -> None:
        """Grava o evento nas tabelas denormalizadas + contadores."""
        lote = BatchStatement(consistency_level=ConsistencyLevel.QUORUM)
        lote.add(self.ins_id, (e.id_evento, e.tipo, e.descricao, e.data_hora, e.gravidade,
                               e.status, e.bairro, e.cidade, e.latitude, e.longitude,
                               e.reportante_tipo, e.reportante_id))
        lote.add(self.ins_tipo, (e.tipo, e.data_hora, e.id_evento, e.descricao, e.gravidade,
                                 e.status, e.bairro, e.cidade, e.latitude, e.longitude,
                                 e.reportante_tipo, e.reportante_id))
        lote.add(self.ins_periodo, (e.bucket_mes, e.data_hora, e.id_evento, e.tipo, e.descricao,
                                    e.gravidade, e.status, e.bairro, e.cidade, e.latitude,
                                    e.longitude, e.reportante_tipo, e.reportante_id))
        lote.add(self.ins_grav, (e.gravidade, e.data_hora, e.id_evento, e.tipo, e.descricao,
                                 e.status, e.bairro, e.cidade, e.latitude, e.longitude,
                                 e.reportante_tipo, e.reportante_id))
        lote.add(self.ins_bairro, (e.bairro, e.data_hora, e.id_evento, e.tipo, e.descricao,
                                   e.gravidade, e.status, e.cidade, e.latitude, e.longitude,
                                   e.reportante_tipo, e.reportante_id))
        self.s.execute(lote)

        # Contadores (tabelas counter -> updates separados do batch normal).
        dia = e.data_hora.date()
        self.s.execute(self.upd_cont_tipo, (e.tipo,))
        self.s.execute(self.upd_cont_bairro, (e.cidade, e.bairro))
        self.s.execute(self.upd_cont_dia, (dia.year, dia))

    # ------------------------------------------------------------------ 6.2 TIPO
    def consultar_por_tipo(self, tipo: str) -> list:
        return list(self.s.execute(self.q_tipo, (tipo,)))

    # ------------------------------------------------------------------ 6.3 PERIODO
    def consultar_por_periodo(self, ini: datetime, fim: datetime) -> list:
        resultado = []
        for bucket in _buckets_mes(ini, fim):
            resultado.extend(self.s.execute(self.q_periodo, (bucket, ini, fim)))
        resultado.sort(key=lambda r: r.data_hora)
        return resultado

    # ------------------------------------------------------------------ 6.4 GEO
    def consultar_geografico(self, lat: float, lon: float, raio_km: float) -> list:
        """Filtra bairros candidatos pelo centro e aplica haversine nos eventos de cada um."""
        bairros_candidatos = [
            b for b, (blat, blon) in BAIRROS.items()
            if haversine_km(lat, lon, blat, blon) <= raio_km + 2.0
        ]
        proximos = []
        for bairro in bairros_candidatos:
            for r in self.s.execute(self.q_bairro, (bairro,)):
                dist = haversine_km(lat, lon, r.latitude, r.longitude)
                if dist <= raio_km:
                    proximos.append((dist, r))
        proximos.sort(key=lambda par: par[0])
        return proximos  # lista de (distancia_km, row)

    # ------------------------------------------------------------------ 6.5 GRAVIDADE
    def consultar_por_gravidade(self, limite_exclusivo: int) -> list:
        """gravidade > limite -> consulta os niveis discretos acima dele (1..5)."""
        niveis = [g for g in range(1, 6) if g > limite_exclusivo]
        if not niveis:
            return []
        rows = list(self.s.execute(self.q_grav, (niveis,)))
        rows.sort(key=lambda r: (r.gravidade, r.data_hora), reverse=True)
        return rows

    # ------------------------------------------------------------------ 6.6 ESTATISTICAS
    def estatisticas_por_tipo(self) -> list:
        linhas = [(r.tipo, r.total) for r in self.s.execute(self.q_cont_tipo)]
        linhas.sort(key=lambda x: x[1], reverse=True)
        return linhas

    def estatisticas_por_bairro(self, cidade: str) -> list:
        linhas = [(r.bairro, r.total) for r in self.s.execute(self.q_cont_bairro, (cidade,))]
        linhas.sort(key=lambda x: x[1], reverse=True)
        return linhas

    def evolucao_por_dia(self, ano: int) -> list:
        return [(r.dia, r.total) for r in self.s.execute(self.q_cont_dia, (ano,))]


def _buckets_mes(ini: datetime, fim: datetime) -> list:
    """Lista de buckets 'YYYY-MM' entre ini e fim (inclusive)."""
    buckets = []
    ano, mes = ini.year, ini.month
    while (ano, mes) <= (fim.year, fim.month):
        buckets.append(f"{ano:04d}-{mes:02d}")
        mes += 1
        if mes > 12:
            mes = 1
            ano += 1
    return buckets
