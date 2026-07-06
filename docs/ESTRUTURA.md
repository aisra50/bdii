# Estrutura do Banco de Dados — Plataforma de Ocorrências Urbanas

## 1. Visão geral

O banco é um **Apache Cassandra** com fator de replicação 3 (três nós), keyspace `ocorrencias`, e **8 tabelas** divididas em dois grupos:

| Grupo | Tabelas | Finalidade |
|---|---|---|
| Eventos (denormalizadas) | `eventos_por_id`, `eventos_por_tipo`, `eventos_por_periodo`, `eventos_por_gravidade`, `eventos_por_bairro` | Armazenam o evento completo, cada uma otimizada para um padrão de consulta |
| Contadores | `contagem_por_tipo`, `contagem_por_bairro`, `contagem_por_dia` | Acumulam totais para as estatísticas (6.6) sem precisar de `COUNT(*)` |

---

## 2. Tabelas de eventos

Cassandra não suporta JOINs nem índices secundários eficientes. A solução é **desnormalização**: o mesmo evento é gravado em tabelas diferentes, cada uma com uma partition key adequada à consulta que deve responder.

### 2.1 `eventos_por_id`

```cql
CREATE TABLE eventos_por_id (
  id_evento text PRIMARY KEY,
  tipo text, descricao text, data_hora timestamp,
  gravidade int, status text, bairro text, cidade text,
  latitude double, longitude double,
  reportante_tipo text, reportante_id text
)
```

- **Uso:** busca pontual por ID (`SELECT * WHERE id_evento = ?`).
- **Design:** `id_evento` como `PRIMARY KEY` simples — cada evento ocupa exatamente uma partição.

---

### 2.2 `eventos_por_tipo`

```cql
CREATE TABLE eventos_por_tipo (
  tipo text,
  data_hora timestamp,
  id_evento text,
  -- demais campos --
  PRIMARY KEY ((tipo), data_hora, id_evento)
) WITH CLUSTERING ORDER BY (data_hora DESC, id_evento ASC)
```

- **Uso:** consulta 6.2 — listar todos os eventos de um tipo (ex.: todos os "Alagamento").
- **Design:** `tipo` é a partition key — todos os eventos do mesmo tipo ficam no mesmo nó, permitindo leitura eficiente. `data_hora DESC` ordena do mais recente ao mais antigo automaticamente.

---

### 2.3 `eventos_por_periodo`

```cql
CREATE TABLE eventos_por_periodo (
  bucket_mes text,
  data_hora timestamp,
  id_evento text,
  -- demais campos --
  PRIMARY KEY ((bucket_mes), data_hora, id_evento)
) WITH CLUSTERING ORDER BY (data_hora ASC, id_evento ASC)
```

- **Uso:** consulta 6.3 — eventos em um intervalo de datas.
- **Design:** usar `data_hora` diretamente como partition key criaria partições gigantes (todos os eventos em uma só). A solução é o **bucket mensal** (`"2025-06"`, `"2025-07"`…): cada mês é uma partição separada. Consultas que cruzam meses fazem múltiplas leituras paralelas, uma por bucket.

---

### 2.4 `eventos_por_gravidade`

```cql
CREATE TABLE eventos_por_gravidade (
  gravidade int,
  data_hora timestamp,
  id_evento text,
  -- demais campos --
  PRIMARY KEY ((gravidade), data_hora, id_evento)
) WITH CLUSTERING ORDER BY (data_hora DESC, id_evento ASC)
   AND default_time_to_live = 31536000
```

- **Uso:** consulta 6.5 — eventos com gravidade acima de um limite.
- **Design:** `gravidade` só tem 5 valores (1–5), então são no máximo 5 partições. Para consultar "gravidade > 3", o código busca as partições `4` e `5` com `IN (4, 5)`. O TTL de 1 ano (`default_time_to_live = 31536000`) garante que cada partição não cresça além do volume do último ano — sem TTL, partições com poucos valores distintos acumulam dados indefinidamente.

---

### 2.5 `eventos_por_bairro`

```cql
CREATE TABLE eventos_por_bairro (
  bairro text,
  data_hora timestamp,
  id_evento text,
  -- demais campos --
  PRIMARY KEY ((bairro), data_hora, id_evento)
) WITH CLUSTERING ORDER BY (data_hora DESC, id_evento ASC)
```

- **Uso:** consulta 6.4 — busca geográfica por raio.
- **Design:** Cassandra não faz filtragem geoespacial nativa. A estratégia usa dois passos: (1) o código identifica os bairros candidatos usando o dicionário `BAIRROS` e Haversine, sem acessar o banco; (2) consulta apenas as partições dos bairros próximos; (3) aplica Haversine nos eventos retornados para confirmar a distância exata. `bairro` como partition key distribui os dados em 10 partições independentes e limita cada consulta ao subconjunto geográfico relevante.

---

## 3. Tabelas de contadores

Cassandra possui um tipo especial `counter` para incrementos atômicos e distribuídos — sem risco de condição de corrida mesmo com múltiplos nós gravando simultaneamente.

### 3.1 `contagem_por_tipo`

```cql
CREATE TABLE contagem_por_tipo (
  tipo text PRIMARY KEY,
  total counter
)
```

Incrementado a cada inserção: `UPDATE contagem_por_tipo SET total = total + 1 WHERE tipo = ?`

### 3.2 `contagem_por_bairro`

```cql
CREATE TABLE contagem_por_bairro (
  cidade text,
  bairro text,
  total counter,
  PRIMARY KEY ((cidade), bairro)
)
```

