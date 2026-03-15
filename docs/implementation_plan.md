# Plano de Implementação — PDF Extraction Service

## Visão Geral

Microserviço que recebe arquivos PDF via HTTP, enfileira para processamento sequencial (GPU ou CPU) usando Marker, converte para Markdown e persiste o resultado em PostgreSQL.

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
│   ├── __init__.py
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
    ├── implementation_plan.md # Este arquivo
    ├── api_contract.md        # Contrato da API
    └── overview.md            # Visão geral da arquitetura
```

---

## Etapas de Implementação

### Etapa 1 — Configuração do Projeto (`pyproject.toml`)

- Definir metadados do projeto e dependências:
  - `fastapi`, `uvicorn`, `python-multipart`, `marker-pdf`, `structlog`
  - `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pydantic-settings`
- Python `>=3.11`
- Usar `uv` como gerenciador de pacotes

### Etapa 2 — Configurações (`src/config.py`)

- Classe `Settings` usando `pydantic-settings` (`BaseSettings`)
- Campos:
  - `log_level`: `"DEBUG"`
  - `timezone`: `"UTC"` (seta `os.environ["TZ"]` e chama `time.tzset()`)
  - `host`: `"0.0.0.0"`
  - `port`: `8503`
  - `queue_maxsize`: `50`
  - `torch_device`: `"cuda"`
  - `job_ttl_minutes`: `30`
  - `db_host`: `"localhost"`
  - `db_port`: `5431`
  - `db_user`: `"postgres"`
  - `db_password`: `"postgres"`
  - `db_name`: `"pdf_extraction_db"`
- **Sem prefixo** de ambiente (variáveis lidas diretamente: `HOST`, `PORT`, etc.)
- Carregamento automático de `.env`
- Property `db_url` → `postgresql+asyncpg://...`
- Singleton via `@lru_cache()`

### Etapa 3 — Logging (`src/logging.py`)

- Configuração do `structlog` com processors:
  - `TimeStamper(fmt="iso", utc=False)` — timestamps no fuso local
  - `add_log_level`, `StackInfoRenderer`, `format_exc_info`
  - `JSONRenderer` para output estruturado
- Handlers: console (`stderr`) + arquivo (`logs/app.log`)
- `HealthCheckFilter` para silenciar logs do `GET /health`

### Etapa 4 — Schemas de Request/Response (`src/schemas.py`)

- `JobStatus(str, Enum)` — valores: `"QUEUED"`, `"PROCESSING"`, `"DONE"`, `"ERROR"`
- `JobResponse` — retornado pelo `POST /converter` e `GET /result/{job_id}`:
  - `job_id: str`
  - `status: JobStatus`
  - `error: str | None`
- `Document` — documento convertido do PDF:
  - `job_id: str`
  - `content_hash: str` (SHA-256 dos bytes do PDF, primeiros 16 chars)
  - `title: str` (extraído do primeiro `# heading` do markdown, fallback para `source`)
  - `content: str` (markdown completo)
  - `source: str` (nome do arquivo, URL, etc.)
  - `language: str | None`
  - `metadata: dict[str, Any]` (tamanho do arquivo + metadados do Marker)
  - `processing_time_ms: int | None`
  - `processed_at: datetime` (via `datetime.now`)

### Etapa 5 — Camada de Banco de Dados (`src/db/`)

**`database.py`:**
- `create_async_engine()` com `pool_size=5`, `max_overflow=10`
- `async_sessionmaker()` com `expire_on_commit=False`
- `Base` declarativa do SQLAlchemy

**`models.py` — `DocumentModel`:**
- Tabela `documents`
- Colunas:
  - `job_id: String` (PK)
  - `content_hash: String` (unique, indexed)
  - `title: String`
  - `content: Text`
  - `source: String`
  - `language: String | None`
  - `metadata_: JSONB` (renomeado com `_` para evitar conflito com SQLAlchemy)
  - `processing_time_ms: Integer | None`
  - `processed_at: DateTime`
- Index único em `content_hash` para detecção de duplicatas

**`repository.py`:**
- `save(session, document: Document)` — insert ou update
- `get_by_job_id(session, job_id: str) -> Document | None`
- `get_by_hash(session, content_hash: str) -> Document | None`
- `_to_document(model: DocumentModel) -> Document` — helper de conversão

### Etapa 6 — Wrapper do Marker (`src/converter.py`)

