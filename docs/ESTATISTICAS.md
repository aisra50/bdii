# Estatísticas — Plataforma de Ocorrências Urbanas

A funcionalidade **6.6** oferece três visões estatísticas sobre os eventos registrados:

| # | Estatística | O que mostra |
|---|---|---|
| 1 | Quantidade por tipo | Total de eventos agrupados por categoria |
| 2 | Quantidade por bairro | Total de eventos agrupados por bairro |
| 3 | Evolução temporal | Total de eventos por dia em um determinado ano |

---

## Como consultar

1. Acesse o container da aplicação:

   ```bash
   docker compose exec app python main.py
   ```

2. Selecione a opção **6**:

   ```
   Opcao: 6
   ```

3. O sistema exibe automaticamente as duas primeiras estatísticas e então solicita o ano para a evolução temporal:

---

### Estatística 1 — Quantidade por tipo

Exibida automaticamente, ordenada do tipo com mais eventos para o com menos:

```
Quantidade por tipo:
  Tipo                             Total
  Alagamento                         612
  Acidente de Transito               589
  Incendio                           541
  Problema no Transporte Publico     530
  Queda de Energia                   521
  Interdicao de Via                  510
  Vazamento de Agua                  508
  Deslizamento                       498
  Tiroteio                           491
```

---

### Estatística 2 — Quantidade por bairro

Exibida em seguida, ordenada do bairro com mais eventos para o com menos:

```
Quantidade por bairro:
  Bairro                  Total
  Centro                    542
  Copacabana                531
  Tijuca                    498
  Botafogo                  487
  Madureira                 476
  Barra da Tijuca           465
  Ipanema                   461
  Maracana                  453
  Campo Grande              448
  Bangu                     439
```

---

### Estatística 3 — Evolução temporal por dia

O sistema solicita o ano e exibe a contagem de eventos por dia:

```
Evolucao temporal - informe o ano (2000-2100): 2025

Quantidade de eventos por dia em 2025:
  2025-01-01   18
  2025-01-02   22
  2025-01-03   19
  ...
  2025-06-30   27
```

Se não houver dados para o ano informado, o sistema exibe `(sem dados nesse ano)`.

---

## O que ocorre no Cassandra

As três estatísticas são respondidas por **tabelas de contadores dedicadas** — sem aggregation em tempo de consulta. Os totais são mantidos atualizados a cada inserção de evento.

---

### Por que contadores e não `COUNT(*)`

Uma abordagem alternativa seria fazer `SELECT COUNT(*) FROM eventos_por_tipo WHERE tipo = 'Alagamento'` a cada consulta. No Cassandra isso seria problemático: `COUNT(*)` varre toda a partição linha por linha. Com milhares de eventos, a resposta ficaria lenta e custosa.

A solução adotada é manter **tabelas `counter`** incrementadas no momento da inserção. A leitura estatística vira uma simples busca de um valor já pronto — custo O(1) independente do volume.

---

### Tabela 1 — `contagem_por_tipo`

**Estrutura:**
```sql
CREATE TABLE contagem_por_tipo (
  tipo   text PRIMARY KEY,
  total  counter
)
```

**Query executada:**
```sql
SELECT tipo, total FROM contagem_por_tipo;
```

Retorna todas as linhas da tabela (uma por tipo de ocorrência). O ordenamento por total é feito no cliente Python após a leitura.

**Como o contador é incrementado** — a cada inserção de evento:
```sql
UPDATE contagem_por_tipo SET total = total + 1 WHERE tipo = 'Alagamento';
```

---

### Tabela 2 — `contagem_por_bairro`

**Estrutura:**
```sql
CREATE TABLE contagem_por_bairro (
  cidade  text,
  bairro  text,
  total   counter,
  PRIMARY KEY ((cidade), bairro)
)
```

A cidade é a partition key: todos os bairros de uma cidade ficam na mesma partição, permitindo buscar todos de uma vez com uma única query.

**Query executada:**
```sql
SELECT bairro, total FROM contagem_por_bairro WHERE cidade = 'Rio de Janeiro';
```

**Como o contador é incrementado:**
```sql
UPDATE contagem_por_bairro SET total = total + 1
 WHERE cidade = 'Rio de Janeiro' AND bairro = 'Centro';
```

---

### Tabela 3 — `contagem_por_dia`

**Estrutura:**
```sql
CREATE TABLE contagem_por_dia (
  ano  int,
  dia  date,
  total counter,
  PRIMARY KEY ((ano), dia)
) WITH CLUSTERING ORDER BY (dia ASC)
```

O ano é a partition key: todos os dias de um ano ficam na mesma partição, já ordenados por `dia ASC`. Isso permite retornar a série temporal completa de um ano com uma única query, sem ordenação extra.

**Query executada:**
```sql
SELECT dia, total FROM contagem_por_dia WHERE ano = 2025;
```

**Como o contador é incrementado:**
```sql
UPDATE contagem_por_dia SET total = total + 1
 WHERE ano = 2025 AND dia = 2025-05-01;
```

---

### Por que os contadores são atualizados fora do BATCH

Ao inserir um evento, as 5 tabelas principais são gravadas via `BATCH LOGGED`. Os 3 contadores são atualizados em operações **separadas**, logo após o batch:

```python
# repository.py — inserir()
self.s.execute(self.upd_cont_tipo,   (e.tipo,))
self.s.execute(self.upd_cont_bairro, (e.cidade, e.bairro))
self.s.execute(self.upd_cont_dia,    (dia.year, dia))
```

Isso é uma restrição do Cassandra: **tabelas `counter` não podem ser misturadas com tabelas normais em um mesmo batch**. Cada `UPDATE counter` é atomico por si só — a operação `total + 1` é garantida pelo Cassandra mesmo sob concorrência.

---

### Fluxo completo

```
main.py (opção 6)
  └─ repository.estatisticas_por_tipo()
  │    └─ SELECT tipo, total FROM contagem_por_tipo
  │              ↓ leitura QUORUM
  │         linhas ordenadas por total DESC no cliente
  │
  └─ repository.estatisticas_por_bairro("Rio de Janeiro")
  │    └─ SELECT bairro, total FROM contagem_por_bairro WHERE cidade = 'Rio de Janeiro'
  │              ↓ leitura QUORUM
  │         linhas ordenadas por total DESC no cliente
  │
  └─ repository.evolucao_por_dia(2025)
       └─ SELECT dia, total FROM contagem_por_dia WHERE ano = 2025
                 ↓ leitura QUORUM
            linhas já ordenadas por dia ASC (clustering order)
```

Todas as três queries leem diretamente de contadores pré-calculados — a resposta é imediata independente do número de eventos no banco.
