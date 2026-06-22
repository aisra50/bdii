"""Popula o cluster com eventos de exemplo (milhares de registros).

Uso:
  python seed.py                 # insere 5000 eventos
  python seed.py --n 10000       # insere 10000 eventos
  python seed.py --reset         # zera as tabelas antes de inserir
  python seed.py --n 0 --reset   # apenas limpa tudo
"""
import argparse
import random
from datetime import datetime, timedelta

from db import conectar
from model import (Evento, TIPOS, STATUS, REPORTANTES, BAIRROS, CIDADE_PADRAO)
from repository import Repositorio

DESCRICOES = {
    "Acidente de transito": "Colisao entre veiculos na via",
    "Alagamento": "Rua completamente interditada por agua",
    "Queda de energia": "Falta de energia afetando o quarteirao",
    "Incendio": "Foco de incendio em edificacao",
    "Problema no transporte publico": "Onibus quebrado bloqueando a faixa",
    "Vazamento de agua": "Vazamento de agua na calcada",
    "Interdicao de via": "Via interditada para obras",
    "Deslizamento de terra": "Deslizamento em encosta proxima",
    "Tiroteio": "Disparos de arma de fogo registrados",
}

# Tabelas a limpar no --reset (inclui as counter).
TABELAS = [
    "eventos_por_id", "eventos_por_tipo", "eventos_por_periodo",
    "eventos_por_gravidade", "eventos_por_cidade",
    "contagem_por_tipo", "contagem_por_bairro", "contagem_por_dia",
]

# Intervalo das datas geradas (cobre o exemplo do enunciado: 01/05-31/05/2025).
INICIO = datetime(2025, 1, 1)
FIM = datetime(2025, 6, 30, 23, 59, 59)


def gerar_evento(i: int) -> Evento:
    tipo = random.choice(TIPOS)
    bairro = random.choice(list(BAIRROS.keys()))
    lat0, lon0 = BAIRROS[bairro]
    # Jitter de ~ +/- 1.5 km em torno do centro do bairro.
    lat = lat0 + random.uniform(-0.015, 0.015)
    lon = lon0 + random.uniform(-0.015, 0.015)
    dt = INICIO + timedelta(seconds=random.randint(0, int((FIM - INICIO).total_seconds())))
    reportante_tipo = random.choice(REPORTANTES)
    prefixo = "USR" if reportante_tipo == "Cidadao" else "SEN"
    return Evento(
        id_evento=f"EVT{i:05d}",
        tipo=tipo,
        descricao=DESCRICOES[tipo],
        data_hora=dt,
        gravidade=random.randint(1, 5),
        status=random.choice(STATUS),
        bairro=bairro,
        cidade=CIDADE_PADRAO,
        latitude=round(lat, 6),
        longitude=round(lon, 6),
        reportante_tipo=reportante_tipo,
        reportante_id=f"{prefixo}{random.randint(1, 999):03d}",
    )


def resetar(session):
    print("Limpando tabelas...")
    for t in TABELAS:
        session.execute(f"TRUNCATE {t}")
    print("Tabelas limpas.")


def main():
    ap = argparse.ArgumentParser(description="Seed de eventos de ocorrencias urbanas")
    ap.add_argument("--n", type=int, default=5000, help="quantidade de eventos (default 5000)")
    ap.add_argument("--reset", action="store_true", help="zera as tabelas antes de inserir")
    args = ap.parse_args()

    session = conectar()
    repo = Repositorio(session)

    if args.reset:
        resetar(session)

    if args.n <= 0:
        print("Nada a inserir (--n <= 0).")
        return

    print(f"Inserindo {args.n} eventos...")
    for i in range(1, args.n + 1):
        repo.inserir(gerar_evento(i))
        if i % 500 == 0:
            print(f"  {i}/{args.n} inseridos")
    print(f"Concluido: {args.n} eventos inseridos.")


if __name__ == "__main__":
    main()
