FROM python:3.12-slim
WORKDIR /app
COPY clickhouse_setup/__init__.py clickhouse_setup/setup.py clickhouse_setup/_client.py clickhouse_setup/_schema.py /app/clickhouse_setup/
ENTRYPOINT ["python", "-m", "clickhouse_setup.setup"]
