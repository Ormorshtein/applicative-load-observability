## Dashboard Cheat Sheet

**How to examine this dashboard:**

1. **Start with the overview** — pie charts show which application, target, operation, or template contributes the most stress.
2. **Check Highest Impact** — the Top 10 Templates and Heaviest Operations tables show exactly what to fix. Focus on templates with high sum stress and cost indicator counts.
3. **Look at trends** — stress over time charts reveal spikes and patterns. Correlate with deployments or traffic changes.
4. **Review volume & throughput** — request volume, total hits, docs affected, and request size panels show operational load. Total hits correlates with CPU.
5. **Examine response times** — high ES or gateway latency alongside high stress may indicate query optimization opportunities.
6. **Sanity checks** — verify if the most recurring templates are also the most stressful; templates with many cost indicators need attention.

**What to focus on:**
- **High stress slices** in pie charts — optimization targets
- **Upward trends** in time series — growing load or degrading patterns
- **Templates with many cost indicators** — query optimization candidates
- **Latency spikes** correlating with specific operations or templates
- **Total hits spikes** — correlate with CPU usage under queue saturation
