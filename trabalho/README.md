# Plataforma de Ocorrências Urbanas — Apache Cassandra

Plataforma para registrar e consultar ocorrências urbanas (acidentes, alagamentos,
incêndios, tiroteios, etc.) reportadas por cidadãos e sensores IoT, usando um **cluster
Apache Cassandra de 3 nós** em Docker. Atende a todos os requisitos do `trabalho.md`.

> **Por que Cassandra?** É um banco distribuído, sem ponto único de falha, com replicação
> nativa e alta disponibilidade (AP no teorema CAP). Suporta milhares de registros e
> **continua respondendo mesmo com um servidor fora do ar** — exatamente o que o enunciado
> pede. A justificativa completa está em [RELATORIO.md](RELATORIO.md).

## Pré-requisitos

- Docker + Docker Compose (testado com Docker 29 / Compose v5).
- ~3 GB de RAM livres (3 nós Cassandra com heap limitado a 512 MB cada).

## Estrutura

```
trabalho/
  docker-compose.yml      # 3 nós Cassandra (cassandra1/2/3) + container da app
  schema.cql              # esquema de referência (a app também cria no startup)
  app/                    # aplicação Python (cassandra-driver)
    db.py                 # conexão (QUORUM) + criação do schema
    model.py              # modelo Evento + tipos e bairros
    geo.py                # distância haversine (consulta geográfica)
    repository.py         # inserção e consultas 6.1–6.6
    seed.py               # gera milhares de eventos de exemplo
    main.py               # menu interativo (CLI)
  scripts/
    teste_falha.ps1 / .sh # roteiro do teste de tolerância a falhas (item 7)
  RELATORIO.md            # justificativas, modelagem e resultados
```

## Como executar

### 1. Subir o cluster (3 nós) + a aplicação

```bash
cd trabalho
docker compose up -d --build
```

Os nós sobem **um de cada vez** (Cassandra exige bootstrap sequencial). A primeira subida
leva alguns minutos. Acompanhe até os 3 ficarem saudáveis:

```bash
docker compose ps
docker compose exec cassandra1 nodetool status   # esperado: 3 linhas começando com UN
```

`UN` = *Up / Normal*. Quando aparecerem 3 nós `UN`, o cluster está pronto.

### 2. Popular com dados de exemplo

```bash
docker compose exec app python seed.py --n 5000          # 5000 eventos
# ou recomeçar do zero:
docker compose exec app python seed.py --n 5000 --reset  # limpa e recarrega
```

### 3. Usar o menu interativo

```bash
docker compose exec app python main.py
```

```
=== Plataforma de Ocorrencias Urbanas (Cassandra) ===
  1) Inserir evento                (6.1)
  2) Consultar por tipo            (6.2)
  3) Consultar por periodo         (6.3)
  4) Consulta geografica (raio km) (6.4)
  5) Consultar por gravidade       (6.5)
  6) Estatisticas                  (6.6)
  0) Sair
```

## Mapeamento das funcionalidades obrigatórias

| Requisito | Onde está | Como funciona |
|---|---|---|
| **6.1** Inserção | `repository.inserir` | Grava o evento (denormalizado) em 5 tabelas via `BATCH` + atualiza 3 contadores |
| **6.2** Por tipo | `consultar_por_tipo` | `eventos_por_tipo` particionada por `tipo` |
| **6.3** Por período | `consultar_por_periodo` | `eventos_por_periodo` com bucket mensal; varre os meses do intervalo |
| **6.4** Geográfica | `consultar_geografico` + `geo.py` | Puxa candidatos por cidade e filtra por **haversine** (sem geo nativo) |
| **6.5** Por gravidade | `consultar_por_gravidade` | `gravidade > N` → `WHERE gravidade IN (...)` (níveis 1–5) |
| **6.6** Estatísticas | `estatisticas_*` / `evolucao_por_dia` | Tabelas **counter** por tipo, por bairro e por dia |
| **7** Distribuído | `docker-compose.yml` + RF=3 + QUORUM | 3 nós, dado replicado, tolera 1 nó fora |

## Teste de tolerância a falhas (item 7)

Roteiro completo automatizado (inserir → derrubar um nó → consultar → verificar):

```powershell
# Windows (PowerShell), a partir da pasta trabalho/
./scripts/teste_falha.ps1
```

```bash
# Linux/macOS/Git Bash
bash scripts/teste_falha.sh
```

Resumo do que o script demonstra:

1. `nodetool status` → 3 nós `UN`.
2. Insere 5000 eventos.
3. Roda consultas (funcionam).
4. `docker compose stop cassandra3` → derruba um nó.
5. `nodetool status` → `cassandra3 = DN`, os outros 2 `UN`.
6. **As mesmas consultas e até uma nova inserção continuam funcionando** — com RF=3 e
   Consistency `QUORUM` (2 de 3), 2 nós bastam.
7. `docker compose start cassandra3` → o nó volta e os dados são reconciliados
   (hinted handoff / read-repair).

## Acesso direto via cqlsh (opcional)

```bash
docker compose exec cassandra1 cqlsh
# já dentro do cqlsh:
USE ocorrencias;
SELECT COUNT(*) FROM eventos_por_id;
SELECT * FROM contagem_por_tipo;
```

## Encerrar

```bash
docker compose down            # para os containers (mantém os dados nos volumes)
docker compose down -v         # para e APAGA os dados (volumes)
```

## Detalhes técnicos

- **Replicação:** keyspace `ocorrencias` com `SimpleStrategy` e `replication_factor = 3`.
- **Consistência:** a aplicação usa `QUORUM` em leituras e escritas → tolerância a 1 nó fora.
- **Modelagem:** orientada a consultas (uma tabela por padrão de consulta), pois o Cassandra
  não faz JOIN nem agregações arbitrárias. Veja [RELATORIO.md](RELATORIO.md).
