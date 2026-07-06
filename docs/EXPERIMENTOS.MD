# Experimentos — Teste de Tolerância a Falhas

Este experimento valida que o sistema **continua funcionando mesmo com um nó do cluster fora do ar**. O roteiro segue quatro etapas:

1. Inserir dados
2. Desligar um nó
3. Executar consultas
4. Verificar se o sistema continua funcionando

> O experimento pode ser executado manualmente passo a passo (seções abaixo) ou de forma automatizada pelo script `trabalho/scripts/teste_falha.ps1` (Windows) ou `teste_falha.sh` (Linux/Mac).

---

## Pré-requisito — cluster saudável

Antes de começar, confirme que os 3 nós estão ativos (`UN` = Up/Normal):

```bash
docker compose exec cassandra1 nodetool status
```

Saída esperada:
```
Datacenter: datacenter1
=======================
Status=Up/Down
|/ State=Normal/Leaving/Joining/Moving
--  Address     Load       Tokens  Owns  Host ID   Rack
UN  172.20.0.2  ...        16      ?     ...       rack1   ← cassandra1
UN  172.20.0.3  ...        16      ?     ...       rack1   ← cassandra2
UN  172.20.0.4  ...        16      ?     ...       rack1   ← cassandra3
```

---

## Etapa 1 — Inserir dados

### Como fazer

Popule o banco com 5.000 eventos sintéticos, resetando qualquer dado anterior:

```bash
docker compose exec app python seed.py --n 5000 --reset
```

Confirme os dados com uma consulta rápida:

```bash
docker compose exec cassandra1 cqlsh -e \
  "SELECT * FROM ocorrencias.contagem_por_tipo;"
```

### O que ocorre no Cassandra

O `seed.py` chama `Repositorio.inserir()` 5.000 vezes. Cada chamada dispara:
- 1 **BATCH LOGGED** com 5 INSERTs nas tabelas de evento
- 3 **UPDATEs** nos contadores de estatística

Todas as escritas usam `ConsistencyLevel.QUORUM`: cada dado é gravado em **3 nós** (RF=3) e confirmado por **2** antes de seguir. Ao final, os 3 nós possuem cópias completas de todos os eventos.

```
seed.py → 5000 × inserir()
               ↓
    BATCH → 3 nós recebem réplicas
    QUORUM → 2 confirmam → cliente avança
```

---

## Etapa 2 — Desligar um nó

### Como fazer

Pare o container `cassandra3`:

```bash
docker compose stop cassandra3
```

Aguarde ~15 segundos para o **gossip** propagar a queda aos demais nós e confirme:

```bash
docker compose exec cassandra1 nodetool status
```

Saída esperada — `cassandra3` agora aparece como `DN` (Down):

```
UN  172.20.0.2  ...   ← cassandra1  (ativo)
UN  172.20.0.3  ...   ← cassandra2  (ativo)
DN  172.20.0.4  ...   ← cassandra3  (fora do ar)
```

### O que ocorre no Cassandra

O Cassandra usa o protocolo **Gossip**: a cada segundo cada nó troca informações de estado com outros nós aleatórios do cluster. Em ~15 segundos, `cassandra1` e `cassandra2` detectam que `cassandra3` parou de responder e marcam seu estado como `DN`.

Nenhum dado é perdido: as réplicas que estavam em `cassandra3` já existem em `cassandra1` e `cassandra2`. O cluster continua operacional com 2 dos 3 nós ativos.

```
cassandra1  ●  (ativo)   ┐
cassandra2  ●  (ativo)   ├─ QUORUM ainda possível (2 de 3)
cassandra3  ✕  (fora)    ┘
```

---

## Etapa 3 — Executar consultas

### Como fazer

Com `cassandra3` fora, execute leituras e uma inserção:

**Consultas de leitura:**
```bash
docker compose exec app python -c "
from db import conectar
from repository import Repositorio
r = Repositorio(conectar())
print('Alagamentos:', len(r.consultar_por_tipo('Alagamento')))
print('Gravidade > 3:', len(r.consultar_por_gravidade(3)))
print('Estatísticas:', r.estatisticas_por_tipo())
"
```

