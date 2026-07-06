# Geração de Dados — Plataforma de Ocorrências Urbanas

Este documento descreve como os dados inseridos no banco Apache Cassandra são gerados para fins de teste e demonstração do sistema.

---

## Visão geral

Os dados são gerados **programaticamente em Python**, sem bibliotecas externas (sem Faker, sem CSV externo). A geração usa apenas o módulo `random` da stdlib Python combinado com tabelas de referência fixas definidas em `model.py`.

O script principal é `trabalho/app/seed.py`.

---

## Como executar

```bash
# Insere 5000 eventos (padrão)
python seed.py

# Insere um número específico de eventos
python seed.py --n 10000

# Limpa todas as tabelas e reinsere
python seed.py --reset
```

---

## Estrutura de um evento gerado

A função `gerar_evento(i: int)` em `seed.py` constrói um evento sintético por chamada. A tabela abaixo descreve como cada campo é preenchido:

| Campo | Estratégia de geração | Exemplo |
|---|---|---|
| `id_evento` | Sequencial formatado | `EVT00001`, `EVT00002`… |
| `tipo` | `random.choice` de 9 tipos fixos | `"Alagamento"`, `"Incendio"` |
| `bairro` | `random.choice` de 10 bairros do RJ | `"Copacabana"`, `"Tijuca"` |
| `latitude` | Coord. central do bairro + `random.uniform(-0.015, 0.015)` | `-22.9878` |
| `longitude` | Coord. central do bairro + `random.uniform(-0.015, 0.015)` | `-43.1920` |
| `data_hora` | Segundo aleatório entre 2025-01-01 e 2025-06-30 | `2025-03-14 17:42:00` |
| `gravidade` | `random.randint(1, 5)` | `3` |
| `status` | `random.choice` de 3 opções fixas | `"Em atendimento"` |
| `reportante_tipo` | `random.choice(["Cidadao", "Sensor"])` | `"Sensor"` |
| `reportante_id` | `USRxxx` ou `SENxxx` conforme o tipo | `"SEN042"` |
| `descricao` | String fixa por tipo de ocorrência (não aleatória) | `"Alagamento na via"` |
| `cidade` | Sempre `"Rio de Janeiro"` (fixo) | — |

---

## Tabelas de referência fixas (`model.py`)

### Tipos de ocorrência (`TIPOS`)

```
Alagamento, Acidente de Transito, Queda de Energia, Incendio,
Problema no Transporte Publico, Vazamento de Agua,
Interdicao de Via, Deslizamento, Tiroteio
```

### Bairros e coordenadas centrais (`BAIRROS`)

| Bairro | Latitude | Longitude |
|---|---|---|
| Centro | -22.9068 | -43.1729 |
| Copacabana | -22.9711 | -43.1823 |
| Tijuca | -22.9231 | -43.2271 |
| Botafogo | -22.9519 | -43.1823 |
| Madureira | -22.8761 | -43.3394 |
| Barra da Tijuca | -23.0000 | -43.3650 |
| Bangu | -22.8878 | -43.4669 |
| Campo Grande | -22.9003 | -43.5596 |
| Ipanema | -22.9836 | -43.2049 |
| Maracanã | -22.9121 | -43.2302 |

As coordenadas de cada evento são geradas aplicando um deslocamento aleatório de até ±0,015° (aproximadamente ±1,5 km) ao redor do centro do bairro.

### Status (`STATUS`)

```
Aberto, Em atendimento, Resolvido
```

---

## Fluxo de inserção no banco

```
seed.py
  └─ gerar_evento(i)          # cria o objeto Evento com dados aleatórios
       └─ Repositorio.inserir(evento)
            ├─ BATCH (5 tabelas de consulta)
            │    ├─ eventos_por_id
            │    ├─ eventos_por_tipo
            │    ├─ eventos_por_periodo
            │    ├─ eventos_por_gravidade
            │    └─ eventos_por_cidade
            └─ UPDATE separado (3 tabelas de contadores)
                 ├─ contagem_por_tipo
                 ├─ contagem_por_bairro
                 └─ contagem_por_dia
```

Cada evento é **desnormalizado** em 5 tabelas principais via `BATCH` com `ConsistencyLevel.QUORUM`. Os contadores são incrementados em uma operação separada (restrição do Cassandra: contadores não podem ser misturados em batches regulares).

---

## Inserção manual (modo interativo)

Além do seed em massa, o sistema permite inserir eventos individualmente pelo menu interativo (`main.py`, opção 1). Nesse modo:

- `id_evento` usa o timestamp Unix atual: `EVT<unix_timestamp>`
- `data_hora` usa `datetime.now()`
- Os demais campos são preenchidos pelo usuário via prompts na linha de comando

---

## Arquivos envolvidos

| Arquivo | Papel |
|---|---|
| `trabalho/app/seed.py` | Script principal de geração e inserção em massa |
| `trabalho/app/model.py` | Tabelas de referência fixas (tipos, bairros, status) |
| `trabalho/app/repository.py` | Camada de escrita no Cassandra |
| `trabalho/app/db.py` | Bootstrap do schema (keyspace + tabelas) |
| `trabalho/app/main.py` | Inserção manual via menu interativo |
| `trabalho/schema.cql` | DDL de referência (documentação) |
