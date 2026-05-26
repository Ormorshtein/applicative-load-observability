{{/*
Chart name truncated to 63 chars.
*/}}
{{- define "alo.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified app name.
*/}}
{{- define "alo.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "alo.labels" -}}
helm.sh/chart: {{ include "alo.name" . }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: alo
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}

{{/*
Selector labels for a component.
Usage: {{ include "alo.selectorLabels" (dict "ctx" . "component" "gateway") }}
*/}}
{{- define "alo.selectorLabels" -}}
app.kubernetes.io/name: {{ include "alo.name" .ctx }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
=============================================================================
ClickHouse (analytics sink) — used by logstash, analyzer, grafana, ch-setup
=============================================================================
*/}}

{{- define "alo.clickhouseUrl" -}}
{{- if .Values.clickhouse.external.enabled }}
{{- required "clickhouse.external.url is required when clickhouse.external.enabled=true" .Values.clickhouse.external.url }}
{{- else }}
{{- printf "http://%s-clickhouse:%d" (include "alo.fullname" .) (.Values.clickhouse.service.httpPort | int) }}
{{- end }}
{{- end }}

{{/*
Host used by the Grafana ClickHouse datasource (native protocol).
*/}}
{{- define "alo.clickhouseNativeHost" -}}
{{- if .Values.clickhouse.external.enabled }}
{{- .Values.clickhouse.external.host | default "" }}
{{- else }}
{{- printf "%s-clickhouse" (include "alo.fullname" .) }}
{{- end }}
{{- end }}

{{- define "alo.clickhouseAuthSecretName" -}}
{{- if .Values.clickhouse.external.auth.existingSecret }}
{{- .Values.clickhouse.external.auth.existingSecret }}
{{- else }}
{{- printf "%s-ch-auth" (include "alo.fullname" .) }}
{{- end }}
{{- end }}

{{- define "alo.clickhouseAuthEnabled" -}}
{{- if and .Values.clickhouse.external.enabled .Values.clickhouse.external.auth.enabled }}true
{{- else if and (not .Values.clickhouse.external.enabled) .Values.clickhouse.auth.enabled }}true
{{- else }}false
{{- end }}
{{- end }}

{{- define "alo.clickhouseCaSecretName" -}}
{{- if .Values.clickhouse.external.tls.caCertSecret }}
{{- .Values.clickhouse.external.tls.caCertSecret }}
{{- else }}
{{- printf "%s-ch-ca" (include "alo.fullname" .) }}
{{- end }}
{{- end }}

{{- define "alo.clickhouseCaEnabled" -}}
{{- if and .Values.clickhouse.external.enabled (or .Values.clickhouse.external.tls.create .Values.clickhouse.external.tls.caCertSecret) }}true
{{- else }}false
{{- end }}
{{- end }}

{{- define "alo.clickhouseInsecure" -}}
{{- if and .Values.clickhouse.external.enabled .Values.clickhouse.external.tls.insecureSkipVerify }}true
{{- else }}false
{{- end }}
{{- end }}

{{- define "alo.clickhouseClusterName" -}}
{{- if .Values.clickhouse.cluster.enabled }}
{{- .Values.clickhouse.cluster.name | default "alo_cluster" }}
{{- end }}
{{- end }}

{{/*
=============================================================================
Gateway upstream Elasticsearch — the *customer's* ES being proxied.
Required when the gateway is enabled.
=============================================================================
*/}}

{{- define "alo.gatewayElasticsearchUrl" -}}
{{- required "gateway.elasticsearch.url is required (the upstream Elasticsearch the gateway proxies)" .Values.gateway.elasticsearch.url }}
{{- end }}

{{- define "alo.gatewayEsAuthEnabled" -}}
{{- if .Values.gateway.elasticsearch.auth.injectAuth }}true
{{- else }}false
{{- end }}
{{- end }}

{{- define "alo.gatewayEsAuthSecretName" -}}
{{- if .Values.gateway.elasticsearch.auth.existingSecret }}
{{- .Values.gateway.elasticsearch.auth.existingSecret }}
{{- else }}
{{- printf "%s-gateway-es-auth" (include "alo.fullname" .) }}
{{- end }}
{{- end }}

{{- define "alo.gatewayEsAuthType" -}}
{{- .Values.gateway.elasticsearch.auth.type }}
{{- end }}

{{- define "alo.gatewayEsCaEnabled" -}}
{{- if or .Values.gateway.elasticsearch.tls.create .Values.gateway.elasticsearch.tls.caCertSecret }}true
{{- else }}false
{{- end }}
{{- end }}

{{- define "alo.gatewayEsCaSecretName" -}}
{{- if .Values.gateway.elasticsearch.tls.caCertSecret }}
{{- .Values.gateway.elasticsearch.tls.caCertSecret }}
{{- else }}
{{- printf "%s-gateway-es-ca" (include "alo.fullname" .) }}
{{- end }}
{{- end }}

{{/*
=============================================================================
NiFi / Grafana / Logstash URL helpers (unchanged from the ES era).
=============================================================================
*/}}

{{- define "alo.grafanaUrl" -}}
{{- if .Values.grafana.external.enabled }}
{{- required "grafana.external.url is required when grafana.external.enabled=true" .Values.grafana.external.url }}
{{- else }}
{{- printf "http://%s-grafana:%d" (include "alo.fullname" .) (.Values.grafana.service.port | int) }}
{{- end }}
{{- end }}

{{- define "alo.logstashUrl" -}}
{{- if .Values.logstash.external.enabled }}
{{- required "logstash.external.url is required when logstash.external.enabled=true" .Values.logstash.external.url }}
{{- else }}
{{- printf "http://%s-logstash.%s.svc.cluster.local:%d/" (include "alo.fullname" .) .Release.Namespace (.Values.logstash.service.httpPort | int) }}
{{- end }}
{{- end }}

{{- define "alo.logstashMonitoringUrl" -}}
{{- printf "http://%s-logstash:%d" (include "alo.fullname" .) (.Values.logstash.service.monitoringPort | int) }}
{{- end }}

{{- define "alo.imagePullSecrets" -}}
{{- range .Values.imagePullSecrets }}
- name: {{ . }}
{{- end }}
{{- end }}

{{- define "alo.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "alo.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
=============================================================================
Pod scheduling + Route TLS/annotations helpers.
=============================================================================
*/}}

{{- define "alo.scheduling" -}}
{{- with .nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .affinity }}
affinity:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}