**Inserção com 1 nó fora:**
```bash
docker compose exec app python -c "
from datetime import datetime
from db import conectar
from model import Evento, CIDADE_PADRAO
from repository import Repositorio
r = Repositorio(conectar())
e = Evento('EVT-FALHA', 'Alagamento', 'Insercao durante falha',
           datetime.now(), 5, 'Aberto', 'Centro', CIDADE_PADRAO,
           -22.9068, -43.1729, 'Cidadao', 'USR999')
r.inserir(e)
print('Inserido com 1 nó fora:', e.id_evento)
"
```

### O que ocorre no Cassandra

O driver Python (`TokenAwarePolicy`) sabe que `cassandra3` está `DN` e **não envia requisições para ele**. Todas as operações são roteadas para `cassandra1` ou `cassandra2`.

**Leituras:** com QUORUM=2, basta que 2 nós respondam. Como `cassandra1` e `cassandra2` têm as réplicas, as consultas retornam normalmente.

**Escritas:** o BATCH é enviado ao coordenador (ex: `cassandra1`), que grava em si mesmo e em `cassandra2` — QUORUM satisfeito com 2 confirmações. O dado que deveria ir ao `cassandra3` é guardado como **hinted handoff**: o coordenador armazena a escrita localmente e a entregará ao `cassandra3` quando ele voltar.

```
Cliente → cassandra1 (coordenador)
               ├─ grava em cassandra1 ✓
               ├─ grava em cassandra2 ✓  → QUORUM atingido → confirma ao cliente
               └─ cassandra3 fora → guarda hint para entregar depois
```

---

## Etapa 4 — Verificar se o sistema continua funcionando

### Como fazer

Religue o `cassandra3` e observe a recuperação automática:

```bash
docker compose start cassandra3
```

Aguarde ~30 segundos para o rejoin e verifique o status:

```bash
docker compose exec cassandra1 nodetool status
```

Saída esperada — todos os nós voltam a `UN`:
```
UN  172.20.0.2  ...   ← cassandra1
UN  172.20.0.3  ...   ← cassandra2
UN  172.20.0.4  ...   ← cassandra3  (voltou)
```

### O que ocorre no Cassandra

Ao voltar, `cassandra3` passa pelo processo de **rejoin** em três fases:

| Fase | Mecanismo | O que acontece |
|---|---|---|
| 1 | **Gossip** | `cassandra3` anuncia retorno; os outros nós atualizam seu estado para `UN` |
| 2 | **Hinted Handoff** | `cassandra1` e `cassandra2` entregam ao `cassandra3` todas as escritas que ocorreram durante sua ausência |
| 3 | **Read Repair** | Nas próximas leituras com QUORUM, o Cassandra compara versões entre réplicas e corrige silenciosamente qualquer divergência |

Após a recuperação, os 3 nós voltam a ter cópias idênticas de todos os dados — sem intervenção manual.

---

## Script automatizado

Para executar todo o experimento de uma vez:

**Windows (PowerShell):**
```powershell
cd trabalho
./scripts/teste_falha.ps1
```

**Linux / Mac (Bash):**
```bash
cd trabalho
bash scripts/teste_falha.sh
```

O script executa as 8 etapas em sequência e exibe o resultado de cada uma, incluindo o status do cluster antes e depois da falha.

---

---

## Teste 1 — Inserção em escala

Este teste mede o tempo necessário para inserir volumes crescentes de registros e observa como o Cassandra se comporta à medida que a carga aumenta.

### O que medir

| Rodada | Registros | Operações no Cassandra |
|---|---|---|
| 1 | 1.000 | ~8.000 |
| 2 | 50.000 | ~400.000 |
| 3 | 100.000 | ~800.000 |

> Cada `inserir()` dispara 1 BATCH com 5 INSERTs + 3 UPDATEs de contadores = **8 operações por evento**.

---

### Como fazer

Execute cada rodada com o cluster completo (3 nós ativos). O `--reset` zera as tabelas antes de cada rodada para que os volumes não se acumulem.

