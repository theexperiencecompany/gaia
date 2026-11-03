"""The playbook series an alert reads exist from import, at zero, under their real labels."""

from prometheus_client import REGISTRY

from app.models.playbook_models import PlaybookRefusal
from app.services.workflow.playbook.metrics import REPLAY_STATUSES


def _label_sets(metric: str) -> list[dict[str, str]]:
    return [
        dict(sample.labels)
        for family in REGISTRY.collect()
        if family.name == metric
        for sample in family.samples
        if sample.name == f"{metric}_total"
    ]


def test_every_write_outcome_an_alert_reads_is_a_series_from_import() -> None:
    present = {
        (labels["tool"], labels["outcome"], labels["reason"])
        for labels in _label_sets("gaia_playbook_decision")
    }

    expected = {("write", "accepted", "none"), ("write", "error", "none")} | {
        ("write", "refused", kind.value) for kind in PlaybookRefusal
    }
    assert expected <= present
    assert not any("None" in labels for labels in present)


def test_every_replay_status_is_a_series_from_import() -> None:
    present = {labels["status"] for labels in _label_sets("gaia_playbook_replay")}

    assert {status.value for status in REPLAY_STATUSES} <= present
    assert "None" not in present
