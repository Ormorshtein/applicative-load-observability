FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml .
RUN uv pip install --system --no-cache -r pyproject.toml
COPY analyzer/ ./analyzer/
EXPOSE 8000
CMD ["uvicorn", "analyzer.main:app", "--host", "0.0.0.0", "--port", "8000"]
