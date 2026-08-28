## Dashboard Cheat Sheet

**How to examine this dashboard:**

1. **Start with the overview** — pie charts show which application, target, operation, or template contributes the most stress.
2. **Review the Top 10 Templates table** — focus on templates with the highest sum stress and cost indicator counts.
3. **Look at trends** — stress over time charts reveal spikes and patterns. Correlate with deployments or traffic changes.
4. **Review volume & throughput** — request volume, total hits, docs affected, and request size panels show operational load. Total hits correlates with CPU.
5. **Examine response times** — high ES or gateway latency alongside high stress may indicate query optimization opportunities.
6. **Sanity checks** — verify if the most recurring templates are also the most stressful; templates with many cost indicators need attention.

**What to focus on:**
- **High stress slices** in pie charts — click to filter the dashboard
- **Upward trends** in time series — growing load or degrading patterns
- **Templates with many cost indicators** — query optimization candidates
- **Latency spikes** correlating with specific operations or templates

**Filtering:**
Use the variable dropdowns at the top (Cluster, Application, Target, Operation, Username, Cost Indicator, Client Host, Template), or the ad-hoc **Filters** bar for any other `alo_raw` column — e.g. `request_target = products`.

**Custom labels (`x-alo-*` headers):**
Labels are stored in the `identity_labels` Map column, not as separate columns, so they are not in the variable dropdowns. Query them with a map subscript in Explore or a panel query:

```sql
SELECT request_template, count(), avg(stress_score)
FROM alo.alo_raw
WHERE identity_labels['team'] = 'payments'
  AND $__timeFilter(timestamp)
GROUP BY request_template
ORDER BY 3 DESC;
```
