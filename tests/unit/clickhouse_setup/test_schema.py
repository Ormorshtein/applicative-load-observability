"""Unit tests for clickhouse_setup/_schema.py — DDL builder."""

from clickhouse_setup._schema import TableSettings, all_ddl


class TestSingleNodeMode:
    def setup_method(self):
        self.plan = all_ddl(TableSettings())
        self.by_label = dict(self.plan)

    def test_plan_skips_distributed_pairs(self):
        labels = [label for label, _ in self.plan]
        assert "alo_raw" not in labels
        assert "alo_dead_letter" not in labels
        assert "alo_summary" not in labels
        # Core DDL labels (alter_alo_raw_* labels follow at the end)
        assert labels[:5] == [
            "database",
            "alo_raw_local",
            "alo_dead_letter_local",
            "alo_summary_local",
            "alo_summary_mv",
        ]
        assert all(l.startswith("alter_alo_raw_") for l in labels[5:])

    def test_raw_uses_plain_mergetree(self):
        ddl = self.by_label["alo_raw_local"]
        assert "ENGINE = MergeTree" in ddl
        assert "ReplicatedMergeTree" not in ddl
        assert "ON CLUSTER" not in ddl

    def test_raw_creates_unsuffixed_table(self):
        assert "CREATE TABLE IF NOT EXISTS alo.alo_raw\n" in self.by_label["alo_raw_local"]

    def test_summary_uses_aggregatingmergetree(self):
        ddl = self.by_label["alo_summary_local"]
        assert "ENGINE = AggregatingMergeTree" in ddl
        assert "Replicated" not in ddl

    def test_mv_reads_unsuffixed_raw(self):
        ddl = self.by_label["alo_summary_mv"]
        assert "FROM alo.alo_raw" in ddl
        assert "FROM alo.alo_raw_local" not in ddl
        assert "TO alo.alo_summary" in ddl
        assert "TO alo.alo_summary_local" not in ddl

    def test_raw_has_ttl_3_days(self):
        ddl = self.by_label["alo_raw_local"]
        assert "INTERVAL 3 DAY DELETE" in ddl

    def test_summary_has_ttl_120_days(self):
        ddl = self.by_label["alo_summary_local"]
        assert "INTERVAL 120 DAY DELETE" in ddl

    def test_raw_orders_by_hot_filters_then_timestamp(self):
        ddl = self.by_label["alo_raw_local"]
        assert (
            "ORDER BY (cluster_name, request_operation, "
            "identity_applicative_provider, timestamp)" in ddl
        )

    def test_mv_filters_unknown_operations(self):
        ddl = self.by_label["alo_summary_mv"]
        assert "WHERE request_operation != 'unknown'" in ddl

    def test_dynamic_stress_maps_are_typed(self):
        ddl = self.by_label["alo_raw_local"]
        assert "stress_cost_indicator_multipliers    Map(LowCardinality(String), Float64)" in ddl
        assert "stress_bonuses                       Map(LowCardinality(String), Float64)" in ddl

    def test_request_body_truncated_column_present(self):
        ddl = self.by_label["alo_raw_local"]
        assert "request_body_truncated" in ddl

    def test_request_body_truncated_alter_in_additions(self):
        labels = [label for label, _ in self.plan]
        assert "alter_alo_raw_request_body_truncated" in labels
        ddl = self.by_label["alter_alo_raw_request_body_truncated"]
        assert "ADD COLUMN IF NOT EXISTS request_body_truncated UInt8" in ddl


class TestClusterMode:
    def setup_method(self):
        s = TableSettings(cluster_enabled=True, cluster_name="alo_cluster")
        self.plan = all_ddl(s)
        self.by_label = dict(self.plan)

    def test_plan_contains_local_and_distributed_pairs(self):
        labels = [label for label, _ in self.plan]
        # Core DDL labels (alter_alo_raw_* labels follow at the end)
        assert labels[:8] == [
            "database",
            "alo_raw_local",
            "alo_raw",
            "alo_dead_letter_local",
            "alo_dead_letter",
            "alo_summary_local",
            "alo_summary",
            "alo_summary_mv",
        ]
        assert all(l.startswith("alter_alo_raw_") for l in labels[8:])

    def test_local_raw_uses_replicated_mergetree(self):
        ddl = self.by_label["alo_raw_local"]
        assert "ENGINE = ReplicatedMergeTree(" in ddl
        assert "'/clickhouse/tables/{shard}/alo_raw_local'" in ddl
        assert "'{replica}'" in ddl
        assert "ON CLUSTER 'alo_cluster'" in ddl

    def test_distributed_raw_table(self):
        ddl = self.by_label["alo_raw"]
        assert (
            "ENGINE = Distributed('alo_cluster', 'alo', 'alo_raw_local', "
            "cityHash64(cluster_name, request_operation))" in ddl
        )
        assert "ON CLUSTER 'alo_cluster'" in ddl

    def test_summary_uses_replicated_aggregating(self):
        ddl = self.by_label["alo_summary_local"]
        assert "ENGINE = ReplicatedAggregatingMergeTree(" in ddl

    def test_distributed_summary_table(self):
        ddl = self.by_label["alo_summary"]
        assert "Distributed('alo_cluster', 'alo', 'alo_summary_local'" in ddl

    def test_mv_reads_local_writes_local(self):
        ddl = self.by_label["alo_summary_mv"]
        assert "FROM alo.alo_raw_local" in ddl
        assert "TO alo.alo_summary_local" in ddl
        assert "ON CLUSTER 'alo_cluster'" in ddl


