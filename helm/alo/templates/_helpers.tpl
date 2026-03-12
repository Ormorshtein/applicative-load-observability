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
Elasticsearch URL — either external or internal service.
Used by logstash, kibana, and setup (ALO storage).
*/}}
{{- define "alo.elasticsearchUrl" -}}
{{- if .Values.elasticsearch.external.enabled }}
{{- required "elasticsearch.external.url is required when elasticsearch.external.enabled=true" .Values.elasticsearch.external.url }}
{{- else }}
{{- printf "http://%s-elasticsearch:%d" (include "alo.fullname" .) (.Values.elasticsearch.service.port | int) }}
{{- end }}
{{- end }}

{{/*
Gateway Elasticsearch URL — the cluster being monitored/proxied.
Falls back to the main elasticsearch config when gateway.elasticsearch.url is empty.
*/}}
{{- define "alo.gatewayElasticsearchUrl" -}}
{{- if .Values.gateway.elasticsearch.url }}
{{- .Values.gateway.elasticsearch.url }}
{{- else }}
{{- include "alo.elasticsearchUrl" . }}
{{- end }}
{{- end }}

{{/*
Whether gateway-specific ES config is active (has its own URL).
*/}}
{{- define "alo.gatewayEsOverride" -}}
{{- if .Values.gateway.elasticsearch.url }}true
{{- else }}false
{{- end }}
{{- end }}

{{/*
Whether gateway ES auth is active.
*/}}
{{- define "alo.gatewayEsAuthEnabled" -}}
{{- if eq (include "alo.gatewayEsOverride" .) "true" }}
{{- if .Values.gateway.elasticsearch.auth.enabled }}true{{- else }}false{{- end }}
{{- else }}
{{- include "alo.esAuthEnabled" . }}
{{- end }}
{{- end }}

{{/*
Name of the Secret holding gateway ES auth credentials.
*/}}
{{- define "alo.gatewayEsAuthSecretName" -}}
{{- if eq (include "alo.gatewayEsOverride" .) "true" }}
{{- if .Values.gateway.elasticsearch.auth.existingSecret }}
{{- .Values.gateway.elasticsearch.auth.existingSecret }}
{{- else }}
{{- printf "%s-gateway-es-auth" (include "alo.fullname" .) }}
{{- end }}
{{- else }}
{{- include "alo.esAuthSecretName" . }}
{{- end }}
{{- end }}

{{/*
Gateway ES auth type.
*/}}
{{- define "alo.gatewayEsAuthType" -}}
{{- if eq (include "alo.gatewayEsOverride" .) "true" }}
{{- .Values.gateway.elasticsearch.auth.type }}
{{- else if .Values.elasticsearch.external.enabled }}
{{- .Values.elasticsearch.external.auth.type }}
{{- else }}
{{- "basic" }}
{{- end }}
{{- end }}

{{/*
Whether a gateway ES CA secret should be mounted.
*/}}
{{- define "alo.gatewayEsCaEnabled" -}}
{{- if eq (include "alo.gatewayEsOverride" .) "true" }}
{{- if or .Values.gateway.elasticsearch.tls.create .Values.gateway.elasticsearch.tls.caCertSecret }}true
{{- else }}false
{{- end }}
{{- else }}
{{- include "alo.esCaEnabled" . }}
{{- end }}
{{- end }}

{{/*
Name of the Secret holding the gateway ES CA certificate.
*/}}
{{- define "alo.gatewayEsCaSecretName" -}}
{{- if eq (include "alo.gatewayEsOverride" .) "true" }}
{{- if .Values.gateway.elasticsearch.tls.caCertSecret }}
{{- .Values.gateway.elasticsearch.tls.caCertSecret }}
{{- else }}
{{- printf "%s-gateway-es-ca" (include "alo.fullname" .) }}
{{- end }}
{{- else }}
{{- include "alo.esCaSecretName" . }}
{{- end }}
{{- end }}

{{/*
NiFi listen URL — either external or internal service.
*/}}
{{- define "alo.nifiListenUrl" -}}
{{- if .Values.nifi.external.enabled }}
{{- required "nifi.external.listenUrl is required when nifi.external.enabled=true" .Values.nifi.external.listenUrl }}
{{- else }}
{{- printf "http://%s-nifi.%s.svc.cluster.local:%d/%s" (include "alo.fullname" .) .Release.Namespace (.Values.nifi.service.listenPort | int) .Values.nifi.listenBasePath }}
{{- end }}
{{- end }}

{{/*
Kibana URL for dashboard setup job.
*/}}
{{- define "alo.kibanaUrl" -}}
{{- if .Values.kibana.external.enabled }}
{{- required "kibana.external.url is required when kibana.external.enabled=true" .Values.kibana.external.url }}
{{- else }}
{{- printf "http://%s-kibana:%d" (include "alo.fullname" .) (.Values.kibana.service.port | int) }}
{{- end }}
{{- end }}