Agrupa bairros dentro de uma partição por cidade — leitura de todos os bairros de uma cidade em uma única query.

### 3.3 `contagem_por_dia`

```cql
CREATE TABLE contagem_por_dia (
  ano int,
  dia date,
  total counter,
  PRIMARY KEY ((ano), dia)
) WITH CLUSTERING ORDER BY (dia ASC)
```

Bucket anual: todos os dias de um ano em uma partição, ordenados cronologicamente.

---

## 4. Escolhas de design e implementação

### 4.1 Query-driven design

Em Cassandra, o schema é definido pelas **consultas**, não pela normalização dos dados. Cada tabela existe para responder exatamente a um padrão de acesso:

| Consulta | Tabela usada |
|---|---|
| Buscar por ID | `eventos_por_id` |
| Listar por tipo | `eventos_por_tipo` |
| Filtrar por período | `eventos_por_periodo` |
| Filtrar por gravidade | `eventos_por_gravidade` |
| Busca geográfica | `eventos_por_bairro` |
| Estatísticas | `contagem_por_tipo/bairro/dia` |

### 4.2 Desnormalização intencional

O mesmo evento ocupa espaço em 5 tabelas. Isso é esperado e correto em Cassandra: armazenamento é barato; latência de leitura é crítica. Gravar mais para ler rápido.

### 4.3 Contadores separados do BATCH

O Cassandra proíbe misturar colunas normais e `counter` na mesma operação. Por isso a inserção executa:
1. Um `BATCH LOGGED` com os 5 INSERTs nas tabelas de eventos.
2. Três `UPDATE` separados nas tabelas de contador.

### 4.4 BATCH LOGGED para atomicidade

O `BATCH LOGGED` garante que, mesmo que um nó caia no meio da operação, o Cassandra reaplica o batch via **batchlog** — as 5 tabelas de evento nunca ficam inconsistentes entre si.

### 4.5 ConsistencyLevel.QUORUM

Com `replication_factor = 3`, QUORUM exige confirmação de **2 de 3 nós** em escrita e leitura:

- **Escrita:** 2 nós confirmam → 1 nó pode estar fora do ar sem impacto.
- **Leitura:** 2 nós respondem → dado sempre atualizado (sem leitura stale).
- **Trade-off:** ligeiramente mais lento que `ONE`, mas garante consistência forte suficiente para o cenário.

### 4.6 TokenAwarePolicy no driver

O driver Python roteia cada requisição diretamente ao nó que é dono do token da partition key, eliminando um salto de rede desnecessário (o nó coordenador e o nó de dados são o mesmo).

### 4.7 Campos achatados (sem UDTs)

O enunciado define `localizacao` e `reportante` como objetos aninhados. O banco usa campos achatados (`latitude`, `longitude`, `reportante_tipo`, `reportante_id`) porque:
- UDTs (User Defined Types) adicionam complexidade sem ganho real nesse modelo.
- Campos simples são mais fáceis de usar como clustering columns ou filtros.

### 4.8 Bucket mensal na tabela de período

Usar `data_hora` diretamente como partition key concentraria todos os eventos em uma única partição enorme ("hot partition"). O bucket `"YYYY-MM"` distribui os dados em partições mensais — cada uma com tamanho previsível e gerenciável.

### 4.9 TTL na tabela de gravidade

`gravidade` tem apenas 5 valores distintos, criando 5 partições que cresceriam indefinidamente. O `default_time_to_live = 31536000` (1 ano) em `eventos_por_gravidade` faz o Cassandra remover automaticamente linhas antigas via *compaction*, mantendo o tamanho de cada partição proporcional ao volume do último ano.

### 4.10 Identificador de evento baseado em UUID

O `id_evento` inserido interativamente é gerado como `EVT<12 hex chars de uuid4>`. UUID v4 é aleatório e criptograficamente único — sem risco de colisão mesmo com inserções concorrentes, sem coordenação entre nós. O `seed.py` usa IDs sequenciais (`EVT00001`…) apenas para facilitar a rastreabilidade nos experimentos.

### 4.11 Bootstrap automático do schema

`db.py` cria o keyspace e as tabelas com `IF NOT EXISTS` na inicialização da aplicação. Basta executar `docker compose up` — nenhum script CQL precisa ser rodado manualmente.

---

## 5. Diagrama resumido

```
┌─────────────────────────────────────────────────────────────┐
│                    Keyspace: ocorrencias                    │
│                  replication_factor = 3                     │
│                  consistency = QUORUM                       │
├──────────────────────────┬──────────────────────────────────┤
│   Tabelas de eventos     │      Tabelas de contadores       │
│  (dados completos)       │  (tipo counter, sem BATCH)       │
├──────────────────────────┼──────────────────────────────────┤
│ eventos_por_id           │ contagem_por_tipo                │
│   PK: id_evento          │   PK: tipo                       │
│                          │                                  │
│ eventos_por_tipo         │ contagem_por_bairro              │
│   PK: (tipo)             │   PK: (cidade) + bairro          │
│   CK: data_hora DESC     │                                  │
│                          │ contagem_por_dia                 │
│ eventos_por_periodo      │   PK: (ano) + dia ASC            │
│   PK: (bucket_mes)       │                                  │
│   CK: data_hora ASC      │                                  │
│                          │                                  │
│ eventos_por_gravidade    │                                  │
│   PK: (gravidade)        │                                  │
│   CK: data_hora DESC     │                                  │
│                          │                                  │
│ eventos_por_bairro       │                                  │
│   PK: (bairro)           │                                  │
│   CK: data_hora DESC     │                                  │
└──────────────────────────┴──────────────────────────────────┘
```
