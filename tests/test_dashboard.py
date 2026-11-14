"""README dashboard of the latest automatic update."""

from nexonic import dashboard


def test_readme_dashboard_lists_changes_and_recent_days():
    report = {
        "counts": {"new_published": 2, "restored": 0, "newly_quarantined": 1, "removed": 0},
        "lists": {
            "new_published": [
                {"id": "a", "name": "Alpha", "country": "de"},
                {"id": "b", "name": "Beta", "country": "fr"},
            ],
            "newly_quarantined": [{"id": "c", "name": "Gamma", "country": "us"}],
        },
    }
    days = [
        {"date": f"2026-11-0{i}", "counts": {"new_published": i}, "lifecycle_counts": {"working": 10 + i}}
        for i in range(1, 10)
    ]
    out = "\n".join(dashboard.lines(report, days))
    assert "| New channels added | 2 |" in out and "Alpha" in out and "Gamma" in out
    assert "| Removed for good | 0 | - |" in out
    assert "2026-11-09" in out and "2026-11-02" not in out  # only the last 7 days, newest first
    assert out.index("2026-11-09") < out.index("2026-11-03")
    readme = "a\n<!-- end -->\nb"
    assert dashboard.insert(readme, ["X"], "<!-- end -->") == "a\nX\n<!-- end -->\nb"
    assert dashboard.lines(None, days) == []
