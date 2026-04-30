FROM python:3.12-slim
WORKDIR /app
COPY setup.py _dashboards.py _dashboard_builders.py _datasource.py _strings.py \
     cheat_sheet.md cheat_sheet_he.md ./
COPY provisioning/ ./provisioning/
CMD ["python", "/app/setup.py"]
