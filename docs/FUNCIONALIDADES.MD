# Funcionalidades — Plataforma de Ocorrências Urbanas

---

## 6.1 Inserir evento

### Como fazer

1. Acesse o container da aplicação:

   ```bash
   docker compose exec app python main.py
   ```

2. No menu principal, selecione a opção **1**:

   ```
   Opcao: 1
   ```

3. Preencha os campos interativamente. Exemplo para um alagamento no Centro:

   ```
   Tipo:
     1) Alagamento          ← digitar 1
     2) Acidente de Transito
     ...
   Escolha o numero: 1

   Bairro:
     1) Centro              ← digitar 1
     2) Copacabana
     ...
   Escolha o numero: 1

   Descricao: Alagamento na Avenida Rio Branco bloqueando trafego

   Gravidade (1-5): 3

   Status:
     1) Aberto              ← digitar 1
     2) Em atendimento
     3) Resolvido
   Escolha o numero: 1

   Usar coordenadas do centro de Centro? (S/n): S

   Reportante:
     1) Cidadao             ← digitar 1
     2) Sensor
   Escolha o numero: 1

   Identificador do reportante (ex.: USR001): USR042
   ```

4. O sistema confirma a inserção:

   ```
   Evento inserido: EVT1751234567 - Alagamento, Centro, grav=3, Aberto
   ```

   O `id_evento` é gerado automaticamente com os primeiros 12 caracteres de um UUID v4 (`EVT<12 hex chars>`), garantindo unicidade sem coordenação entre nós ou instâncias.

---

### O que ocorre no Cassandra

#### 1. Roteamento inteligente

O driver Python usa `TokenAwarePolicy`: antes de enviar a requisição, calcula o **token** de cada partition key e entrega cada INSERT diretamente ao nó dono daquele token — sem saltos desnecessários na rede.

#### 2. BATCH LOGGED com 5 INSERTs (QUORUM)

O evento é gravado simultaneamente em **5 tabelas** via um único `BATCH LOGGED` com `ConsistencyLevel.QUORUM`:

```
BATCH (LOGGED)
  INSERT INTO eventos_por_id        -- partition key: id_evento
  INSERT INTO eventos_por_tipo      -- partition key: tipo       | clustering: data_hora DESC
  INSERT INTO eventos_por_periodo   -- partition key: bucket_mes | clustering: data_hora ASC
  INSERT INTO eventos_por_gravidade -- partition key: gravidade  | clustering: data_hora DESC
  INSERT INTO eventos_por_bairro    -- partition key: bairro     | clustering: data_hora DESC
APPLY BATCH
```

Cada tabela tem uma partition key diferente porque cada uma foi projetada para responder a um tipo de consulta sem JOINs — padrão de **desnormalização** do Cassandra.

O batch é **LOGGED**: o Cassandra persiste o lote em um `batchlog` antes de executá-lo. Se um nó cair no meio da operação, o coordenador (ou outro nó) replaya o batch ao se recuperar, garantindo que todas as 5 tabelas fiquem consistentes entre si.

#### 3. Garantia de quorum (tolerância a 1 falha)

Com `replication_factor = 3` e `ConsistencyLevel.QUORUM`:

| Métrica | Valor |
|---|---|
| Nós no cluster | 3 |
| Réplicas por dado | 3 |
| Confirmações exigidas (QUORUM) | 2 |
| Nós que podem falhar sem impacto | 1 |

A escrita só é confirmada ao cliente após **2 dos 3 nós** responderem. O terceiro nó receberá a réplica em background. Se um nó estiver fora, a escrita ainda funciona; quando o nó voltar, recebe as atualizações via **hinted handoff** ou **repair**.

#### 4. UPDATEs nos contadores (operações separadas)

Após o BATCH, 3 atualizações incrementam as tabelas de contadores:

```sql
UPDATE contagem_por_tipo
   SET total = total + 1
 WHERE tipo = 'Alagamento';

UPDATE contagem_por_bairro
   SET total = total + 1
 WHERE cidade = 'Rio de Janeiro' AND bairro = 'Centro';

UPDATE contagem_por_dia
   SET total = total + 1
 WHERE ano = 2026 AND dia = 2026-07-05;
```

Essas operações são **separadas do BATCH** por restrição do Cassandra: tabelas `counter` não podem ser combinadas com tabelas normais em um mesmo batch.

#### 5. Fluxo completo

