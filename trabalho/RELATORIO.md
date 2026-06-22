# Relatório — Plataforma de Ocorrências Urbanas com Apache Cassandra

## 1. O problema

A Prefeitura precisa registrar e consultar, **em tempo real**, ocorrências urbanas
(acidentes de trânsito, alagamentos, quedas de energia, incêndios, problemas no transporte
público, vazamentos de água, interdições de vias, deslizamentos e tiroteios) reportadas por
cidadãos e sensores IoT. Os requisitos não-funcionais centrais são:

- suportar **milhares de registros**;
- consultar em **tempo real**;
- **continuar funcionando mesmo com um servidor de banco fora do ar**.

## 2. Podemos usar o Apache Cassandra? Sim.

Cassandra é um banco **NoSQL distribuído, orientado a colunas e descentralizado** (todos os
nós são iguais — não há nó mestre). Ele atende ponto a ponto ao enunciado:

| Necessidade | Como o Cassandra atende |
|---|---|
| Continuar funcionando com um servidor fora | **Replicação** nativa (RF > 1) + arquitetura **sem ponto único de falha**. Qualquer nó atende leituras/escritas. |
| Milhares (ou milhões) de registros | **Escala horizontal linear**: basta adicionar nós; os dados são distribuídos por *consistent hashing* (token ring). |
| Tempo real | Escritas muito rápidas (append em *commit log* + *memtable*); leituras por chave de partição são O(1) de partição. |
| Alta disponibilidade | No teorema **CAP**, Cassandra é **AP** (Disponibilidade + tolerância a Partição), com **consistência ajustável** por consulta (ONE, QUORUM, ALL...). |

**Custo dessa escolha:** abrimos mão de JOINs, de agregações arbitrárias e de geoconsultas
nativas. Isso muda a forma de modelar (seção 4) mas não impede atender aos requisitos.

## 3. Arquitetura distribuída (item 7)

- **Cluster de 3 nós** em Docker (`cassandra1`, `cassandra2`, `cassandra3`), na mesma rede.
  `cassandra1` é o *seed*; os nós sobem em sequência (bootstrap do Cassandra é sequencial).
- **Keyspace `ocorrencias`** com `SimpleStrategy` e **`replication_factor = 3`** → cada
  registro é replicado nos **3 nós**. Logo, "os dados existem em mais de um servidor".
- **Consistência `QUORUM`** na aplicação (leitura e escrita). Com RF=3:

  ```
  QUORUM = floor(RF/2) + 1 = floor(3/2) + 1 = 2
  ```

  Como uma operação só precisa de **2 dos 3** nós, o sistema **tolera a queda de 1 nó**
  mantendo **consistência forte** (a interseção entre o quórum de escrita e o de leitura
  garante que toda leitura enxerga a última escrita confirmada).

  > Se quiséssemos tolerar **2 nós** fora, bastaria usar `ONE` nas leituras/escritas —
  > maior disponibilidade, porém consistência mais fraca. Optamos por `QUORUM` por ser o
  > ponto de equilíbrio que ainda demonstra forte consistência sob falha.

- **Recuperação:** quando o nó volta, *hinted handoff* (escritas pendentes guardadas pelos
  vivos) e *read-repair* reconciliam os dados automaticamente.

## 4. Modelagem orientada a consultas (query-first)

No Cassandra **modela-se a partir das consultas**, não das entidades. Como não há JOIN, o
mesmo evento é **desnormalizado** em várias tabelas — uma por padrão de acesso. A chave
primária define a **partição** (distribuição/lookup) e a **ordenação** (clustering).

| Tabela | Partition key | Clustering | Atende |
|---|---|---|---|
| `eventos_por_id` | `id_evento` | — | registro canônico / busca por id |
| `eventos_por_tipo` | `tipo` | `data_hora DESC, id_evento` | **6.2** listar por tipo |
| `eventos_por_periodo` | `bucket_mes` `'YYYY-MM'` | `data_hora ASC, id_evento` | **6.3** intervalo de datas |
| `eventos_por_gravidade` | `gravidade` (1–5) | `data_hora DESC, id_evento` | **6.5** gravidade alta |
| `eventos_por_cidade` | `cidade` | `data_hora DESC, id_evento` | **6.4** candidatos p/ filtro geográfico |
| `contagem_por_tipo` | `tipo` | — (`total counter`) | **6.6** total por tipo |
| `contagem_por_bairro` | `cidade` | `bairro` (`total counter`) | **6.6** total por bairro |
| `contagem_por_dia` | `ano` | `dia` (`total counter`) | **6.6** evolução temporal |

