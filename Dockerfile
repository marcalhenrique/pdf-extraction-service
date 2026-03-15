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
