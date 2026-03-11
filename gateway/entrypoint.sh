#!/bin/sh
set -e

: "${DNS_RESOLVER:=$(awk '/^nameserver/{print $2; exit}' /etc/resolv.conf 2>/dev/null || echo 127.0.0.11)}"
: "${ELASTICSEARCH_HOST:=elasticsearch:9200}"
: "${LOGSTASH_URL:=http://logstash:8080/}"
: "${GATEWAY_PORT:=9200}"

export DNS_RESOLVER ELASTICSEARCH_HOST LOGSTASH_URL GATEWAY_PORT

envsubst '${DNS_RESOLVER} ${ELASTICSEARCH_HOST} ${LOGSTASH_URL} ${GATEWAY_PORT}' \
  < /etc/nginx/nginx.conf.template \
  > /usr/local/openresty/nginx/conf/nginx.conf

exec /usr/local/openresty/bin/openresty -g 'daemon off;'