```
main.py
  └─ repository.py
       ├─ BATCH LOGGED (ConsistencyLevel.QUORUM)
       │    ├─ INSERT eventos_por_id         → token("EVT1751234567")
       │    ├─ INSERT eventos_por_tipo       → token("Alagamento")
       │    ├─ INSERT eventos_por_periodo    → token("2026-07")
       │    ├─ INSERT eventos_por_gravidade  → token(3)
       │    └─ INSERT eventos_por_bairro     → token("Centro")
       │              ↓
       │    Cada INSERT replicado em 3 nós, confirmado por 2 (QUORUM)
       │
       ├─ UPDATE contagem_por_tipo   +1
       ├─ UPDATE contagem_por_bairro +1
       └─ UPDATE contagem_por_dia    +1
```

Ao final, **8 tabelas** são afetadas por uma única inserção — 5 de eventos (para leitura eficiente por diferentes critérios) e 3 de contadores (para estatísticas em tempo real).

---

## 6.2 Listar todos os alagamentos

### Como fazer

1. Acesse o container da aplicação:

   ```bash
   docker compose exec app python main.py
   ```

2. No menu principal, selecione a opção **2**:

   ```
   Opcao: 2
   ```

3. Escolha o tipo "Alagamento":

   ```
   Tipo:
     1) Alagamento          ← digitar 1
     2) Acidente de Transito
     ...
   Escolha o numero: 1
   ```

4. O sistema exibe todos os eventos encontrados, ordenados do mais recente para o mais antigo:

   ```
   42 evento(s) encontrado(s):
     [EVT1751234567] Alagamento grav=4 Aberto - Centro @ 2026-07-05 14:32 :: Alagamento na via
     [EVT0003812]    Alagamento grav=2 Resolvido - Copacabana @ 2026-06-18 09:10 :: Alagamento na via
     ...
   ```

---

### O que ocorre no Cassandra

#### 1. Uma única query de leitura

A consulta é executada diretamente na tabela `eventos_por_tipo`, que foi criada especificamente para esse padrão de acesso:

```sql
SELECT * FROM eventos_por_tipo WHERE tipo = 'Alagamento';
```

Não há varredura de tabela completa (full scan), não há filtro em memória e não há JOIN — o Cassandra localiza a partição de `"Alagamento"` e lê todas as linhas dela em ordem de clustering.

#### 2. Por que existe uma tabela dedicada para isso

No Cassandra, toda consulta eficiente precisa que a **partition key seja filtrada por igualdade**. A tabela `eventos_por_tipo` foi modelada exatamente para esse caso:

```
CREATE TABLE eventos_por_tipo (
  tipo       text,          -- partition key: todos os alagamentos ficam na mesma partição
  data_hora  timestamp,     -- clustering key 1: ordena do mais recente ao mais antigo
  id_evento  text,          -- clustering key 2: desempate
  ...
  PRIMARY KEY ((tipo), data_hora, id_evento)
) WITH CLUSTERING ORDER BY (data_hora DESC, id_evento ASC)
```

Todos os alagamentos vivem na **mesma partição** (`tipo = 'Alagamento'`), fisicamente armazenados em disco já ordenados por `data_hora DESC`. A leitura é sequencial — sem ordenação em tempo de consulta.

#### 3. Roteamento e consistência

O driver calcula o token de `"Alagamento"` e envia a query diretamente ao nó responsável por essa partição (`TokenAwarePolicy`). A leitura usa `ConsistencyLevel.QUORUM`: o coordenador consulta **2 dos 3 nós** que guardam réplicas e retorna o dado mais recente — garantindo que nenhum evento recém-inserido fique invisível.

#### 4. Fluxo completo

```
main.py (opção 2)
  └─ repository.consultar_por_tipo("Alagamento")
       └─ SELECT * FROM eventos_por_tipo WHERE tipo = 'Alagamento'
                 ↓
         token("Alagamento") → nó coordenador
                 ↓
         leitura QUORUM (2 de 3 réplicas confirmam)
                 ↓
         linhas já ordenadas por data_hora DESC (sem sort extra)
                 ↓
         imprimir_eventos(rows, limite=50)
```

#### 5. Por que não usar a tabela `eventos_por_id`

A tabela `eventos_por_id` tem `id_evento` como partition key — cada evento é uma partição separada. Buscar todos os alagamentos exigiria iterar por milhares de partições individualmente, o que seria extremamente ineficiente. A desnormalização em `eventos_por_tipo` existe exatamente para evitar isso.

---

## 6.3 Consultar eventos por período

### Como fazer

1. Acesse o container da aplicação:

   ```bash
   docker compose exec app python main.py
   ```

