"""Grafana datasource provisioning helpers."""

import os
import textwrap

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DS_DIR = os.path.join(SCRIPT_DIR, "provisioning", "datasources")
DS_PATH = os.path.join(DS_DIR, "elasticsearch.yml")


def generate_datasource_yaml(elasticsearch_url="http://elasticsearch:9200",
                             index_pattern="logs-alo.*-*"):
    content = textwrap.dedent(f"""\
        apiVersion: 1

        datasources:
          - name: Elasticsearch (ALO)
            type: elasticsearch
            uid: alo-elasticsearch
            access: proxy
            url: {elasticsearch_url}
            database: "{index_pattern}"
            isDefault: true
            jsonData:
              esVersion: "8.0.0"
              timeField: "@timestamp"
              logMessageField: ""
              logLevelField: ""
              maxConcurrentShardRequests: 5
              interval: ""
            editable: true
    """)
    os.makedirs(DS_DIR, exist_ok=True)
    with open(DS_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Generated: {DS_PATH}")
    return DS_PATH
