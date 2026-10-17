"""content_dupes.py: the standing guard over the SEO data forest.

Drives the real script against a miniature data forest in tmp_path — never a
reimplementation. Each rule gets one fixture that must fail, plus the
snapshot/ratchet mechanics: first run records, rerun passes, any NEW finding
or RISING fallback share fails, and falling shares always pass.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

SCRIPT = Path(__file__).resolve().parent.parent.parent / "checks" / "content_dupes.py"

COMPARISON = {
    "slug": "widget",
    "metaTitle": "Widget vs GAIA",
    "metaDescription": "How GAIA compares to Widget.",
    "rows": [{"feature": "x", "gaia": "GAIA does x", "competitor": "Widget does x"}],
    "faqs": [{"question": "Is GAIA cheaper?", "answer": "y" * 200}],
}


def write_forest(root: Path, files: dict[str, dict]) -> Path:
    """Lay out a miniature apps/web/public/data tree under root."""
    data = root / "apps" / "web" / "public" / "data"
    for rel, doc in files.items():
        path = data / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc), encoding="utf-8")
    return data


def run(tmp_path: Path, *args: str, data: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run the real checker with an empty allowlist and tmp snapshot."""
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text('{"contains": []}', encoding="utf-8")
    snapshot = tmp_path / "snapshot.json"
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--allowlist",
        str(allowlist),
        "--snapshot",
        str(snapshot),
    ]
    if data is not None:
        cmd += ["--data-dir", str(data)]
    return subprocess.run([*cmd, *args], capture_output=True, text=True, check=False)


