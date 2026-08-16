"""Unit tests for grafana/_dashboards.py — dashboard variable SQL builder."""

from grafana._dashboards import _make_query_var, _SUMMARY_COLUMNS


class TestQueryVariables:
    def test_summary_column_uses_summary_table_and_hour_aligned_time_bound(self):
        var = _make_query_var("cluster", "Cluster", "cluster_name")
        sql = var["query"]["rawSql"]
        assert "alo.alo_summary" in sql
        assert "toStartOfHour($__fromTime)" in sql
        assert "$__toTime" in sql

    def test_raw_column_uses_raw_table_and_time_filter_macro(self):
        var = _make_query_var("username", "Username", "identity_username")
        sql = var["query"]["rawSql"]
        assert "alo.alo_raw" in sql
        assert "$__timeFilter(timestamp)" in sql

    def test_no_row_cap_or_fixed_lookback(self):
        for column in _SUMMARY_COLUMNS | {"identity_username", "identity_client_host"}:
            sql = _make_query_var("var", "Var", column)["query"]["rawSql"]
            assert "LIMIT 200000" not in sql
            assert "INTERVAL" not in sql
            assert "GROUP BY v" in sql

    def test_array_column_still_unnests_via_arrayjoin(self):
        var = _make_query_var("cost_indicator", "Cost Indicator",
                              "stress_cost_indicator_names")
        sql = var["query"]["rawSql"]
        assert "arrayJoin(" in sql
        assert "GROUP BY v" in sql

    def test_all_value_pinned_to_sentinel(self):
        var = _make_query_var("cluster", "Cluster", "cluster_name")
        assert var["allValue"] == "$__all"
        assert var["refresh"] == 2
