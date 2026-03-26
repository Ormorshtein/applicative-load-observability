FROM openresty/openresty:1.29.2.2-alpine
RUN apk add --no-cache curl gettext perl \
    && mkdir -p /usr/local/openresty/site/lualib/resty \
    && curl -fsSL https://raw.githubusercontent.com/ledgetech/lua-resty-http/v0.17.2/lib/resty/http.lua \
         -o /usr/local/openresty/site/lualib/resty/http.lua \
    && curl -fsSL https://raw.githubusercontent.com/ledgetech/lua-resty-http/v0.17.2/lib/resty/http_headers.lua \
         -o /usr/local/openresty/site/lualib/resty/http_headers.lua \
    && curl -fsSL https://raw.githubusercontent.com/ledgetech/lua-resty-http/v0.17.2/lib/resty/http_connect.lua \
         -o /usr/local/openresty/site/lualib/resty/http_connect.lua \
    && /usr/local/openresty/bin/opm get fffonion/lua-resty-openssl \
    && apk del curl perl
COPY nginx.conf.template /etc/nginx/nginx.conf.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
