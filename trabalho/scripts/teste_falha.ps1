# Teste de tolerancia a falhas (item 7) - PowerShell (host Windows).
# Roteiro: inserir dados -> derrubar um no -> consultar -> verificar que segue
# funcionando. Execute a partir da pasta `trabalho/`:
#   ./scripts/teste_falha.ps1

$ErrorActionPreference = "Stop"

function Passo($txt) { Write-Host "`n==== $txt ====" -ForegroundColor Cyan }

Passo "1. Status do cluster (esperado: 3 nos UN)"
docker compose exec cassandra1 nodetool status

Passo "2. Garantindo dados (seed 5000 eventos, com reset)"
docker compose exec app python seed.py --n 5000 --reset

Passo "3. Consulta com cluster completo (estatisticas por tipo)"
docker compose exec cassandra1 cqlsh -e "SELECT * FROM ocorrencias.contagem_por_tipo;"

Passo "4. Derrubando o no cassandra3"
docker compose stop cassandra3

Write-Host "Aguardando o gossip detectar a queda (15s)..."
Start-Sleep -Seconds 15

Passo "5. Status do cluster (esperado: cassandra3 = DN, 2 nos UN)"
docker compose exec cassandra1 nodetool status

Passo "6. Consultas COM 1 NO FORA (RF=3, QUORUM=2 -> deve funcionar)"
docker compose exec app python -c "from db import conectar; from repository import Repositorio; r=Repositorio(conectar()); print('Por tipo (Alagamento):', len(r.consultar_por_tipo('Alagamento'))); print('Gravidade > 3:', len(r.consultar_por_gravidade(3))); print('Estatisticas por tipo:', r.estatisticas_por_tipo())"

Passo "7. Inserindo um novo evento COM 1 NO FORA (deve funcionar)"
docker compose exec app python -c "from datetime import datetime; from db import conectar; from model import Evento, CIDADE_PADRAO; from repository import Repositorio; r=Repositorio(conectar()); e=Evento('EVT-FALHA','Alagamento','Insercao durante falha',datetime.now(),5,'Aberto','Centro',CIDADE_PADRAO,-22.9068,-43.1729,'Cidadao','USR999'); r.inserir(e); print('Inserido com 1 no fora:', e.id_evento)"

Passo "8. Religando cassandra3 (rejoin + reparo via hinted handoff/read-repair)"
docker compose start cassandra3
Write-Host "Aguardando rejoin (30s)..."
Start-Sleep -Seconds 30
docker compose exec cassandra1 nodetool status

Write-Host "`nTeste de tolerancia a falhas concluido." -ForegroundColor Green