**Linux / Mac (Bash):**

```bash
# Rodada 1 — 1.000 registros
time docker compose exec app python seed.py --n 1000 --reset

# Rodada 2 — 50.000 registros
time docker compose exec app python seed.py --n 50000 --reset

# Rodada 3 — 100.000 registros
time docker compose exec app python seed.py --n 100000 --reset
```

**Windows (PowerShell):**

```powershell
# Rodada 1 — 1.000 registros
Measure-Command { docker compose exec app python seed.py --n 1000 --reset }

# Rodada 2 — 50.000 registros
Measure-Command { docker compose exec app python seed.py --n 50000 --reset }

# Rodada 3 — 100.000 registros
Measure-Command { docker compose exec app python seed.py --n 100000 --reset }
```

O `seed.py` imprime o progresso a cada 500 eventos inseridos, permitindo acompanhar o andamento:

```
Inserindo 50000 eventos...
  500/50000 inseridos
  1000/50000 inseridos
  ...
Concluido: 50000 eventos inseridos.
```

---

### Como registrar os resultados

Anote o tempo de cada rodada numa tabela para comparação:

| Rodada | Registros | Tempo (s) | Eventos/s |
|---|---|---|---|
| 1 | 1.000 | ___ | ___ |
| 2 | 50.000 | ___ | ___ |
| 3 | 100.000 | ___ | ___ |

**Eventos/s** = Registros ÷ Tempo total em segundos.

---

### O que ocorre no Cassandra

#### 1. O que acontece a cada `inserir()`

Cada evento inserido gera exatamente 8 operações no Cassandra:

```
inserir(evento)
  ├─ BATCH LOGGED (1 operação atômica com 5 INSERTs)
  │    ├─ INSERT INTO eventos_por_id
  │    ├─ INSERT INTO eventos_por_tipo
  │    ├─ INSERT INTO eventos_por_periodo
  │    ├─ INSERT INTO eventos_por_gravidade
  │    └─ INSERT INTO eventos_por_bairro
  ├─ UPDATE contagem_por_tipo   + 1
  ├─ UPDATE contagem_por_bairro + 1
  └─ UPDATE contagem_por_dia    + 1
```

Todas as escritas usam `ConsistencyLevel.QUORUM`: cada dado é replicado para os 3 nós e confirmado por 2 antes de o cliente avançar para o próximo evento.

#### 2. Por que o tempo escala linearmente

As inserções são feitas **de forma sequencial** no `seed.py` — um evento por vez, aguardando a confirmação do Cassandra antes de enviar o próximo:

```python
for i in range(1, args.n + 1):
    repo.inserir(gerar_evento(i))  # síncrono: espera QUORUM antes de continuar
```

Isso significa que o tempo total cresce proporcionalmente ao volume: 100.000 eventos demoram ~100× mais que 1.000. Não há paralelismo de escrita nessa implementação.

#### 3. O que o Cassandra faz internamente a cada escrita

```
Cliente Python
    │
    ▼
Nó coordenador (TokenAwarePolicy escolhe o dono do token)
    ├─ Grava no próprio Commit Log (durabilidade em disco)
    ├─ Grava no Memtable (cache em memória)
    ├─ Replica para os outros 2 nós (RF=3)
    │       ↓
    │   cada réplica repete: Commit Log + Memtable
    │
    └─ Quando 2 de 3 nós confirmam → responde QUORUM ao cliente
```

O dado fica primeiro no **Memtable** (memória) e é persistido no **SSTable** (disco) quando o Cassandra decide fazer o flush — o que acontece periodicamente em background, não a cada inserção individual.

#### 4. O que observar nos resultados

- **Throughput estável**: como cada inserção é independente, o Cassandra mantém uma taxa constante de eventos/s ao longo das rodadas — o tempo deve escalar linearmente.
- **Sem degradação perceptível**: diferente de bancos relacionais, não há bloqueios de tabela, índices B-tree para rebalancear ou locks de linha. As escritas vão diretamente para o Memtable.
- **Overhead de QUORUM**: parte do tempo é latência de rede entre os 3 containers Docker esperando as 2 confirmações.

