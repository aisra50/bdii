# Imagem fixa em 3.12: o cassandra-driver tem wheels estaveis para esta versao
# (evita problemas de compilacao com Python muito novo no host).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# O comando real e definido no docker-compose (container fica ocioso e os
# scripts sao executados via `docker compose exec app python ...`).
CMD ["python", "--version"]