Decisões de projeto:

- **Bucket mensal na consulta por período:** particionar por mês (`'YYYY-MM'`) evita
  partições gigantes (anti-padrão do Cassandra) e ainda permite *range query* eficiente por
  `data_hora` dentro do mês. A aplicação calcula os meses do intervalo pedido e consulta
  cada bucket (ver `repository._buckets_mes`).
- **Gravidade > 3:** Cassandra não faz `>` em chave de partição. Como a gravidade é um
  domínio discreto (1–5), a aplicação traduz "> N" para `WHERE gravidade IN (...)` com os
  níveis acima de N — sem `ALLOW FILTERING`.
- **Consulta geográfica (sem geo nativo):** conforme autorizado no enunciado, a filtragem é
  feita **na aplicação**. Puxamos os candidatos da cidade (`eventos_por_cidade`) e
  calculamos a distância pela fórmula de **Haversine** (`geo.py`), retornando os eventos
  dentro do raio em km, ordenados por distância.
  - *Escalabilidade (trabalho futuro):* para milhões de eventos, particionar por **geohash**
    (ex.: prefixo de ~5 km) e consultar a célula + vizinhas reduziria os candidatos. Mantido
    fora do escopo por simplicidade; o volume do trabalho (milhares) é tratado sem problema.
- **Estatísticas com tabelas `counter`:** em vez de `COUNT(*)` (caro e que exige conhecer
  todas as chaves), mantemos contadores atualizados **a cada inserção** — estatísticas em
  tempo real. Counters exigem tabela própria (não se misturam com colunas normais), por isso
  as três tabelas `contagem_*`.
  - *Trade-off:* contadores não são idempotentes em re-tentativa/recarga. Por isso
    `seed.py --reset` **trunca** as tabelas antes de recarregar, mantendo a contagem coerente.

### Inserção (6.1)

`repository.inserir` grava as 5 tabelas de evento em um **`BATCH` logado** (mantém as
cópias denormalizadas consistentes entre si) e, em seguida, incrementa os 3 contadores
(updates separados, pois são tabelas counter).

## 5. Mapeamento requisito → implementação

| Requisito | Implementação |
|---|---|
| 6.1 Inserção | `Repositorio.inserir` (BATCH + counters) / opção 1 do menu |
| 6.2 Por tipo | `consultar_por_tipo` / opção 2 |
| 6.3 Por período | `consultar_por_periodo` (buckets mensais) / opção 3 |
| 6.4 Geográfica | `consultar_geografico` + `geo.haversine_km` / opção 4 |
| 6.5 Por gravidade | `consultar_por_gravidade` (`IN`) / opção 5 |
| 6.6 Estatísticas | `estatisticas_por_tipo`, `estatisticas_por_bairro`, `evolucao_por_dia` / opção 6 |
| 7 Distribuído | `docker-compose.yml` (3 nós), RF=3, QUORUM |

## 6. Teste de tolerância a falhas (procedimento e resultado esperado)

Script: `scripts/teste_falha.ps1` (ou `.sh`).

1. **Inserir dados** — `seed.py --n 5000 --reset`.
2. **Verificar cluster** — `nodetool status` mostra **3 nós `UN`**.
3. **Consultar** — consultas 6.2/6.5 e estatísticas retornam normalmente.
4. **Desligar um nó** — `docker compose stop cassandra3`.
5. **Verificar** — `nodetool status` mostra `cassandra3 = DN` e 2 nós `UN`.
6. **Consultar e inserir novamente** — com 1 nó fora, **as consultas continuam
   funcionando** e uma nova inserção é aceita, pois QUORUM=2 é satisfeito pelos 2 nós vivos.
7. **Religar o nó** — `docker compose start cassandra3`; ele reentra no cluster e os dados
   gravados durante a falha são reconciliados (hinted handoff / read-repair).

**Conclusão:** o requisito de continuar operando com um servidor indisponível é atendido
pela combinação **RF=3 + QUORUM**, sem qualquer intervenção manual.

## 7. Conclusão

O Apache Cassandra é adequado ao problema: distribuído, altamente disponível, escalável e
tolerante a falhas. As limitações (sem JOIN/agregação/geo) são contornadas com modelagem
orientada a consultas, contadores e filtragem geográfica na aplicação — entregando todas as
funcionalidades obrigatórias (6.1–6.6) e a parte distribuída (item 7).