---

## Resumo do experimento

```
[Cluster saudável: 3 × UN]
         ↓
  seed.py → 5.000 eventos (RF=3, cada dado em 3 nós)
         ↓
  docker compose stop cassandra3  →  cluster: 2 UN + 1 DN
         ↓
  leituras e escritas → funcionam (QUORUM = 2 de 3)
  escritas pendentes → guardadas como hinted handoff
         ↓
  docker compose start cassandra3  →  rejoin
         ↓
  hinted handoff entregue  →  cluster consistente: 3 × UN
```

**Conclusão:** com `replication_factor = 3` e `ConsistencyLevel.QUORUM`, o sistema tolera a falha de 1 nó sem perda de dados e sem interrupção do serviço.

---

## Teste 2 — Tempo de resposta das consultas

Este teste mede quanto tempo cada tipo de consulta leva para responder nos três volumes de dados (1.000, 50.000 e 100.000 registros), permitindo comparar como o Cassandra escala para cada padrão de acesso.

### O que medir

| Consulta | Tabela acessada | Estratégia |
|---|---|---|
| Por tipo | `eventos_por_tipo` | Leitura direta de uma partição |
| Por período | `eventos_por_periodo` | Uma query por mês no intervalo |
| Geográfica | `eventos_por_bairro` | Pré-filtra bairros + consulta partições relevantes + Haversine |

---

### Como fazer

O procedimento para cada rodada é: **popular o banco → medir as 3 consultas → repetir com o próximo volume**.

#### Rodada 1 — 1.000 registros

```bash
# 1. Popular
docker compose exec app python seed.py --n 1000 --reset
```

```bash
# 2a. Consulta por tipo
docker compose exec app python -c "
import time
from db import conectar
from repository import Repositorio
r = Repositorio(conectar())
t0 = time.time()
res = r.consultar_por_tipo('Alagamento')
print(f'Por tipo     | Tempo: {time.time()-t0:.3f}s | Resultados: {len(res)}')
"
```

```bash
# 2b. Consulta por período (janeiro a junho de 2025)
docker compose exec app python -c "
import time
from datetime import datetime
from db import conectar
from repository import Repositorio
r = Repositorio(conectar())
t0 = time.time()
res = r.consultar_por_periodo(datetime(2025,1,1), datetime(2025,6,30))
print(f'Por periodo  | Tempo: {time.time()-t0:.3f}s | Resultados: {len(res)}')
"
```

```bash
# 2c. Consulta geográfica (raio de 5 km do centro do Rio)
docker compose exec app python -c "
import time
from db import conectar
from repository import Repositorio
r = Repositorio(conectar())
t0 = time.time()
res = r.consultar_geografico(-22.9068, -43.1729, 5.0)
print(f'Geografica   | Tempo: {time.time()-t0:.3f}s | Resultados: {len(res)}')
"
```

#### Rodada 2 — 50.000 registros

Repita os mesmos comandos de medição após popular com 50.000:

```bash
docker compose exec app python seed.py --n 50000 --reset
# ... mesmos comandos 2a, 2b, 2c
```

#### Rodada 3 — 100.000 registros

```bash
docker compose exec app python seed.py --n 100000 --reset
# ... mesmos comandos 2a, 2b, 2c
```

---

### Como registrar os resultados

| Consulta | 1.000 reg. | 50.000 reg. | 100.000 reg. |
|---|---|---|---|
| Por tipo | ___ s | ___ s | ___ s |
| Por período | ___ s | ___ s | ___ s |
| Geográfica | ___ s | ___ s | ___ s |

---

### O que ocorre no Cassandra — por que cada consulta escala diferente

#### Consulta por tipo — escala com o volume do tipo

```sql
SELECT * FROM eventos_por_tipo WHERE tipo = 'Alagamento';
```

O Cassandra vai direto à partição `"Alagamento"` e lê todas as linhas dela em sequência. O tempo cresce com o número de alagamentos no banco (~1/9 do total, pois há 9 tipos distribuídos uniformemente).