- Classe `PDFConverter`:
  - `__init__(torch_device: str)` — instancia `PdfConverter(artifact_dict=create_model_dict(device=torch_device), config={"device": torch_device})` e carrega todos os modelos. **Chamado uma única vez no startup**
  - `convert(pdf_bytes: bytes, source: str, job_id: str) -> Document` — função síncrona e bloqueante (GPU/CPU):
    - Valida que `pdf_bytes` não está vazio
    - Escreve bytes em `tempfile.NamedTemporaryFile(suffix=".pdf")`
    - Chama `self._converter(str(temp_path))` → `rendered`
    - Extrai markdown: `rendered.markdown`
    - Gera `content_hash` via `hashlib.sha256(pdf_bytes).hexdigest()[:16]`
    - Extrai `title` via `_extract_title()`
    - Monta `metadata` com `source_size_bytes` e `pdf_metadata` (se disponível)
    - Retorna `Document`
    - **`finally`**: remove arquivo temporário (`temp_path.unlink(missing_ok=True)`)
    - Executada em thread separada via `asyncio.to_thread()`
  - `_extract_title(markdown: str, fallback: str) -> str` — extrai o primeiro `# heading` do markdown; usa `source` como fallback

### Etapa 7 — Sistema de Fila e Worker (`src/worker.py`)

**Estruturas de dados:**

- `Job` (dataclass):
  - `job_id: str` (UUID4, primeiros 12 chars)
  - `pdf_bytes: bytes`
  - `source: str`
  - `status: JobStatus`
  - `created_at: datetime` (default `datetime.datetime.now`)
  - `result: asyncio.Future`
  - `error: str | None`

**Classe `JobManager`:**

- Atributos:
  - `_queue: asyncio.Queue(maxsize=settings.queue_maxsize)`
  - `_jobs: dict[str, Job]` (armazenamento em memória para status)
  - `_session: async_sessionmaker` (referência da session factory)
- Métodos:
  - `enqueue(pdf_bytes: bytes, source: str) -> str`
    - Gera `job_id` via `uuid4().hex[:12]`
    - Cria `Job` com status `QUEUED`
    - Tenta `_queue.put_nowait(job)` — se cheia, propaga `asyncio.QueueFull`
    - Armazena no dicionário `_jobs`
    - Retorna `job_id`
  - `get_job(job_id: str) -> Job | None`
  - `process_queue(converter: PDFConverter) -> None` (loop infinito do worker)
    - `job = await queue.get()`
    - Status → `PROCESSING`
    - Mede tempo com `time.perf_counter()`
    - `document = await asyncio.to_thread(converter.convert, job.pdf_bytes, job.source, job.job_id)`
    - Calcula `processing_time_ms` e seta no `document`
    - Salva no banco via `repository.save()`
    - Status → `DONE`, seta resultado no `Future`
    - Em caso de erro: status → `ERROR`, seta exceção no `Future`
    - **`finally`**: limpa `job.pdf_bytes = b""` e chama `queue.task_done()`
  - `cleanup_old_jobs() -> None` (tarefa periódica)
    - Loop infinito com `await asyncio.sleep(300)` (a cada 5 minutos)
    - Remove jobs `DONE` ou `ERROR` criados há mais de `job_ttl_minutes`
  - `_remove_expired_jobs(cutoff: float) -> int` — helper que filtra e remove expirados

### Etapa 8 — Aplicação FastAPI (`src/api.py`)

**Lifespan (startup/shutdown):**

- No startup:
  1. Instanciar `PDFConverter(torch_device=settings.torch_device)` — carrega modelos
  2. Warmup com `static/warmup.pdf` via `asyncio.to_thread(converter.convert, ...)` — com try/except (não bloqueia se falhar)
  3. Criar instância de `JobManager`, salvar em `app.state`
  4. Iniciar `asyncio.create_task(job_manager.process_queue(converter))`
  5. Iniciar `asyncio.create_task(job_manager.cleanup_old_jobs())`
- No shutdown:
  1. Cancelar tasks do worker e cleanup

**Endpoints:**

| Método | Rota                 | Descrição                                              |
| ------ | -------------------- | ------------------------------------------------------ |
| `POST` | `/converter`         | Upload PDF, detecção de duplicatas, enfileira job       |
| `GET`  | `/result/{job_id}`   | Status do job (in-memory)                              |
| `GET`  | `/document/{job_id}` | Busca Document no PostgreSQL                           |
| `GET`  | `/health`            | Health check                                           |

