# PDF Extraction Service — API Contract

**Base URL:** `http://{host}:{port}` (default: `http://localhost:8503`)

---

## POST /converter

Envia um arquivo PDF para extração assíncrona. Se o PDF já foi processado anteriormente (mesmo conteúdo), retorna o documento existente.

**Request:**

- Content-Type: `multipart/form-data`
- Body:

| Campo  | Tipo         | Obrigatório | Descrição                    |
|--------|--------------|-------------|------------------------------|
| `file` | `UploadFile` | Sim         | Arquivo PDF a ser processado |

**Responses:**

### 202 Accepted — Job enfileirado

```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "QUEUED"
}
```

### 200 OK — Duplicata detectada

PDF já foi processado anteriormente (mesmo SHA-256). Retorna o Document completo.

```json
{
  "job_id": "f6e5d4c3b2a1",
  "content_hash": "3f2a1b9c7e4d0a82",
  "title": "Título extraído do PDF",
  "content": "# Título\n\nConteúdo em markdown...",
  "source": "documento.pdf",
  "language": null,
  "metadata": {
    "source_size_bytes": 102400,
    "pdf_metadata": {}
  },
  "processing_time_ms": 12345,
  "processed_at": "2026-03-14T18:30:00.000000"
}
```

### 400 Bad Request

```json
{
  "detail": "Uploaded file is empty."
}
```

### 503 Service Unavailable

```json
{
  "detail": "Job queue is full. Please try again later."
}
```

---

## GET /result/{job_id}

Consulta o status de um job. Usar para polling até `DONE` ou `ERROR`.

**Path Parameters:**

| Parâmetro | Tipo  | Descrição              |
|-----------|-------|------------------------|
| `job_id`  | `str` | ID retornado pelo POST |

**Responses:**

### 200 OK

```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "QUEUED | PROCESSING | DONE | ERROR",
  "error": null
}
```

Quando `status = "ERROR"`, o campo `error` contém a mensagem de erro.

### 404 Not Found

Job não encontrado (ID inválido ou expirado pelo TTL).

```json
{
  "detail": "Job not found."
}
```

---

## GET /document/{job_id}

Busca o documento convertido no PostgreSQL. Disponível após `status = "DONE"`.

**Path Parameters:**

| Parâmetro | Tipo  | Descrição              |
|-----------|-------|------------------------|
| `job_id`  | `str` | ID retornado pelo POST |

**Responses:**

### 200 OK

```json
{
  "job_id": "a1b2c3d4e5f6",
  "content_hash": "3f2a1b9c7e4d0a82",
  "title": "Título extraído do PDF",
  "content": "# Título\n\nConteúdo completo em Markdown...",
  "source": "documento.pdf",
  "language": null,
  "metadata": {
    "source_size_bytes": 102400,
    "pdf_metadata": {}
  },
  "processing_time_ms": 12345,
  "processed_at": "2026-03-14T18:30:00.000000"
}
```

### 404 Not Found

Documento não encontrado (job ainda processando ou ID inválido).

```json
{
  "detail": "Document not found."
}
```

---

## GET /health

Health check do serviço.

**Response:**

### 200 OK

```json
{
  "status": "ok"
}
```

---

## Schemas

### JobStatus (enum)

| Valor        | Descrição                     |
|--------------|-------------------------------|
| `QUEUED`     | Job na fila aguardando        |
| `PROCESSING` | Job sendo processado          |
| `DONE`       | Processamento concluído       |
| `ERROR`      | Erro durante o processamento  |

### JobResponse

| Campo    | Tipo            | Descrição                          |
|----------|-----------------|------------------------------------|
| `job_id` | `str`           | ID único do job (12 chars hex)     |
| `status` | `JobStatus`     | Status atual do job                |
| `error`  | `str \| null`   | Mensagem de erro (quando `ERROR`)  |

### Document

| Campo              | Tipo          | Descrição                                    |
|--------------------|---------------|----------------------------------------------|
| `job_id`           | `str`         | ID do job que gerou o documento              |
| `content_hash`     | `str`         | SHA-256 (16 chars) dos bytes do PDF          |
| `title`            | `str`         | Primeiro `# heading` do markdown ou filename |
| `content`          | `str`         | Conteúdo completo em Markdown                |
| `source`           | `str`         | Nome do arquivo original                     |
| `language`         | `str \| null` | Idioma detectado (futuro)                    |
| `metadata`         | `dict`        | `source_size_bytes` + metadados do Marker    |
| `processing_time_ms` | `int \| null` | Tempo de processamento em milissegundos   |
| `processed_at`     | `datetime`    | Timestamp de conclusão do processamento      |

---

## Fluxo de Uso

```
1. POST /converter        →  202 { job_id, status: "QUEUED" }
                              ou 200 { document }  (se duplicata)
2. GET /result/{job_id}   →  polling até status = "DONE" ou "ERROR"
3. GET /document/{job_id} →  busca o Document completo do banco
```

### Detecção de Duplicatas

Ao receber um PDF, o serviço calcula o SHA-256 dos bytes e verifica se já existe um documento com o mesmo hash no banco. Se sim, retorna o documento existente com status 200, sem enfileirar um novo job.