def test_clean_forest_passes(tmp_path: Path) -> None:
    """A forest with no duplication passes once its snapshot exists."""
    data = write_forest(tmp_path, {"comparisons/widget.json": COMPARISON})
    assert run(tmp_path, "--update-snapshot", data=data).returncode == 0
    proc = run(tmp_path, data=data)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK (no new findings" in proc.stdout


def test_faq_within_file_fails(tmp_path: Path) -> None:
    """The same question twice in one file is a new finding."""
    doc = dict(COMPARISON)
    doc["faqs"] = [
        {"question": "Is GAIA cheaper?", "answer": "y" * 200},
        {"question": "  is gaia CHEAPER? ", "answer": "z" * 200},
    ]
    data = write_forest(tmp_path, {"comparisons/widget.json": COMPARISON})
    assert run(tmp_path, "--update-snapshot", data=data).returncode == 0
    data = write_forest(tmp_path, {"comparisons/widget.json": doc})
    proc = run(tmp_path, data=data)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "faq-within:comparisons:widget:" in proc.stdout


def test_faq_cross_file_fails(tmp_path: Path) -> None:
    """The same question in two same-family files is a new finding."""
    data = write_forest(tmp_path, {"comparisons/widget.json": COMPARISON})
    assert run(tmp_path, "--update-snapshot", data=data).returncode == 0
    other = dict(COMPARISON)
    other["slug"] = "gadget"
    other["metaTitle"] = "Gadget vs GAIA"
    other["metaDescription"] = "How GAIA compares to Gadget."
    other["rows"] = [{"feature": "x", "gaia": "GAIA handles x", "competitor": "no"}]
    data = write_forest(
        tmp_path,
        {"comparisons/widget.json": COMPARISON, "comparisons/gadget.json": other},
    )
    proc = run(tmp_path, data=data)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "faq-cross:comparisons:gadget:widget:" in proc.stdout


def test_meta_and_cell_dupes_fail(tmp_path: Path) -> None:
    """Byte-identical meta and reused GAIA cells are new findings."""
    data = write_forest(tmp_path, {"comparisons/widget.json": COMPARISON})
    assert run(tmp_path, "--update-snapshot", data=data).returncode == 0
    other = dict(COMPARISON)
    other["slug"] = "gadget"
    other["faqs"] = [{"question": "Something else?", "answer": "w" * 200}]
    data = write_forest(
        tmp_path,
        {"comparisons/widget.json": COMPARISON, "comparisons/gadget.json": other},
    )
    proc = run(tmp_path, data=data)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "meta:comparisons:metaTitle:gadget:widget:" in proc.stdout
    assert "cell:comparisons:rows.gaia:" in proc.stdout


def test_reversed_pair_needs_canonical(tmp_path: Path) -> None:
    """A both-orders automate pair fails until one side defers via canonicalSlug."""
    first = {
        "slug": "a-b",
        "toolASlug": "a",
        "toolBSlug": "b",
        "metaTitle": "A",
        "metaDescription": "d1",
        "faqs": [],
    }
    data = write_forest(tmp_path, {"combos/a-b.json": first})
    assert run(tmp_path, "--update-snapshot", data=data).returncode == 0
    second = dict(first)
    second.update(
        {
            "slug": "b-a",
            "toolASlug": "b",
            "toolBSlug": "a",
            "metaTitle": "B",
            "metaDescription": "d2",
        }
    )
    data = write_forest(tmp_path, {"combos/a-b.json": first, "combos/b-a.json": second})
    proc = run(tmp_path, data=data)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "pair-reversed:a-b:b-a" in proc.stdout
    fixed = dict(first)
    fixed["canonicalSlug"] = "b-a"
    data = write_forest(tmp_path, {"combos/a-b.json": fixed, "combos/b-a.json": second})
    proc = run(tmp_path, data=data)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_compare_alternative_pair_needs_winner(tmp_path: Path) -> None:
    """A tool with both pages fails until either side declares canonicalSlug."""
    data = write_forest(tmp_path, {"comparisons/widget.json": COMPARISON})
    assert run(tmp_path, "--update-snapshot", data=data).returncode == 0
    alt = {"slug": "widget", "metaTitle": "t", "metaDescription": "d", "faqs": []}
    data = write_forest(
        tmp_path,
        {"comparisons/widget.json": COMPARISON, "alternatives/widget.json": alt},
    )
    proc = run(tmp_path, data=data)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "pair-nowinner:widget" in proc.stdout
    fixed = dict(alt)
    fixed["canonicalSlug"] = "widget"
    data = write_forest(
        tmp_path,
        {"comparisons/widget.json": COMPARISON, "alternatives/widget.json": fixed},
    )
    assert run(tmp_path, data=data).returncode == 0


def test_fallback_rise_fails_fall_passes(tmp_path: Path) -> None:
    """A rising byte-identical overlay share fails; a falling one passes."""
    en = {"widget": {"name": "Widget", "tagline": "t", "description": "d" * 200}}
    de_same = {"widget": {"name": "Widget", "tagline": "t", "description": "d" * 200}}
    data = write_forest(
        tmp_path,
        {
            "comparisons/widget.json": COMPARISON,
            "i18n/comparisons/en.json": en,
            "i18n/comparisons/de.json": de_same,
        },
    )
    assert run(tmp_path, "--update-snapshot", data=data).returncode == 0
    assert run(tmp_path, data=data).returncode == 0
    snapshot = json.loads((tmp_path / "snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["fallbacks"]["comparisons/de"] == 100.0
    # Translate half the entry: the share falls, and the gate stays green.
    de_half = {
        "widget": {
            "name": "Widget",
            "tagline": "translated",
            "description": "d" * 200,
        }
    }
    data = write_forest(
        tmp_path,
        {
            "comparisons/widget.json": COMPARISON,
            "i18n/comparisons/en.json": en,
            "i18n/comparisons/de.json": de_half,
        },
    )
    assert run(tmp_path, data=data).returncode == 0
    # Back to fully identical: the share rises against the base, and it fails.
    data = write_forest(
        tmp_path,
        {
            "comparisons/widget.json": COMPARISON,
            "i18n/comparisons/en.json": en,
            "i18n/comparisons/de.json": de_same,
        },
    )
    snapshot = json.loads((tmp_path / "snapshot.json").read_text(encoding="utf-8"))
    snapshot["fallbacks"]["comparisons/de"] = 0.0
    (tmp_path / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    proc = run(tmp_path, data=data)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "RISEN fallback comparisons/de" in proc.stdout


def test_missing_snapshot_fails_loud(tmp_path: Path) -> None:
    """No snapshot is an environment error, never a silent green."""
    data = write_forest(tmp_path, {"comparisons/widget.json": COMPARISON})
    proc = run(tmp_path, data=data)
    assert proc.returncode == 2
    assert "missing snapshot" in proc.stderr


def test_malformed_allowlist_entry_fails_loud(tmp_path: Path) -> None:
    """An allowlist entry without a dated why is an error, not a skip."""
    data = write_forest(tmp_path, {"comparisons/widget.json": COMPARISON})
    (tmp_path / "allowlist.json").write_text('{"contains": [{"text": "x"}]}', encoding="utf-8")
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--allowlist",
        str(tmp_path / "allowlist.json"),
        "--snapshot",
        str(tmp_path / "snapshot.json"),
        "--data-dir",
        str(data),
        "--update-snapshot",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 2
    assert "malformed allowlist" in proc.stderr


def test_snapshot_round_trip_stable(tmp_path: Path) -> None:
    """Snapshot round-trip: identical forest, identical ids, green rerun."""
    doc = dict(COMPARISON)
    doc["faqs"] = [
        {"question": "Is GAIA cheaper?", "answer": "y" * 200},
        {"question": "Is GAIA cheaper?", "answer": "z" * 200},
    ]
    data = write_forest(tmp_path, {"comparisons/widget.json": doc})
    assert run(tmp_path, "--update-snapshot", data=data).returncode == 0
    first = json.loads((tmp_path / "snapshot.json").read_text(encoding="utf-8"))
    assert run(tmp_path, "--update-snapshot", data=data).returncode == 0
    second = json.loads((tmp_path / "snapshot.json").read_text(encoding="utf-8"))
    assert first == second
    assert any(i.startswith("faq-within") for i in second["known"])
