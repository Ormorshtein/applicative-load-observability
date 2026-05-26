FROM python:3.12-slim
WORKDIR /app
COPY __init__.py setup.py _dashboards.py _dashboard_builders.py _datasource.py cheat_sheet.md /app/grafana/
COPY provisioning/ /app/grafana/provisioning/
CMD ["python", "-m", "grafana.setup"]
