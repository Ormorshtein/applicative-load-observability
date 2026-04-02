#!/bin/sh
set -e

: "${DNS_RESOLVER:=$(awk '/^nameserver/{print $2; exit}' /etc/resolv.conf 2>/dev/null || echo 127.0.0.11)}"
: "${ELASTICSEARCH_HOST:=elasticsearch:9200}"
: "${LOGSTASH_URL:=http://logstash:8080/}"
: "${GATEWAY_PORT:=9200}"
: "${WORKER_CONNECTIONS:=1024}"
: "${LOGSTASH_TIMEOUT_MS:=1000}"
: "${CLUSTER_NAME:=default}"

export DNS_RESOLVER ELASTICSEARCH_HOST LOGSTASH_URL GATEWAY_PORT WORKER_CONNECTIONS LOGSTASH_TIMEOUT_MS CLUSTER_NAME

envsubst '${DNS_RESOLVER} ${ELASTICSEARCH_HOST} ${LOGSTASH_URL} ${GATEWAY_PORT} ${WORKER_CONNECTIONS} ${LOGSTASH_TIMEOUT_MS} ${CLUSTER_NAME}' \
  < /etc/nginx/nginx.conf.template \
  > /usr/local/openresty/nginx/conf/nginx.conf

mkdir -p /tmp/nginx

exec /usr/local/openresty/bin/openresty -g 'daemon off;'
