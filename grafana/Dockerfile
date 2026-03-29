FROM python:3.12-slim
WORKDIR /app
COPY setup.py _dashboards.py _dashboard_builders.py _datasource.py cheat_sheet.md ./
COPY provisioning/ ./provisioning/
CMD ["python", "/app/setup.py"]
