# PDF Extraction Service

Microserviço que converte PDFs em Markdown usando [Marker](https://github.com/VikParuchuri/marker), com fila assíncrona e persistência em PostgreSQL.

## Features

- Upload de PDF via HTTP (multipart/form-data)
- Processamento assíncrono com fila (asyncio.Queue, max 50 jobs)
- Conversão PDF → Markdown via Marker (GPU/CPU)
- Persistência dos documentos em PostgreSQL
- Detecção de duplicatas via SHA-256 do conteúdo
- Tracking de tempo de processamento
- Cleanup automático de jobs expirados
- Structured logging (structlog)
- Migrations automáticas (Alembic)

## Stack

FastAPI · Marker · PostgreSQL · SQLAlchemy (async) · Alembic · structlog · Docker · uv

## Quick Start

### Pré-requisitos

- Docker e Docker Compose
- NVIDIA Container Toolkit (para GPU, opcional)

### Setup

```bash
# Criar a rede Docker
docker network create pdf-extraction-network

# Subir os serviços
docker compose up -d
```

O container roda `alembic upgrade head` automaticamente antes de iniciar o app.

### Desenvolvimento Local

```bash
# Instalar dependências
uv sync

# Subir só o PostgreSQL
docker compose up postgres -d

# Rodar o app
uv run python main.py
```

## API

### Endpoints

| Método | Rota                  | Descrição                           |
|--------|-----------------------|-------------------------------------|
| POST   | `/converter`          | Upload PDF para conversão           |
| GET    | `/result/{job_id}`    | Status do job (polling)             |
| GET    | `/document/{job_id}`  | Documento convertido (PostgreSQL)   |
| GET    | `/health`             | Health check                        |

### Fluxo

```
1. POST /converter (PDF)    → 202 { job_id, status: "QUEUED" }
                               ou 200 { Document }  (duplicata)
2. GET /result/{job_id}     → polling até "DONE" ou "ERROR"
3. GET /document/{job_id}   → Document completo em Markdown
```

### Exemplo

```bash
# Enviar PDF
curl -X POST http://localhost:8503/converter \
  -F "file=@documento.pdf"

# Checar status
curl http://localhost:8503/result/{job_id}

# Buscar documento convertido
curl http://localhost:8503/document/{job_id}
```

## Configuração

Variáveis de ambiente (`.env`):

| Variável        | Default               | Descrição                     |
|-----------------|-----------------------|-------------------------------|
| `HOST`          | `0.0.0.0`             | Host do servidor              |
| `PORT`          | `8503`                | Porta do servidor             |
| `TORCH_DEVICE`  | `cuda`                | Device: `cuda` ou `cpu`       |
| `QUEUE_MAXSIZE` | `50`                  | Tamanho máximo da fila        |
| `JOB_TTL_MINUTES` | `30`               | TTL dos jobs concluídos       |
| `DB_HOST`       | `localhost`           | Host do PostgreSQL            |
| `DB_PORT`       | `5431`                | Porta do PostgreSQL           |
| `DB_NAME`       | `pdf_extraction_db`   | Nome do banco                 |
| `DB_USER`       | `postgres`            | Usuário do banco              |
| `DB_PASSWORD`   | `postgres`            | Senha do banco                |
| `TZ`            | `America/Sao_Paulo`   | Timezone                      |

## Estrutura do Projeto

```
├── main.py                # Entry point
├── src/
│   ├── config.py          # Settings (pydantic-settings)
│   ├── schemas.py         # Pydantic models
│   ├── converter.py       # Wrapper do Marker
│   ├── worker.py          # Fila + worker
│   ├── api.py             # FastAPI app + rotas
│   ├── logging.py         # Configuração structlog
│   └── db/
│       ├── database.py    # Engine + session (asyncpg)
│       ├── models.py      # SQLAlchemy model
│       └── repository.py  # CRUD
├── alembic/               # Migrations
├── docker-compose.yml
├── Dockerfile
└── docs/
    ├── api_contract.md    # Contrato detalhado da API
    └── overview.md        # Visão geral da arquitetura
```

## Docs

- [API Contract](docs/api_contract.md) — Contrato detalhado da API com schemas
- [Overview](docs/overview.md) — Visão geral da arquitetura e decisões

## Deploy em outra máquina (sem registry)

```bash
# Exportar imagem
docker save pdf-extraction-service-pdf-extraction | gzip > pdf-extraction.tar.gz

# Na outra máquina
docker load -i pdf-extraction.tar.gz
docker network create pdf-extraction-network
docker compose up -d
```