{{/*
Logstash URL — either external or internal service.
*/}}
{{- define "alo.logstashUrl" -}}
{{- if .Values.logstash.external.enabled }}
{{- required "logstash.external.url is required when logstash.external.enabled=true" .Values.logstash.external.url }}
{{- else }}
{{- printf "http://%s-logstash.%s.svc.cluster.local:%d/" (include "alo.fullname" .) .Release.Namespace (.Values.logstash.service.httpPort | int) }}
{{- end }}
{{- end }}

{{/*
Logstash monitoring URL — internal service monitoring port.
*/}}
{{- define "alo.logstashMonitoringUrl" -}}
{{- printf "http://%s-logstash:%d" (include "alo.fullname" .) (.Values.logstash.service.monitoringPort | int) }}
{{- end }}

{{/*
Pipeline URL — resolves to Logstash or NiFi URL based on pipelineMode.
*/}}
{{- define "alo.pipelineUrl" -}}
{{- if eq .Values.pipelineMode "logstash" }}
{{- include "alo.logstashUrl" . }}
{{- else }}
{{- include "alo.nifiListenUrl" . }}
{{- end }}
{{- end }}

{{/*
Image pull secrets.
*/}}
{{- define "alo.imagePullSecrets" -}}
{{- range .Values.imagePullSecrets }}
- name: {{ . }}
{{- end }}
{{- end }}

{{/*
ServiceAccount name.
*/}}
{{- define "alo.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "alo.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Name of the Secret holding ES credentials used by the gateway and Kibana.
Returns the user-supplied existingSecret or the chart-managed secret name.
*/}}
{{- define "alo.esAuthSecretName" -}}
{{- if .Values.elasticsearch.external.enabled }}
  {{- if .Values.elasticsearch.external.auth.existingSecret }}
    {{- .Values.elasticsearch.external.auth.existingSecret }}
  {{- else }}
    {{- printf "%s-es-auth" (include "alo.fullname" .) }}
  {{- end }}
{{- else }}
  {{- if .Values.elasticsearch.security.existingSecret }}
    {{- .Values.elasticsearch.security.existingSecret }}
  {{- else }}
    {{- printf "%s-es-auth" (include "alo.fullname" .) }}
  {{- end }}
{{- end }}
{{- end }}

{{/*
Whether ES auth is active (external auth OR internal security).
*/}}
{{- define "alo.esAuthEnabled" -}}
{{- if and .Values.elasticsearch.external.enabled .Values.elasticsearch.external.auth.enabled }}true
{{- else if and (not .Values.elasticsearch.external.enabled) .Values.elasticsearch.security.enabled }}true
{{- else }}false
{{- end }}
{{- end }}

{{/*
Name of the Secret holding NiFi auth credentials for external NiFi.
*/}}
{{- define "alo.nifiAuthSecretName" -}}
{{- if .Values.nifi.external.auth.existingSecret }}
{{- .Values.nifi.external.auth.existingSecret }}
{{- else }}
{{- printf "%s-nifi-ext-auth" (include "alo.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Name of the Secret holding NiFi UI credentials (internal).
*/}}
{{- define "alo.nifiSecretName" -}}
{{- if .Values.nifi.auth.existingSecret }}
{{- .Values.nifi.auth.existingSecret }}
{{- else }}
{{- printf "%s-nifi" (include "alo.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Name of the Secret holding the ES CA certificate.
*/}}
{{- define "alo.esCaSecretName" -}}
{{- if .Values.elasticsearch.external.tls.caCertSecret }}
{{- .Values.elasticsearch.external.tls.caCertSecret }}
{{- else }}
{{- printf "%s-es-ca" (include "alo.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Whether an ES CA secret should be mounted.
*/}}
{{- define "alo.esCaEnabled" -}}
{{- if or .Values.elasticsearch.external.tls.create .Values.elasticsearch.external.tls.caCertSecret }}true
{{- else }}false
{{- end }}
{{- end }}

{{/*
Whether storage ES TLS verification should be skipped.
*/}}
{{- define "alo.esInsecure" -}}
{{- if and .Values.elasticsearch.external.enabled .Values.elasticsearch.external.tls.insecureSkipVerify }}true
{{- else }}false
{{- end }}
{{- end }}

{{/*
Whether storage ES URL is HTTPS (SSL must be enabled in clients).
*/}}
{{- define "alo.esSslEnabled" -}}
{{- if or (eq (include "alo.esCaEnabled" .) "true") (eq (include "alo.esInsecure" .) "true") (hasPrefix "https://" (include "alo.elasticsearchUrl" .)) }}true
{{- else }}false
{{- end }}
{{- end }}

{{/*
Pod scheduling helpers — renders nodeSelector, tolerations, affinity.
Usage: {{ include "alo.scheduling" .Values.gateway }}
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