2. No menu principal, selecione a opção **3**:

   ```
   Opcao: 3
   ```

3. Informe as datas de início e fim. Aceita dois formatos:

   ```
   Data inicial (AAAA-MM-DD ou AAAA-MM-DDTHH:MM): 2025-05-01
   Data final   (AAAA-MM-DD ou AAAA-MM-DDTHH:MM): 2025-05-31
   ```

4. O sistema exibe todos os eventos no intervalo, ordenados do mais antigo ao mais recente:

   ```
   87 evento(s) encontrado(s):
     [EVT00042] Alagamento grav=3 Aberto - Centro @ 2025-05-02 08:14 :: Alagamento na via
     [EVT00107] Incendio grav=5 Resolvido - Tijuca @ 2025-05-10 21:33 :: Incendio em edificacao
     ...
   ```

   Se as datas forem informadas invertidas (fim antes do início), o sistema as corrige automaticamente.

---

### O que ocorre no Cassandra

#### 1. O problema do range query em partition keys

No Cassandra, filtros de intervalo (`>=`, `<=`) **só funcionam em clustering keys**, nunca em partition keys. Isso impediria uma consulta direta por `data_hora` se ela fosse a partition key. A solução é o padrão de **bucketing por mês**.

#### 2. A tabela `eventos_por_periodo` e o bucket mensal

```
CREATE TABLE eventos_por_periodo (
  bucket_mes  text,       -- partition key: ex. "2025-05"
  data_hora   timestamp,  -- clustering key 1: ordena dentro do mês (ASC)
  id_evento   text,       -- clustering key 2: desempate
  ...
  PRIMARY KEY ((bucket_mes), data_hora, id_evento)
) WITH CLUSTERING ORDER BY (data_hora ASC, id_evento ASC)
```

Todos os eventos de maio de 2025 ficam na partição `"2025-05"`, fisicamente ordenados por `data_hora ASC`. O range filter (`data_hora >= ? AND data_hora <= ?`) é aplicado sobre a clustering key — operação eficiente e nativa do Cassandra.

#### 3. Uma query por mês no intervalo

O código gera um bucket para cada mês entre as datas e dispara uma query por bucket:

```python
# repository.py — consultar_por_periodo()
for bucket in _buckets_mes(ini, fim):
    resultado.extend(session.execute(
        "SELECT * FROM eventos_por_periodo "
        "WHERE bucket_mes = ? AND data_hora >= ? AND data_hora <= ?",
        (bucket, ini, fim)
    ))
resultado.sort(key=lambda r: r.data_hora)
```

| Intervalo solicitado | Buckets gerados | Queries ao Cassandra |
|---|---|---|
| 01/05/2025 – 31/05/2025 | `["2025-05"]` | 1 |
| 01/03/2025 – 30/06/2025 | `["2025-03", "2025-04", "2025-05", "2025-06"]` | 4 |
| 01/12/2024 – 28/02/2025 | `["2024-12", "2025-01", "2025-02"]` | 3 |

Os resultados de cada bucket são concatenados e reordenados em memória pelo cliente para garantir a ordem global entre meses.

#### 4. Roteamento e consistência

Cada query vai diretamente ao nó dono do bucket (`TokenAwarePolicy`). A leitura usa `ConsistencyLevel.QUORUM` — 2 dos 3 nós confirmam, garantindo que eventos recém-inseridos já aparecem na consulta.

#### 5. Fluxo completo

```
main.py (opção 3)
  └─ repository.consultar_por_periodo(2025-05-01, 2025-05-31)
       └─ _buckets_mes() → ["2025-05"]
            └─ SELECT * FROM eventos_por_periodo
               WHERE bucket_mes = '2025-05'
               AND data_hora >= 2025-05-01
               AND data_hora <= 2025-05-31
                     ↓
               token("2025-05") → nó coordenador
                     ↓
               leitura QUORUM (2 de 3 réplicas)
                     ↓
               linhas já ordenadas por data_hora ASC
                     ↓
               resultado.sort() (reordenação final no cliente)
                     ↓
               imprimir_eventos(rows, limite=50)
```

---

## 6.4 Consultar eventos por raio geográfico

### Como fazer

1. Acesse o container da aplicação:

   ```bash
   docker compose exec app python main.py
   ```

2. No menu principal, selecione a opção **4**:

   ```
   Opcao: 4
   ```

