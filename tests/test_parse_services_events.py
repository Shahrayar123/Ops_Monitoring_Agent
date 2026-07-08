"""Tests for parsing the real service-status and alert exports."""

from data_sources import parse_cm_export


def test_parse_services_reads_standard_shape():
    raw = {
        "items": [
            {
                "name": "hdfs",
                "type": "HDFS",
                "clusterRef": {"clusterName": "c1"},
                "serviceState": "STARTED",
                "healthSummary": "CONCERNING",
                "healthChecks": [{"name": "HDFS_FREE_SPACE", "summary": "CONCERNING"}],
            },
            {
                "name": "tez",
                "type": "TEZ",
                "clusterRef": {"clusterName": "c1"},
                "serviceState": "NA",              # config-only service
                "healthSummary": "GOOD",
                "healthChecks": [],
            },
            {"name": "other", "type": "X", "clusterRef": {"clusterName": "c2"},
             "serviceState": "STARTED", "healthSummary": "GOOD", "healthChecks": []},
        ]
    }
    services = parse_cm_export.parse_services(raw, "c1")
    names = {s.name for s in services}
    assert names == {"hdfs", "tez"}            # c2's service filtered out
    hdfs = next(s for s in services if s.name == "hdfs")
    assert hdfs.health_summary == "CONCERNING"


def test_parse_events_flattens_list_attributes_and_filters():
    raw = {
        "items": [
            {
                "id": "e1",
                "content": "role bad",
                "timeOccurred": "2026-07-06T06:15:51.632Z",
                "category": "HEALTH_EVENT",
                "severity": "CRITICAL",
                "alert": True,
                "attributes": [
                    {"name": "ALERT_SUMMARY", "values": ["Event Server became bad"]},
                    {"name": "ROLE_TYPE", "values": ["EVENTSERVER"]},
                ],
            },
            {
                "id": "e2",
                "content": "not an alert",
                "timeOccurred": "2026-07-06T06:15:51.632Z",
                "category": "AUDIT_EVENT",
                "severity": "INFORMATIONAL",
                "alert": False,
                "attributes": [],
            },
        ]
    }
    # alert_only=True drops e2; attributes become a {name: [values]} dict
    events = parse_cm_export.parse_events(raw, category=None, alert_only=True)
    assert [e.id for e in events] == ["e1"]
    assert events[0].attributes["ALERT_SUMMARY"] == ["Event Server became bad"]

    # alert_only=False keeps both
    assert len(parse_cm_export.parse_events(raw, category=None, alert_only=False)) == 2
    # category filter still works
    assert len(parse_cm_export.parse_events(raw, category="AUDIT_EVENT", alert_only=False)) == 1
