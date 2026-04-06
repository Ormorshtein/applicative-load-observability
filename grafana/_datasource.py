"""Grafana datasource provisioning helpers."""

import os
import textwrap

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DS_DIR = os.path.join(SCRIPT_DIR, "provisioning", "datasources")
DS_PATH = os.path.join(DS_DIR, "elasticsearch.yml")


def generate_datasource_yaml(elasticsearch_url="http://elasticsearch:9200",
                             index_pattern="logs-alo.*-*,alo-summary"):
    content = textwrap.dedent(f"""\
        apiVersion: 1

        # Primary datasource queries raw + summary. While raw data exists it
        # outnumbers summary docs ~50:1 (<2% noise). After ILM deletes raw,
        # summary seamlessly provides avg metrics and percentiles at hourly
        # granularity.
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

          - name: Elasticsearch (ALO Summary)
            type: elasticsearch
            uid: alo-elasticsearch-summary
            access: proxy
            url: {elasticsearch_url}
            database: "alo-summary"
            isDefault: false
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