3. Informe o ponto central e o raio desejado:

   ```
   Dica: centro do Rio ~ -22.9068, -43.1729

   Latitude do ponto: -22.9068
   Longitude do ponto: -43.1729
   Raio (km): 5
   ```

4. O sistema exibe os eventos dentro do raio, ordenados do mais próximo ao mais distante:

   ```
   12 evento(s) dentro de 5 km:
     0.31 km [EVTA3F1B2C9D0E] Alagamento - Centro @ 2025-05-02 08:14
     1.74 km [EVT8B7E3A1F0D2] Queda de Energia - Botafogo @ 2025-03-17 14:20
     4.89 km [EVT1C2D4F5A6B7] Incendio - Copacabana @ 2025-01-09 22:05
   ```

---

### O que ocorre no Cassandra

#### 1. Limitação: Cassandra não tem suporte geoespacial nativo

O Cassandra não oferece operadores de distância ou índices espaciais. A solução é uma estratégia em três passos: pré-filtrar os bairros candidatos localmente, consultar no banco apenas as partições relevantes, e aplicar o filtro de distância exata no cliente.

#### 2. Passo 1 — Python: identificar bairros candidatos (sem acesso ao banco)

Antes de qualquer consulta ao Cassandra, o código percorre o dicionário estático `BAIRROS` — que contém as coordenadas do centro de cada bairro — e aplica Haversine para identificar quais bairros têm seu centro a menos de **raio + 2 km** do ponto informado. A margem de 2 km absorve o espalhamento geográfico dos eventos dentro de um bairro (o `seed.py` distribui eventos em até ±1,5 km do centro):

```python
# repository.py — consultar_geografico()
bairros_candidatos = [
    b for b, (blat, blon) in BAIRROS.items()
    if haversine_km(lat, lon, blat, blon) <= raio_km + 2.0
]
```

Essa filtragem é puramente local e reduz o número de consultas ao banco ao mínimo necessário.

#### 3. Passo 2 — Cassandra: busca apenas os bairros candidatos

Para cada bairro candidato, uma query é enviada à tabela `eventos_por_bairro`, que tem `bairro` como partition key:

```sql
SELECT * FROM eventos_por_bairro WHERE bairro = 'Centro';
SELECT * FROM eventos_por_bairro WHERE bairro = 'Botafogo';
-- somente os bairros dentro da margem de raio
```

A tabela distribui os eventos em 10 partições independentes:

```
CREATE TABLE eventos_por_bairro (
  bairro     text,       -- partition key: eventos do mesmo bairro na mesma partição
  data_hora  timestamp,  -- clustering key 1
  id_evento  text,       -- clustering key 2
  ...
  PRIMARY KEY ((bairro), data_hora, id_evento)
)
```

Em vez de transferir todo o dataset, somente as partições dos bairros próximos são lidas — o volume é proporcional ao raio de busca.

#### 4. Passo 3 — Python: filtro final por distância com Haversine

Para cada evento retornado do banco, o código calcula a distância exata usando a **fórmula de Haversine** (`geo.py`), que considera a curvatura da Terra:

```python
for bairro in bairros_candidatos:
    for r in session.execute(q_bairro, (bairro,)):
        dist = haversine_km(lat, lon, r.latitude, r.longitude)
        if dist <= raio_km:
            proximos.append((dist, r))
proximos.sort(key=lambda par: par[0])
```

```python
# geo.py — fórmula de Haversine
def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    return 2 * RAIO_TERRA_KM * asin(sqrt(a))  # RAIO_TERRA_KM = 6371.0
```

Eventos fora do raio são descartados; os restantes são ordenados por distância crescente.

#### 5. Fluxo completo

```
main.py (opção 4)
  └─ repository.consultar_geografico(-22.9068, -43.1729, 5.0)
       ├─ BAIRROS.items() → haversine → bairros com centro ≤ 7 km
       │         ↓
       │   bairros_candidatos = ["Centro", "Botafogo", "Tijuca", ...]
       │
       ├─ SELECT * FROM eventos_por_bairro WHERE bairro = 'Centro'
       │         ↓ token("Centro") → nó coordenador (QUORUM)
       │
       ├─ SELECT * FROM eventos_por_bairro WHERE bairro = 'Botafogo'
       │         ↓ token("Botafogo") → nó coordenador (QUORUM)
       │
       └─ para cada evento de cada bairro:
            haversine_km(ponto_central, evento.lat, evento.lon)
                  ↓
            se dist ≤ 5 km → adiciona à lista
                  ↓
            proximos.sort() por distância crescente
                  ↓
            exibe os 50 primeiros resultados
