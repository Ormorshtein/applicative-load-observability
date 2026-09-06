FROM docker.elastic.co/logstash/logstash:8.13.0
RUN logstash-plugin install --version 1.4.3 logstash-filter-http \
 && logstash-plugin install --version 0.1.5 logstash-output-clickhouse
