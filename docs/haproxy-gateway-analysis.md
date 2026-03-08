# Can OpenShift's Default HAProxy Replace the OpenResty Gateway?

**Short answer: No.**

This document analyzes whether the OpenShift built-in HAProxy ingress controller
can take over the role of the OpenResty gateway in the observability pipeline.

---

## What the Gateway Does

The OpenResty gateway (`gateway/nginx.conf.template`) is not just a reverse proxy.
It performs three critical functions:

1. **Proxies requests** to Elasticsearch and returns the response to the client
2. **Captures the full request and response bodies** during proxying
3. **Fires an async HTTP POST to Logstash** *after* the response is already sent,
   carrying: method, path, headers, request_body, response_body, response_status,
   gateway_took_ms, request/response sizes, and client_host

The analyzer depends on the **full response body** (to extract `took`, `hits.total.value`,
`_shards.total`, `docs_affected`) and the **full request body** (to parse query structure,
count clauses, build templates, evaluate cost indicators).

---

## Blocker 1: Response Body Capture Is Unreliable in HAProxy

OpenResty streams response chunks via `body_filter_by_lua_block` and accumulates them
reliably into `ngx.ctx.resp_body`. HAProxy Lua only has access to `tune.bufsize` bytes
(default 16 KB) of response data, and `res.body` returns `nil` in many contexts.

Elasticsearch responses regularly exceed 16 KB. This makes HAProxy fundamentally
unsuitable for capturing the data the analyzer needs.

**Sources:**
- [Response body is coming as nil using register_fetches and lua](https://discourse.haproxy.org/t/response-body-is-coming-as-nil-using-register-fetches-and-lua/9893)
- [Request & Response body logging — HAProxy community](https://discourse.haproxy.org/t/request-response-body-logging/4868)
- [How to read Request and Response using Lua Plugin](https://discourse.haproxy.org/t/how-to-read-request-and-response-using-lua-plugin/8484)
- [Modify Request Body / Response Body — GitHub issue #2564](https://github.com/haproxy/haproxy/issues/2564)

---

## Blocker 2: No Post-Response Async Phase

OpenResty's `log_by_lua_block` + `ngx.timer.at(0, ...)` fires the Logstash notification
**after** the response is sent to the client — zero added latency.

HAProxy Lua actions run **during** request processing (`http-request`, `http-response`,
or `tcp-request` phases). Making an HTTP call to Logstash from HAProxy Lua would
**block the client response**, violating the pipeline's core design principle:
*"failures in the observability pipeline never propagate upstream"* (ARCHITECTURE.md §5).

> HAProxy *does* have `core.httpclient()` for outbound HTTP — the capability exists,
> but there is no equivalent of "run this after the response is sent."

**Sources:**
- [HAProxy Lua API — Introduction](https://www.haproxy.com/documentation/haproxy-lua-api/getting-started/introduction/)
- [How Lua runs in HAProxy](https://www.arpalert.org/src/haproxy-lua-api/2.8/index.html)
- [5 Ways to Extend HAProxy with Lua](https://www.haproxy.com/blog/5-ways-to-extend-haproxy-with-lua)

---

## Blocker 3: OpenShift 4 Doesn't Support Custom HAProxy Templates

Even if HAProxy could do everything above, the OpenShift 4 Ingress Operator
**does not allow** custom HAProxy template modifications. Customizations available
in OpenShift 3.x are explicitly missing in OpenShift 4. The operator manages the
router lifecycle, and direct template changes are not a supported configuration.

Customization is limited to a few knobs: `maxConnections`, custom error pages.

**Sources:**
- [HAProxy router customizations are missing in OpenShift 4 — Red Hat Portal](https://access.redhat.com/solutions/5477331)
- [OpenShift 4.10 Ingress Operator docs](https://docs.openshift.com/container-platform/4.10/networking/ingress-operator.html)

---

## Blocker 4: Shared Infrastructure Risk

The OpenShift HAProxy router is a **cluster-wide shared resource** serving hundreds of
deployments. Injecting application-specific observability logic into it would:

- Require cluster-admin privileges
- Affect all other traffic flowing through the router
- Be overwritten by OpenShift upgrades
- Risk taking down ingress for the entire cluster if a bug occurs

---

## Best Practice: Dedicated Gateway Pod

The standard Kubernetes/OpenShift pattern is:

```
Client → OpenShift HAProxy (routing + TLS only)
              ↓
         OpenResty Pod (dedicated deployment in your namespace)
              ↓
         Elasticsearch
```

- HAProxy does what it's good at: TLS termination, route-based traffic splitting
- OpenResty does what only it can do: body capture, async notification, fire-and-forget
- Your observability logic lives in your namespace, isolated from cluster infrastructure

This is the same pattern used by service meshes (Envoy sidecars), API gateways
(Kong — also OpenResty-based), and observability proxies industry-wide.

---

## Summary

| Requirement | OpenResty | HAProxy (standalone) | OpenShift HAProxy |
|---|---|---|---|
| Full response body capture | Yes (`body_filter_by_lua_block`) | Unreliable (16 KB buffer, nil) | No (can't customize) |
| Full request body capture | Yes (`ngx.req.get_body_data()`) | Partial (`tune.bufsize` limit) | No (can't customize) |
| Async POST after response | Yes (`ngx.timer.at`) | No (blocks client) | No (can't customize) |
| Zero client latency impact | Yes | No | No |
| Per-app isolation | Yes (own pod) | Yes (own pod) | No (shared cluster resource) |
| Survives platform upgrades | Yes | Yes | No (operator-managed) |