**Detalhes dos endpoints:**

- **`POST /converter`**
  - Aceita `file: UploadFile`
  - Valida que o arquivo não está vazio → HTTP 400
  - Calcula `content_hash = sha256(pdf_bytes).hexdigest()[:16]`
  - Busca no banco via `repository.get_by_hash()`:
    - Se encontrado → retorna Document existente com HTTP 200 (duplicata)
    - Se novo → enfileira e retorna `JobResponse` com HTTP 202
  - Se fila cheia: HTTP 503

- **`GET /result/{job_id}`**
  - Busca job via `app.state.job_manager.get_job(job_id)`
  - Se não encontrado: HTTP 404
  - Retorna `JobResponse` com status atual e error (se houver)

- **`GET /document/{job_id}`**
  - Busca no PostgreSQL via `repository.get_by_job_id()`
  - Se não encontrado: HTTP 404
  - Retorna `Document` completo

- **`GET /health`**
  - Retorna `{"status": "ok"}` — HTTP 200

### Etapa 9 — Entry Point (`main.py`)

- Importa `Settings`, `configure_logging`, e a `app` do FastAPI
- Converte `settings.log_level` (string) para inteiro via `getattr(logging, ...)`
- Roda `uvicorn.run(app, host=settings.host, port=settings.port)`

### Etapa 10 — Migrations (Alembic)

- `alembic init -t async alembic` — template async
- Configurar `alembic/env.py`:
  - Importar `get_settings` e `Base` do SQLAlchemy
  - Setar `sqlalchemy.url` a partir de `settings.db_url`
  - Registrar `DocumentModel` para autogenerate
- Gerar migration: `alembic revision --autogenerate -m "create documents table"`
- Aplicar: `alembic upgrade head`

### Etapa 11 — Dockerfile

```dockerfile
FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY src/ src/
COPY main.py .
COPY static/ static/
COPY alembic/ alembic/
COPY alembic.ini .

ENV TORCH_DEVICE=cuda

EXPOSE 8503

CMD ["sh", "-c", "uv run alembic upgrade head && uv run python main.py"]
```

- Imagem `-runtime` (não `-devel`) — sem necessidade de compilação CUDA
- Copia `alembic/` e `alembic.ini` para rodar migrations no startup
- CMD encadeado: roda migrations primeiro, depois inicia o app

### Etapa 12 — Docker Compose (`docker-compose.yml`)

**Serviço `postgres`:**
- Imagem `postgres:16-alpine`
- Variáveis: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `TZ` (do `.env`)
- Porta exposta: `${DB_PORT:-5431}:5432`
- Volume `pgdata` para persistência
- Healthcheck: `pg_isready -U postgres` (interval 5s, timeout 3s, retries 5)

**Serviço `pdf_extraction`:**
- Build do diretório atual (`.`)
- Porta: `8503:8503`
- `env_file: .env` + overrides: `DB_HOST=pdf_extraction_db`, `DB_PORT=5432` (porta interna do container)
- `depends_on: postgres: condition: service_healthy`
- Reserva GPU: `deploy.resources.reservations.devices` (nvidia, count 1, capabilities gpu)
- Restart: `unless-stopped`

**Rede:** `pdf-extraction-network` (`external: true` — criada manualmente pelo usuário)
**Volume:** `pgdata`

### Etapa 13 — Variáveis de Ambiente (`.env`)

```env
HOST=0.0.0.0
PORT=8503
QUEUE_MAXSIZE=50
TORCH_DEVICE=cpu
JOB_TTL_MINUTES=30
TZ=America/Sao_Paulo

DB_HOST=localhost
DB_PORT=5431
DB_NAME=pdf_extraction_db
DB_USER=postgres
DB_PASSWORD=postgres
```

- Sem prefixo `EXTRACTION_` — variáveis lidas diretamente pelo pydantic-settings
- `TORCH_DEVICE=cpu` para desenvolvimento (usar `cuda` em produção)
- `DB_PORT=5431` refere-se à porta exposta no host; dentro do Docker Compose o serviço usa `5432`

### Etapa 14 — Documentação

- `README.md` — features, quick start, API, configuração, estrutura, deploy
- `docs/api_contract.md` — contrato detalhado dos 4 endpoints
- `docs/overview.md` — diagrama de arquitetura, componentes, decisões, stack

---

