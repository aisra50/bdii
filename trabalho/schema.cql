-- ============================================================================
-- Esquema da plataforma de Ocorrencias Urbanas (Apache Cassandra)
-- ----------------------------------------------------------------------------
-- Modelagem ORIENTADA A CONSULTAS (query-first): uma tabela por padrao de
-- consulta. Cada evento e gravado de forma DENORMALIZADA em varias tabelas.
--
-- Este arquivo serve como referencia/documentacao. A aplicacao (app/db.py)
-- tambem cria tudo com IF NOT EXISTS no startup, entao rodar este script
-- manualmente e OPCIONAL. Para aplicar manualmente:
--   docker compose exec cassandra1 cqlsh -f /schema.cql
-- ============================================================================

-- Keyspace com replicacao em 3 nos => o dado existe em mais de um servidor.
-- RF=3 + Consistency QUORUM (na app) tolera 1 no fora do ar.
CREATE KEYSPACE IF NOT EXISTS ocorrencias
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 3};

USE ocorrencias;

-- Registro canonico, acesso direto por id (6.1 / consulta pontual).
CREATE TABLE IF NOT EXISTS eventos_por_id (
  id_evento       text PRIMARY KEY,
  tipo            text,
  descricao       text,
  data_hora       timestamp,
  gravidade       int,
  status          text,
  bairro          text,
  cidade          text,
  latitude        double,
  longitude       double,
  reportante_tipo text,
  reportante_id   text
);

-- 6.2 Consulta por tipo: "listar todos os alagamentos".
CREATE TABLE IF NOT EXISTS eventos_por_tipo (
  tipo            text,
  data_hora       timestamp,
  id_evento       text,
  descricao       text,
  gravidade       int,
  status          text,
  bairro          text,
  cidade          text,
  latitude        double,
  longitude       double,
  reportante_tipo text,
  reportante_id   text,
  PRIMARY KEY ((tipo), data_hora, id_evento)
) WITH CLUSTERING ORDER BY (data_hora DESC, id_evento ASC);

-- 6.3 Consulta por periodo: particionado por mes (bucket 'YYYY-MM') para
-- limitar o tamanho da particao; a app varre os meses do intervalo pedido.
CREATE TABLE IF NOT EXISTS eventos_por_periodo (
  bucket_mes      text,
  data_hora       timestamp,
  id_evento       text,
  tipo            text,
  descricao       text,
  gravidade       int,
  status          text,
  bairro          text,
  cidade          text,
  latitude        double,
  longitude       double,
  reportante_tipo text,
  reportante_id   text,
  PRIMARY KEY ((bucket_mes), data_hora, id_evento)
) WITH CLUSTERING ORDER BY (data_hora ASC, id_evento ASC);

-- 6.5 Consulta por gravidade: gravidade 1..5 como chave de particao.
-- "gravidade > 3" => a app consulta WHERE gravidade IN (4,5).
CREATE TABLE IF NOT EXISTS eventos_por_gravidade (
  gravidade       int,
  data_hora       timestamp,
  id_evento       text,
  tipo            text,
  descricao       text,
  status          text,
  bairro          text,
  cidade          text,
  latitude        double,
  longitude       double,
  reportante_tipo text,
  reportante_id   text,
  PRIMARY KEY ((gravidade), data_hora, id_evento)
) WITH CLUSTERING ORDER BY (data_hora DESC, id_evento ASC);

-- 6.4 Consulta geografica: sem geo nativo no Cassandra. A app puxa os
-- candidatos por cidade e filtra por distancia (haversine) na aplicacao.
CREATE TABLE IF NOT EXISTS eventos_por_cidade (
  cidade          text,
  data_hora       timestamp,
  id_evento       text,
  tipo            text,
  descricao       text,
  gravidade       int,
  status          text,
  bairro          text,
  latitude        double,
  longitude       double,
  reportante_tipo text,
  reportante_id   text,
  PRIMARY KEY ((cidade), data_hora, id_evento)
) WITH CLUSTERING ORDER BY (data_hora DESC, id_evento ASC);

-- 6.6 Estatisticas (tabelas counter, atualizadas a cada insercao).
-- Counters precisam de tabela exclusiva (nao misturam com colunas normais).

-- Quantidade por tipo.
CREATE TABLE IF NOT EXISTS contagem_por_tipo (
  tipo   text PRIMARY KEY,
  total  counter
);

-- Quantidade por bairro (particionado por cidade; clustering por bairro =>
-- "SELECT * WHERE cidade=?" retorna todos os bairros com seus totais).
CREATE TABLE IF NOT EXISTS contagem_por_bairro (
  cidade text,
  bairro text,
  total  counter,
  PRIMARY KEY ((cidade), bairro)
);

-- Evolucao temporal: quantidade por dia (particionado por ano).
CREATE TABLE IF NOT EXISTS contagem_por_dia (
  ano    int,
  dia    date,
  total  counter,
  PRIMARY KEY ((ano), dia)
) WITH CLUSTERING ORDER BY (dia ASC);
