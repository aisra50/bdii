#!/usr/bin/env bash
# Teste de tolerancia a falhas (item 7) - bash.
# Roteiro: inserir dados -> derrubar um no -> consultar -> verificar que segue
# funcionando. Execute a partir da pasta `trabalho/`:
#   bash scripts/teste_falha.sh
set -euo pipefail

passo() { echo -e "\n==== $1 ===="; }

passo "1. Status do cluster (esperado: 3 nos UN)"
docker compose exec cassandra1 nodetool status

passo "2. Garantindo dados (seed 5000 eventos, com reset)"
docker compose exec app python seed.py --n 5000 --reset

passo "3. Consulta com cluster completo (estatisticas por tipo)"
docker compose exec cassandra1 cqlsh -e "SELECT * FROM ocorrencias.contagem_por_tipo;"

passo "4. Derrubando o no cassandra3"
docker compose stop cassandra3

echo "Aguardando o gossip detectar a queda (15s)..."
sleep 15

passo "5. Status do cluster (esperado: cassandra3 = DN, 2 nos UN)"
docker compose exec cassandra1 nodetool status

passo "6. Consultas COM 1 NO FORA (RF=3, QUORUM=2 -> deve funcionar)"
docker compose exec app python -c "from db import conectar; from repository import Repositorio; r=Repositorio(conectar()); print('Por tipo (Alagamento):', len(r.consultar_por_tipo('Alagamento'))); print('Gravidade > 3:', len(r.consultar_por_gravidade(3))); print('Estatisticas por tipo:', r.estatisticas_por_tipo())"

passo "7. Inserindo um novo evento COM 1 NO FORA (deve funcionar)"
docker compose exec app python -c "from datetime import datetime; from db import conectar; from model import Evento, CIDADE_PADRAO; from repository import Repositorio; r=Repositorio(conectar()); e=Evento('EVT-FALHA','Alagamento','Insercao durante falha',datetime.now(),5,'Aberto','Centro',CIDADE_PADRAO,-22.9068,-43.1729,'Cidadao','USR999'); r.inserir(e); print('Inserido com 1 no fora:', e.id_evento)"

passo "8. Religando cassandra3 (rejoin + reparo via hinted handoff/read-repair)"
docker compose start cassandra3
echo "Aguardando rejoin (30s)..."
sleep 30
docker compose exec cassandra1 nodetool status

echo -e "\nTeste de tolerancia a falhas concluido."
