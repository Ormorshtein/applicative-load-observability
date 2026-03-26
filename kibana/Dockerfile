FROM python:3.12-slim
WORKDIR /app
COPY setup.py _client.py _dashboard_builders.py _dashboards.py _index_template.py \
     _visualizations.py _viz_builders.py cheat_sheet.md ./
COPY dashboard*.ndjson ./
CMD ["python", "/app/setup.py"]
