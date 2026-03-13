FROM openresty/openresty:alpine
RUN apk add --no-cache curl gettext \
    && mkdir -p /usr/local/openresty/site/lualib/resty \
    && curl -fsSL https://raw.githubusercontent.com/ledgetech/lua-resty-http/v0.16.1/lib/resty/http.lua \
         -o /usr/local/openresty/site/lualib/resty/http.lua \
    && curl -fsSL https://raw.githubusercontent.com/ledgetech/lua-resty-http/v0.16.1/lib/resty/http_headers.lua \
         -o /usr/local/openresty/site/lualib/resty/http_headers.lua \
    && apk del curl
COPY nginx.conf.template /etc/nginx/nginx.conf.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
