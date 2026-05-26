FROM python:3.12-slim
WORKDIR /app
COPY __init__.py setup.py _client.py _schema.py /app/clickhouse_setup/
CMD ["python", "-m", "clickhouse_setup.setup"]
