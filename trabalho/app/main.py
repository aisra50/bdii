"""Menu interativo (CLI) da plataforma de Ocorrencias Urbanas.

Cobre as funcionalidades obrigatorias 6.1 a 6.6. Execute com:
  docker compose exec app python main.py
"""
import uuid
from datetime import datetime

from db import conectar
from model import (Evento, TIPOS, STATUS, REPORTANTES, BAIRROS, CIDADE_PADRAO)
from repository import Repositorio


# --------------------------------------------------------------------- helpers
def escolher_da_lista(titulo: str, itens: list) -> str:
    print(titulo)
    for i, it in enumerate(itens, 1):
        print(f"  {i}) {it}")
    while True:
        op = input("Escolha o numero: ").strip()
        if op.isdigit() and 1 <= int(op) <= len(itens):
            return itens[int(op) - 1]
        print("Opcao invalida.")


def ler_data(rotulo: str) -> datetime:
    while True:
        txt = input(f"{rotulo} (AAAA-MM-DD ou AAAA-MM-DDTHH:MM): ").strip()
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(txt, fmt)
            except ValueError:
                continue
        print("Formato invalido. Ex.: 2025-05-01")


def ler_float(rotulo: str) -> float:
    while True:
        try:
            return float(input(f"{rotulo}: ").strip().replace(",", "."))
        except ValueError:
            print("Numero invalido.")


def ler_int(rotulo: str, minimo: int, maximo: int) -> int:
    while True:
        txt = input(f"{rotulo} ({minimo}-{maximo}): ").strip()
        if txt.isdigit() and minimo <= int(txt) <= maximo:
            return int(txt)
        print("Valor invalido.")


def imprimir_eventos(rows, limite: int = 50):
    total = len(rows)
    print(f"\n{total} evento(s) encontrado(s)" +
          (f" (mostrando {limite})" if total > limite else "") + ":")
    for r in rows[:limite]:
        print(f"  [{r.id_evento}] {r.tipo} grav={r.gravidade} {r.status} "
              f"- {r.bairro} @ {r.data_hora:%Y-%m-%d %H:%M} :: {r.descricao}")
    print()


# --------------------------------------------------------------------- acoes
def acao_inserir(repo: Repositorio):
    print("\n--- 6.1 Inserir evento ---")
    tipo = escolher_da_lista("Tipo:", TIPOS)
    bairro = escolher_da_lista("Bairro:", list(BAIRROS.keys()))
    lat0, lon0 = BAIRROS[bairro]
    descricao = input("Descricao: ").strip() or "Sem descricao"
    gravidade = ler_int("Gravidade", 1, 5)
    status = escolher_da_lista("Status:", STATUS)
    usar_centro = input(f"Usar coordenadas do centro de {bairro}? (S/n): ").strip().lower()
    if usar_centro in ("", "s", "sim"):
        lat, lon = lat0, lon0
    else:
        lat = ler_float("Latitude")
        lon = ler_float("Longitude")
    rep_tipo = escolher_da_lista("Reportante:", REPORTANTES)
    rep_id = input("Identificador do reportante (ex.: USR001): ").strip() or "USR000"

    evento = Evento(
        id_evento=f"EVT{uuid.uuid4().hex[:12].upper()}",
        tipo=tipo, descricao=descricao, data_hora=datetime.now(),
        gravidade=gravidade, status=status, bairro=bairro, cidade=CIDADE_PADRAO,
        latitude=lat, longitude=lon, reportante_tipo=rep_tipo, reportante_id=rep_id,
    )
    repo.inserir(evento)
    print(f"\nEvento inserido: {evento}\n")


def acao_por_tipo(repo: Repositorio):
    print("\n--- 6.2 Consulta por tipo ---")
    tipo = escolher_da_lista("Tipo:", TIPOS)
    imprimir_eventos(repo.consultar_por_tipo(tipo))


def acao_por_periodo(repo: Repositorio):
    print("\n--- 6.3 Consulta por periodo ---")
    ini = ler_data("Data inicial")
    fim = ler_data("Data final")
    if fim < ini:
        ini, fim = fim, ini
    imprimir_eventos(repo.consultar_por_periodo(ini, fim))


def acao_geografica(repo: Repositorio):
    print("\n--- 6.4 Consulta geografica (raio em km) ---")
    print("Dica: centro do Rio ~ -22.9068, -43.1729")
    lat = ler_float("Latitude do ponto")
    lon = ler_float("Longitude do ponto")
    raio = ler_float("Raio (km)")
    resultados = repo.consultar_geografico(lat, lon, raio)
    print(f"\n{len(resultados)} evento(s) dentro de {raio} km:")
    for dist, r in resultados[:50]:
        print(f"  {dist:5.2f} km [{r.id_evento}] {r.tipo} - {r.bairro} "
              f"@ {r.data_hora:%Y-%m-%d %H:%M}")
    print()


def acao_por_gravidade(repo: Repositorio):
    print("\n--- 6.5 Consulta por gravidade ---")
    limite = ler_int("Listar eventos com gravidade SUPERIOR a", 0, 5)
    imprimir_eventos(repo.consultar_por_gravidade(limite))


def acao_estatisticas(repo: Repositorio):
    print("\n--- 6.6 Estatisticas ---")
    print("\nQuantidade por tipo:")
    print(f"  {'Tipo':<32} {'Total':>8}")
    for tipo, total in repo.estatisticas_por_tipo():
        print(f"  {tipo:<32} {total:>8}")

    print("\nQuantidade por bairro:")
    print(f"  {'Bairro':<20} {'Total':>8}")
    for bairro, total in repo.estatisticas_por_bairro(CIDADE_PADRAO):
        print(f"  {bairro:<20} {total:>8}")

    ano = ler_int("\nEvolucao temporal - informe o ano", 2000, 2100)
    print(f"\nQuantidade de eventos por dia em {ano}:")
    linhas = repo.evolucao_por_dia(ano)
    for dia, total in linhas:
        print(f"  {dia}  {total}")
    if not linhas:
        print("  (sem dados nesse ano)")
    print()


MENU = """
=== Plataforma de Ocorrencias Urbanas (Cassandra) ===
  1) Inserir evento                (6.1)
  2) Consultar por tipo            (6.2)
  3) Consultar por periodo         (6.3)
  4) Consulta geografica (raio km) (6.4)
  5) Consultar por gravidade       (6.5)
  6) Estatisticas                  (6.6)
  0) Sair
"""


def main():
    session = conectar()
    repo = Repositorio(session)
    acoes = {
        "1": acao_inserir, "2": acao_por_tipo, "3": acao_por_periodo,
        "4": acao_geografica, "5": acao_por_gravidade, "6": acao_estatisticas,
    }
    while True:
        print(MENU)
        op = input("Opcao: ").strip()
        if op == "0":
            print("Ate logo!")
            return
        acao = acoes.get(op)
        if not acao:
            print("Opcao invalida.")
            continue
        try:
            acao(repo)
        except Exception as exc:  # noqa: BLE001 - menu nao deve quebrar
            print(f"Erro ao executar a operacao: {exc}")


if __name__ == "__main__":
    main()
