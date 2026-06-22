"""Conexao ao cluster Cassandra e bootstrap do schema.

- Le os hosts e o keyspace das variaveis de ambiente (definidas no compose).
- Usa Consistency Level QUORUM por padrao: com RF=3, QUORUM=2, o sistema
  continua respondendo com 1 no fora do ar (item 7 - tolerancia a falhas).
- Cria keyspace e tabelas com IF NOT EXISTS (idempotente) no startup.
"""
import os
import time

from cassandra.cluster import Cluster
from cassandra.query import ConsistencyLevel
from cassandra.policies import DCAwareRoundRobinPolicy, TokenAwarePolicy

HOSTS = os.getenv("CASSANDRA_HOSTS", "cassandra1,cassandra2,cassandra3").split(",")
KEYSPACE = os.getenv("CASSANDRA_KEYSPACE", "ocorrencias")
REPLICATION_FACTOR = int(os.getenv("CASSANDRA_RF", "3"))

# DDL do keyspace + tabelas (espelha schema.cql). Mantido aqui para que a app
# seja auto-suficiente (basta `docker compose up`).
DDL = [
    f"""
    CREATE KEYSPACE IF NOT EXISTS {KEYSPACE}
      WITH replication = {{'class': 'SimpleStrategy',
                           'replication_factor': {REPLICATION_FACTOR}}}
    """,
    """
    CREATE TABLE IF NOT EXISTS eventos_por_id (
      id_evento text PRIMARY KEY, tipo text, descricao text, data_hora timestamp,
      gravidade int, status text, bairro text, cidade text,
      latitude double, longitude double, reportante_tipo text, reportante_id text)
    """,
    """
    CREATE TABLE IF NOT EXISTS eventos_por_tipo (
      tipo text, data_hora timestamp, id_evento text, descricao text, gravidade int,
      status text, bairro text, cidade text, latitude double, longitude double,
      reportante_tipo text, reportante_id text,
      PRIMARY KEY ((tipo), data_hora, id_evento))
      WITH CLUSTERING ORDER BY (data_hora DESC, id_evento ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS eventos_por_periodo (
      bucket_mes text, data_hora timestamp, id_evento text, tipo text, descricao text,
      gravidade int, status text, bairro text, cidade text, latitude double,
      longitude double, reportante_tipo text, reportante_id text,
      PRIMARY KEY ((bucket_mes), data_hora, id_evento))
      WITH CLUSTERING ORDER BY (data_hora ASC, id_evento ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS eventos_por_gravidade (
      gravidade int, data_hora timestamp, id_evento text, tipo text, descricao text,
      status text, bairro text, cidade text, latitude double, longitude double,
      reportante_tipo text, reportante_id text,
      PRIMARY KEY ((gravidade), data_hora, id_evento))
      WITH CLUSTERING ORDER BY (data_hora DESC, id_evento ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS eventos_por_cidade (
      cidade text, data_hora timestamp, id_evento text, tipo text, descricao text,
      gravidade int, status text, bairro text, latitude double, longitude double,
      reportante_tipo text, reportante_id text,
      PRIMARY KEY ((cidade), data_hora, id_evento))
      WITH CLUSTERING ORDER BY (data_hora DESC, id_evento ASC)
    """,
    "CREATE TABLE IF NOT EXISTS contagem_por_tipo (tipo text PRIMARY KEY, total counter)",
    """
    CREATE TABLE IF NOT EXISTS contagem_por_bairro (
      cidade text, bairro text, total counter, PRIMARY KEY ((cidade), bairro))
    """,
    """
    CREATE TABLE IF NOT EXISTS contagem_por_dia (
      ano int, dia date, total counter, PRIMARY KEY ((ano), dia))
      WITH CLUSTERING ORDER BY (dia ASC)
    """,
]


def conectar(max_tentativas: int = 30, espera_seg: int = 5):
    """Conecta ao cluster com retry e garante o schema. Retorna a Session."""
    perfil_consistencia = ConsistencyLevel.QUORUM
    ultimo_erro = None
    for tentativa in range(1, max_tentativas + 1):
        try:
            cluster = Cluster(
                contact_points=HOSTS,
                load_balancing_policy=TokenAwarePolicy(DCAwareRoundRobinPolicy()),
                protocol_version=5,
            )
            session = cluster.connect()
            session.default_consistency_level = perfil_consistencia
            _garantir_schema(session)
            session.set_keyspace(KEYSPACE)
            print(f"Conectado ao cluster Cassandra (hosts={HOSTS}, "
                  f"keyspace={KEYSPACE}, consistency=QUORUM).")
            return session
        except Exception as exc:  # noqa: BLE001 - retry amplo de bootstrap
            ultimo_erro = exc
            print(f"[{tentativa}/{max_tentativas}] cluster ainda nao pronto: {exc}")
            time.sleep(espera_seg)
    raise RuntimeError(f"Nao foi possivel conectar ao cluster: {ultimo_erro}")


def _garantir_schema(session) -> None:
    """Cria keyspace e tabelas (idempotente)."""
    for ddl in DDL:
        if "CREATE KEYSPACE" in ddl:
            session.execute(ddl)
            session.set_keyspace(KEYSPACE)
        else:
            session.execute(ddl)