```
1.000 eventos  → ~111 alagamentos → leitura rápida
50.000 eventos → ~5.555 alagamentos → proporcional
100.000 eventos → ~11.111 alagamentos → proporcional
```

Não há varredura de outras partições — só a de `"Alagamento"` é tocada.

#### Consulta por período — escala com os meses do intervalo

```sql
-- Uma query por mês entre as datas informadas
SELECT * FROM eventos_por_periodo WHERE bucket_mes = '2025-01' AND data_hora >= ... AND data_hora <= ...;
SELECT * FROM eventos_por_periodo WHERE bucket_mes = '2025-02' AND ...;
-- ... até 2025-06 → 6 queries no total
```

O intervalo janeiro–junho de 2025 gera **6 queries** (uma por mês). O tempo cresce com o volume de eventos em cada mês, mas o número de queries ao Cassandra é fixo para um intervalo fixo — independente do total no banco.

#### Consulta geográfica — escala com a densidade dos bairros próximos

```python
# Passo 1: pré-filtro local (sem acesso ao banco)
bairros_candidatos = [b for b, (blat, blon) in BAIRROS.items()
                      if haversine_km(lat, lon, blat, blon) <= raio_km + 2.0]

# Passo 2: uma query por bairro candidato
for bairro in bairros_candidatos:
    SELECT * FROM eventos_por_bairro WHERE bairro = ?
```

Esta consulta carrega apenas os eventos dos bairros dentro da margem de raio — não o dataset completo. O volume transferido é proporcional ao raio e à densidade dos bairros próximos, não ao total de eventos no banco.

```
raio = 5 km, ~3 bairros candidatos → carrega ~3/10 dos eventos
raio = 5 km, 1.000 eventos  → carrega ~300  → filtra em Python
raio = 5 km, 50.000 eventos → carrega ~15.000 → filtra em Python   ← escala, mas não 50×
raio = 5 km, 100.000 eventos → carrega ~30.000 → filtra em Python
```

O tempo cresce com o volume nos bairros relevantes — não com o total. Para raios pequenos em relação ao tamanho da cidade, o crescimento é significativamente mais suave que a abordagem de carregar tudo.

#### Resumo do comportamento esperado

| Consulta | O que determina o tempo | Escala com volume? |
|---|---|---|
| Por tipo | Tamanho da partição do tipo consultado | Sim, ~proporcional ao total |
| Por período | Volume de eventos nos meses do intervalo | Sim, mas fixo por mês |
| Geográfica | Volume de eventos nos bairros dentro do raio | Sim, proporcional à área de busca |

> A consulta por tipo e por período devem mostrar crescimento proporcional ao volume. A consulta geográfica cresce de forma mais suave — apenas os eventos dos bairros candidatos são carregados, não o dataset inteiro.

---

## Teste 3 — Falha de Nó

Este teste verifica se o sistema **mantém a disponibilidade e a consistência dos dados** quando um nó do cluster é derrubado. O objetivo é comparar os resultados das consultas antes e depois da falha e confirmar que são idênticos.

### O que observar

- As consultas continuam funcionando com 1 nó fora?
- Os resultados retornados são os mesmos?
- O tempo de resposta se altera?

---

### Etapa 1 — Executar consulta normal (cluster completo)

Garanta que o banco tem dados e o cluster está saudável (3 nós `UN`), então execute e **salve os resultados**:

```bash
# Verificar cluster
docker compose exec cassandra1 nodetool status

# Popular (caso ainda não tenha dados)
docker compose exec app python seed.py --n 5000 --reset
```

```bash
# Executar e salvar resultados ANTES da falha
docker compose exec app python -c "
import time
from db import conectar
from repository import Repositorio
r = Repositorio(conectar())

t0 = time.time()
tipo = r.consultar_por_tipo('Alagamento')
print(f'[ANTES] Por tipo     | Tempo: {time.time()-t0:.3f}s | Resultados: {len(tipo)}')

t0 = time.time()
stats = r.estatisticas_por_tipo()
print(f'[ANTES] Estatisticas | Tempo: {time.time()-t0:.3f}s | Tipos: {len(stats)}')
total = sum(v for _, v in stats)
print(f'[ANTES] Total eventos nos contadores: {total}')
"
```

