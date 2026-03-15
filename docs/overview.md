# PDF Extraction Service — Visão Geral da Arquitetura

## O que é

Microserviço que recebe arquivos PDF via HTTP, enfileira para processamento sequencial usando [Marker](https://github.com/VikParuchuri/marker), converte para Markdown e persiste o resultado em PostgreSQL.

---

## Diagrama de Fluxo

```
Cliente                    FastAPI (api.py)                Worker (worker.py)            PostgreSQL
  │                             │                               │                          │
  │  POST /converter            │                               │                          │
  │  (multipart/form-data)      │                               │                          │
  ├────────────────────────────►│                               │                          │
  │                             │  hash(pdf_bytes)              │                          │
  │                             │  get_by_hash()───────────────────────────────────────────►│
  │                             │◄──────────────────────────────────────────────────────────┤
  │                             │                               │                          │
  │                             │  [duplicata?] ◄── sim ── return 200 Document             │
  │                             │  [novo?] ◄── não ── enqueue()                            │
  │  ◄── 202 {job_id, QUEUED} ─┤                               │                          │
  │                             │                               │                          │
  │                             │          asyncio.Queue        │                          │
  │                             │  ─────────────────────────►   │                          │
  │                             │                               │  converter.convert()     │
  │                             │                               │  (asyncio.to_thread)     │
  │                             │                               │         │                │
  │                             │                               │  Marker (GPU/CPU)        │
  │                             │                               │         │                │
  │                             │                               │  Document                │
  │                             │                               │  + processing_time_ms    │
  │                             │                               │         │                │
  │                             │                               │  repository.save() ─────►│
  │                             │                               │  status = DONE           │
  │                             │                               │                          │
  │  GET /result/{job_id}       │                               │                          │
  ├────────────────────────────►│  job.status (in-memory)       │                          │
  │  ◄── 200 {status: DONE} ───┤                               │                          │
  │                             │                               │                          │
  │  GET /document/{job_id}     │                               │                          │
  ├────────────────────────────►│  get_by_job_id() ────────────────────────────────────────►│
  │  ◄── 200 {Document} ───────┤◄──────────────────────────────────────────────────────────┤
```

---

## Estrutura do Projeto

```
pdf-extraction-service/
├── main.py                    # Entry point: configura logging + uvicorn
├── pyproject.toml             # Dependências (gerenciadas com uv)
├── Dockerfile                 # Imagem PyTorch + app
├── docker-compose.yml         # App + PostgreSQL
├── alembic.ini                # Configuração do Alembic
├── .env                       # Variáveis de ambiente
├── static/
│   └── warmup.pdf             # PDF para warmup dos modelos no startup
├── alembic/
│   ├── env.py                 # Configuração async do Alembic
│   └── versions/              # Migrations
├── src/
│   ├── config.py              # Settings (pydantic-settings)
│   ├── schemas.py             # Pydantic models: JobStatus, JobResponse, Document
│   ├── converter.py           # PDFConverter: wrapper do Marker
│   ├── worker.py              # Job dataclass + JobManager (fila + worker)
│   ├── api.py                 # FastAPI app, rotas, lifespan
│   ├── logging.py             # Configuração do structlog
│   └── db/
│       ├── database.py        # Engine + session maker (asyncpg)
│       ├── models.py          # SQLAlchemy model: DocumentModel
│       └── repository.py      # CRUD: save, get_by_job_id, get_by_hash
└── docs/
    ├── api_contract.md        # Contrato da API
    └── overview.md            # Este arquivo
```

---

## Componentes

### config.py
Configurações via `pydantic-settings` com `.env`. Campos: host, port, queue_maxsize, torch_device, job_ttl_minutes, db_host/port/user/password/name. Property `db_url` monta a connection string para asyncpg.

### schemas.py
- **JobStatus** — enum: QUEUED, PROCESSING, DONE, ERROR
- **JobResponse** — resposta de status: job_id, status, error
- **Document** — documento convertido: job_id, content_hash, title, content, source, language, metadata, processing_time_ms, processed_at

### converter.py
**PDFConverter** — wrapper do Marker. Carrega modelos uma vez no `__init__`. Método `convert(pdf_bytes, source, job_id)` é síncrono e bloqueante (GPU), chamado via `asyncio.to_thread()` pelo worker. Gera `content_hash` (SHA-256, 16 chars) para detecção de duplicatas.

### worker.py
- **Job** — dataclass com job_id, pdf_bytes, source, status, created_at, result (Future), error
- **JobManager** — gerencia `asyncio.Queue` (maxsize 50) e dict de jobs em memória. `process_queue()` roda em loop infinito consumindo jobs, convertendo PDFs e salvando no banco. `cleanup_old_jobs()` remove jobs expirados (configurable via `job_ttl_minutes`).

### api.py
FastAPI com lifespan que:
1. Instancia PDFConverter (carrega modelos)
2. Faz warmup com PDF de teste
3. Cria JobManager e inicia worker + cleanup tasks

Rotas:
- `POST /converter` — upload PDF, detecção de duplicatas, enfileira job
- `GET /result/{job_id}` — status do job (in-memory)
- `GET /document/{job_id}` — busca Document no PostgreSQL
- `GET /health` — health check

### db/
- **database.py** — engine async (asyncpg), session maker, Base class
- **models.py** — DocumentModel (tabela `documents`), PK em job_id, unique index em content_hash
- **repository.py** — funções: save(), get_by_job_id(), get_by_hash()

---

## Decisões Arquiteturais

| Decisão | Justificativa |
|---------|---------------|
| **In-memory para status de jobs** | Redis seria over-engineering para armazenar um enum de status. O dict `_jobs` é suficiente para o volume esperado. |
| **PostgreSQL para Documents** | Persistência durável dos documentos convertidos. Permite busca por hash (duplicatas) e recuperação após restart. |
| **asyncio.Queue (não Celery/Redis)** | Processamento sequencial na GPU. Apenas 1 job por vez. Queue nativa do asyncio é suficiente. |
| **asyncio.to_thread()** | O Marker é síncrono e bloqueante (GPU). `to_thread()` libera o event loop para processar HTTP enquanto a conversão roda. |
| **SHA-256 para duplicatas** | Hash dos bytes do PDF (16 chars). Evita reprocessamento de PDFs idênticos. |
| **Alembic async** | Migrations versionadas. Roda automaticamente no startup do container (`alembic upgrade head`). |
| **Warmup no startup** | Primeira inferência do Marker é lenta (carrega pesos). Warmup com PDF de teste reduz latência do primeiro job real. |

---

## Stack Tecnológica

| Componente | Tecnologia |
|------------|------------|
| Framework Web | FastAPI + Uvicorn |
| Conversão PDF | Marker (surya layout, OCR, table detection) |
| Banco de Dados | PostgreSQL 16 (Alpine) |
| ORM | SQLAlchemy 2.0 (async) + asyncpg |
| Migrations | Alembic (async template) |
| Config | pydantic-settings |
| Logging | structlog |
| Container | Docker (PyTorch base image) |
| Package Manager | uv |
| Python | >= 3.11 |