{{- define "alo.routeTls" -}}
{{- $g := .global -}}
{{- $l := .local -}}
{{- $enabled := ternary $l.enabled $g.enabled (hasKey $l "enabled") -}}
{{- if $enabled }}
tls:
  termination: {{ $l.termination | default $g.termination }}
  {{- $iep := $l.insecureEdgeTerminationPolicy | default $g.insecureEdgeTerminationPolicy }}
  {{- if $iep }}
  insecureEdgeTerminationPolicy: {{ $iep }}
  {{- end }}
  {{- $cert := $l.certificate | default $g.certificate }}
  {{- if $cert }}
  certificate: |
    {{- $cert | nindent 4 }}
  {{- end }}
  {{- $key := $l.key | default $g.key }}
  {{- if $key }}
  key: |
    {{- $key | nindent 4 }}
  {{- end }}
  {{- $ca := $l.caCertificate | default $g.caCertificate }}
  {{- if $ca }}
  caCertificate: |
    {{- $ca | nindent 4 }}
  {{- end }}
  {{- $destCa := $l.destinationCACertificate | default $g.destinationCACertificate }}
  {{- if $destCa }}
  destinationCACertificate: |
    {{- $destCa | nindent 4 }}
  {{- end }}
{{- end }}
{{- end }}

{{- define "alo.routeAnnotations" -}}
{{- $merged := merge (.local | default dict) (.global | default dict) -}}
{{- if $merged }}
annotations:
  {{- toYaml $merged | nindent 2 }}
{{- end }}
{{- end }}