Anote os valores retornados — serão comparados após a falha.

---

### Etapa 2 — Desligar um servidor

Derrube o `cassandra3` e aguarde o gossip propagar a queda:

```bash
docker compose stop cassandra3

# Aguardar ~15 segundos e confirmar
docker compose exec cassandra1 nodetool status
```

Saída esperada:
```
UN  172.20.0.2  ...   ← cassandra1  (ativo)
UN  172.20.0.3  ...   ← cassandra2  (ativo)
DN  172.20.0.4  ...   ← cassandra3  (fora do ar)
```

---

### Etapa 3 — Executar novamente (com 1 nó fora)

Repita **exatamente as mesmas consultas** com o nó fora:

```bash
docker compose exec app python -c "
import time
from db import conectar
from repository import Repositorio
r = Repositorio(conectar())

t0 = time.time()
tipo = r.consultar_por_tipo('Alagamento')
print(f'[DEPOIS] Por tipo     | Tempo: {time.time()-t0:.3f}s | Resultados: {len(tipo)}')

t0 = time.time()
stats = r.estatisticas_por_tipo()
print(f'[DEPOIS] Estatisticas | Tempo: {time.time()-t0:.3f}s | Tipos: {len(stats)}')
total = sum(v for _, v in stats)
print(f'[DEPOIS] Total eventos nos contadores: {total}')
"
```

---

### Etapa 4 — Comparar os resultados

Preencha a tabela com os valores coletados nas etapas 1 e 3:

| Consulta | Antes (3 nós) | Depois (2 nós) | Igual? |
|---|---|---|---|
| Nº de alagamentos | ___ | ___ | ✓ / ✗ |
| Total nos contadores | ___ | ___ | ✓ / ✗ |
| Tempo por tipo (s) | ___ | ___ | — |
| Tempo estatísticas (s) | ___ | ___ | — |

**Resultado esperado:** os números de resultados e totais devem ser **idênticos**. O tempo pode variar levemente, mas as consultas não devem falhar.

Ao terminar, religue o nó:

```bash
docker compose start cassandra3

# Aguardar ~30s para o rejoin
docker compose exec cassandra1 nodetool status
```

---

### O que ocorre no Cassandra

#### Por que os resultados são idênticos mesmo com 1 nó fora

Com `replication_factor = 3`, cada dado existe em **3 cópias** — uma em cada nó. Quando `cassandra3` cai, `cassandra1` e `cassandra2` ainda têm cópias completas de todos os dados.

A leitura com `ConsistencyLevel.QUORUM` exige confirmação de **2 dos 3 nós**. Com 2 nós ativos, o QUORUM ainda é satisfeito:

```
cassandra1  ●  responde ✓  ┐
cassandra2  ●  responde ✓  ├─ QUORUM = 2 → leitura confirmada
cassandra3  ✕  fora do ar  ┘
```

O coordenador ignora `cassandra3`, obtém os dados de `cassandra1` e `cassandra2`, e retorna o resultado normalmente ao cliente.

#### Por que o tempo pode ser ligeiramente maior

Com o cluster completo, o driver (`TokenAwarePolicy`) envia a leitura diretamente ao nó dono do token. Com `cassandra3` fora, algumas partições cujo nó primário era `cassandra3` precisam ser lidas de uma réplica secundária — um salto extra na rede. A diferença costuma ser pequena (dezenas de milissegundos).

#### O que acontece ao religar cassandra3

```
cassandra3 volta
    │
    ├─ Gossip: anuncia retorno → estado atualizado para UN nos outros nós
    │
    ├─ Hinted Handoff: cassandra1/2 entregam as escritas
    │   que ocorreram durante a ausência
    │
    └─ Read Repair: nas próximas leituras QUORUM, o Cassandra
        compara versões entre réplicas e sincroniza divergências
```

Após o rejoin, os 3 nós voltam a ter cópias idênticas — sem intervenção manual.