class TestRetentionOverrides:
    def test_custom_retention_propagates(self):
        s = TableSettings(raw_retention_days=7, summary_retention_days=365)
        by_label = dict(all_ddl(s))
        assert "INTERVAL 7 DAY DELETE" in by_label["alo_raw_local"]
        assert "INTERVAL 365 DAY DELETE" in by_label["alo_summary_local"]


class TestSummaryAggregates:
    def setup_method(self):
        by_label = dict(all_ddl(TableSettings()))
        self.summary_ddl = by_label["alo_summary_local"]
        self.mv_ddl = by_label["alo_summary_mv"]

    def test_quantile_states_for_es_took_gateway_took_score(self):
        for col in ("pct_es_took_ms_state",
                    "pct_gateway_took_ms_state",
                    "pct_score_state"):
            assert col in self.summary_ddl
            assert "AggregateFunction(quantiles(0.5, 0.95, 0.99)" in self.summary_ddl

    def test_mv_quantile_select_uses_correct_combinator_syntax(self):
        # ClickHouse combinator syntax: quantilesState(0.5,0.95,0.99)(col)
        # NOT: quantiles(0.5,0.95,0.99)State(col)
        assert "quantilesState(0.5, 0.95, 0.99)(response_es_took_ms)" in self.mv_ddl
        assert "quantilesState(0.5, 0.95, 0.99)(response_gateway_took_ms)" in self.mv_ddl
        assert "quantilesState(0.5, 0.95, 0.99)(stress_score)" in self.mv_ddl

    def test_count_state(self):
        assert "count_state                     AggregateFunction(count)" in self.summary_ddl


class TestTtlAndSettingsOverrides:
    def test_raw_ttl_clause_replaces_default(self):
        clause = "timestamp + INTERVAL 1 DAY TO VOLUME 'warm', timestamp + INTERVAL 7 DAY DELETE"
        s = TableSettings(raw_ttl_clause=clause, raw_retention_days=99)
        by_label = dict(all_ddl(s))
        ddl = by_label["alo_raw_local"]
        assert f"TTL {clause}" in ddl
        # Override wins over retention days
        assert "INTERVAL 99 DAY DELETE" not in ddl
        # Dead letter follows the same raw clause
        assert f"TTL {clause}" in by_label["alo_dead_letter_local"]

    def test_summary_ttl_clause_replaces_default(self):
        clause = "time_bucket + INTERVAL 30 DAY DELETE"
        s = TableSettings(summary_ttl_clause=clause, summary_retention_days=999)
        ddl = dict(all_ddl(s))["alo_summary_local"]
        assert f"TTL {clause}" in ddl
        assert "INTERVAL 999 DAY DELETE" not in ddl

    def test_empty_ttl_clause_falls_back_to_retention_days(self):
        s = TableSettings(raw_retention_days=14, summary_retention_days=180)
        by_label = dict(all_ddl(s))
        assert "INTERVAL 14 DAY DELETE" in by_label["alo_raw_local"]
        assert "INTERVAL 14 DAY DELETE" in by_label["alo_dead_letter_local"]
        assert "INTERVAL 180 DAY DELETE" in by_label["alo_summary_local"]

    def test_raw_extra_settings_merged_with_index_granularity(self):
        s = TableSettings(raw_extra_settings={
            "storage_policy": "hot_warm_cold",
            "merge_with_ttl_timeout": "86400",
        })
        ddl = dict(all_ddl(s))["alo_raw_local"]
        assert "index_granularity = 8192" in ddl
        assert "storage_policy = hot_warm_cold" in ddl
        assert "merge_with_ttl_timeout = 86400" in ddl

    def test_raw_extra_settings_override_index_granularity(self):
        s = TableSettings(raw_extra_settings={"index_granularity": "4096"})
        ddl = dict(all_ddl(s))["alo_raw_local"]
        assert "index_granularity = 4096" in ddl
        assert "index_granularity = 8192" not in ddl

    def test_summary_extra_settings_appended(self):
        s = TableSettings(summary_extra_settings={"storage_policy": "cold_only"})
        ddl = dict(all_ddl(s))["alo_summary_local"]
        assert "SETTINGS storage_policy = cold_only" in ddl

    def test_summary_no_settings_clause_by_default(self):
        ddl = dict(all_ddl(TableSettings()))["alo_summary_local"]
        assert "SETTINGS" not in ddl
