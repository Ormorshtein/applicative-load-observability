FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml .
RUN uv pip install --system --no-cache -r pyproject.toml
COPY analyzer/ .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