## Decisões Técnicas

| Decisão | Justificativa |
|---------|---------------|
| **Estrutura `src/` + `main.py` na raiz** | Separação clara entre entry point e código de negócio. `main.py` configura logging e inicia uvicorn; `src/api.py` contém o app FastAPI. |
| **In-memory para status de jobs** | Dict `_jobs` suficiente para tracking de status. Redis seria over-engineering para um enum. |
| **PostgreSQL para Documents** | Persistência durável dos documentos convertidos. Permite busca por hash (duplicatas) e recuperação após restart. |
| **asyncio.Queue (não Celery/Redis)** | Processamento sequencial na GPU. Apenas 1 job por vez. Queue nativa do asyncio é suficiente. |
| **asyncio.to_thread()** | O Marker é síncrono e bloqueante. `to_thread()` libera o event loop para processar HTTP. |
| **SQLAlchemy async + asyncpg** | Driver async nativo para PostgreSQL. Evita bloquear o event loop em operações de I/O com banco. |
| **SHA-256 para duplicatas** | Hash dos bytes do PDF (16 chars). Detectado no `POST /converter` antes de enfileirar. |
| **Alembic async** | Migrations versionadas. Executa `alembic upgrade head` automaticamente no startup do container. |
| **Warmup no startup** | Primeira inferência do Marker é lenta. Warmup com PDF de teste reduz latência do primeiro job real. |
| **Rede Docker externa** | Permite que outros serviços na mesma rede se conectem ao PDF Extraction Service. |
| **Imagem pytorch runtime** | Menor que `-devel`, sem necessidade de compilação CUDA. |
| **Limpeza de jobs a cada 5 min** | Previne vazamento de memória sem adicionar dependências externas. |
| **Fila cheia → HTTP 503** | Padrão REST para indicar que o serviço está temporariamente sobrecarregado. |
| **Sem autenticação** | Serviço interno em rede privada. |

---

## Fluxo de uma Requisição

```
Cliente                    FastAPI (api.py)             Worker (worker.py)           PostgreSQL
  │                             │                             │                          │
  │  POST /converter            │                             │                          │
  │  (multipart/form-data)      │                             │                          │
  ├────────────────────────────►│                             │                          │
  │                             │  hash(pdf_bytes)            │                          │
  │                             │  get_by_hash() ────────────────────────────────────────►│
  │                             │◄───────────────────────────────────────────────────────┤│
  │                             │                             │                          │
  │                             │  [duplicata] → 200 Document │                          │
  │                             │  [novo] → enqueue()         │                          │
  │  ◄── 202 {job_id, QUEUED} ─┤                             │                          │
  │                             │                             │                          │
  │                             │       asyncio.Queue         │                          │
  │                             │  ──────────────────────►    │                          │
  │                             │                             │  converter.convert()     │
  │                             │                             │  (asyncio.to_thread)     │
  │                             │                             │  Marker (GPU/CPU)        │
  │                             │                             │         │                │
  │                             │                             │  Document                │
  │                             │                             │  + processing_time_ms    │
  │                             │                             │  repository.save() ─────►│
  │                             │                             │  status = DONE           │
  │                             │                             │                          │
  │  GET /result/{job_id}       │                             │                          │
  ├────────────────────────────►│  job.status (in-memory)     │                          │
  │  ◄── 200 {status: DONE} ───┤                             │                          │
  │                             │                             │                          │
  │  GET /document/{job_id}     │                             │                          │
  ├────────────────────────────►│  get_by_job_id() ──────────────────────────────────────►│
  │  ◄── 200 {Document} ───────┤◄───────────────────────────────────────────────────────┤│
```

---

## Verificação / Testes Manuais

1. Criar rede Docker: `docker network create pdf-extraction-network`
2. `docker compose up --build` — PostgreSQL sobe, migrations rodam, modelos carregam, warmup executa
3. `curl -X POST http://localhost:8503/converter -F "file=@test.pdf"` → `{"job_id": "...", "status": "QUEUED"}`
4. `curl http://localhost:8503/result/{job_id}` → poll até `status: "DONE"`
5. `curl http://localhost:8503/document/{job_id}` → Document completo com markdown
6. Reenviar o mesmo PDF → `200` com Document já existente (duplicata detectada)
7. `curl http://localhost:8503/health` → `{"status": "ok"}`
8. Enviar 51 PDFs rapidamente → 51º retorna HTTP 503
