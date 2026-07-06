# Decisões de design e ajustes de implementação

Este documento registra escolhas de implementação que divergem do esboço inicial do schema, explicando o motivo de cada uma.

---

## 1. Identificador único gerado com UUID

**Arquivo:** `app/main.py`

**Problema:** gerar `id_evento` a partir do timestamp Unix em segundos (`EVT<unix_timestamp>`) provoca colisão quando dois eventos são inseridos no mesmo segundo. No Cassandra, a política de *last-write-wins* faz com que o registro mais antigo seja **sobrescrito silenciosamente** em `eventos_por_id` — sem erro, sem aviso.

**Solução:** o `id_evento` é gerado com os primeiros 12 caracteres de um UUID v4 aleatório:

```python
id_evento = f"EVT{uuid.uuid4().hex[:12].upper()}"
# ex.: EVTA3F1B2C9D0E4
```

UUIDs v4 são criptograficamente aleatórios — a probabilidade de colisão é desprezível mesmo com milhões de eventos por segundo, sem nenhuma coordenação entre nós ou instâncias.

> O `seed.py` continua usando IDs sequenciais (`EVT00001`, `EVT00002`…) para facilitar a rastreabilidade durante os experimentos. Esses IDs não colidem porque são gerados por um único processo sequencial controlado.

---

## 2. Busca geográfica particionada por bairro

**Arquivos:** `schema.cql`, `app/db.py`, `app/repository.py`

**Problema:** a tabela `eventos_por_cidade` tinha `cidade` como partition key, mas `cidade` é sempre `"Rio de Janeiro"` em todo o dataset — criando uma única partição com 100% dos eventos. A busca geográfica precisava carregar toda essa partição para o cliente Python antes de aplicar qualquer filtro de distância, tornando o custo da operação proporcional ao total de eventos no banco.

**Solução:** a tabela foi renomeada para `eventos_por_bairro` e a partition key foi alterada para `bairro`:

```sql
CREATE TABLE eventos_por_bairro (
  bairro text,   -- partition key: distribui eventos em 10 partições independentes
  ...
  PRIMARY KEY ((bairro), data_hora, id_evento)
)
```

A função `consultar_geografico` agora opera em dois passos antes de tocar o banco:

1. **Pré-filtro local:** consulta o dicionário estático `BAIRROS` (coordenadas dos centros) e usa Haversine para identificar quais bairros têm seu centro a menos de `raio + 2 km` do ponto informado (margem que absorve o espalhamento geográfico dos eventos dentro de um bairro).
2. **Consulta seletiva:** busca no Cassandra apenas as partições dos bairros candidatos.
3. **Filtro exato:** aplica Haversine em cada evento retornado para confirmar que está dentro do raio.

Com isso, em vez de transferir todo o dataset, somente as partições relevantes são lidas — o volume é proporcional ao raio de busca e à densidade dos bairros próximos.

---

## 3. TTL de 1 ano em `eventos_por_gravidade`

**Arquivos:** `schema.cql`, `app/db.py`

**Problema:** `gravidade` tem apenas 5 valores distintos (1–5), criando 5 partições fixas. Sem qualquer mecanismo de expiração, cada partição acumula eventos indefinidamente — a partição `gravidade = 5` cresceria com todos os eventos críticos de toda a vida útil do sistema, tornando-se uma *hot partition* de tamanho ilimitado.

**Solução:** adicionado `default_time_to_live = 31536000` (365 dias) à tabela:

```sql
CREATE TABLE eventos_por_gravidade (
  ...
) WITH CLUSTERING ORDER BY (data_hora DESC, id_evento ASC)
   AND default_time_to_live = 31536000;
```

Linhas com mais de 1 ano são removidas automaticamente pelo processo de *compaction* do Cassandra, mantendo o tamanho de cada partição proporcional ao volume do último ano — não ao histórico completo.

> As demais tabelas não precisam de TTL: `eventos_por_tipo` já é limitada por tipo (~1/9 do total cada); `eventos_por_periodo` é naturalmente limitada por mês; `eventos_por_bairro` é agora limitada por bairro.

---

## 4. Inconsistência entre BATCH e contadores — limitação aceita

**Arquivo:** sem mudança de código

**Contexto:** o `BATCH LOGGED` que grava as 5 tabelas de evento e os 3 `UPDATE` de contadores são operações **separadas e não atômicas entre si**. O Cassandra proíbe misturar tabelas `counter` com tabelas normais em um mesmo batch. Uma queda da aplicação exatamente entre essas operações deixaria os contadores levemente defasados em relação às tabelas de evento.

**Decisão:** essa é uma limitação estrutural e amplamente aceita do modelo de counters do Cassandra. O risco prático é mínimo — requer que a aplicação falhe exatamente na janela de milissegundos entre o BATCH e os UPDATEs. Em caso de deriva detectada, os contadores podem ser reconstruídos com `seed.py --reset` seguido de reinserção dos dados. A alternativa (substituir counters por `COUNT(*)` sob demanda) trocaria a inconsistência eventual por latência proporcional ao volume — incompatível com o requisito de estatísticas em tempo real.
