#!/usr/bin/env python3
"""Fail on Google-facing content duplication in the SEO data forest.

Scans ``apps/web/public/data/`` (read-only; never app source) for the duplication
shapes two audits kept finding and CI never caught:

* exact duplicate FAQ questions (within one file, or the same question in two
  same-family files);
* byte-identical metaTitle / metaDescription on two different slugs;
* identical GAIA-column cell text reused across two or more files;
* paragraph-level near-duplicates: a shared 15+-token run inside one family;
* route-level collisions: reversed automate pairs (A-B and B-A both live) and
  compare / alternative-to pages for the same tool where neither declares the
  winner via ``canonicalSlug``;
* locale fallback drift: per-i18n-overlay share of entries byte-identical to
  the EN source, ratcheted so the share may only fall.

Nothing found today is illegal: the first run commits its findings as the
snapshot beside this script, and the gate fails only on NEW finding ids or a
RISING fallback share. Fixing debt removes ids from the snapshot with
``--update-snapshot``; adding a deliberate constant adds one line to the
allowlist with a dated why. Usage: ``python3 scripts/checks/content_dupes.py
[--root DIR] [--update-snapshot]``. Exit 0 clean, 1 violations, 2 environment
error. Stdlib only; whole-tree scan is ~1 s.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Iterator
import hashlib
import json
from pathlib import Path
import re
import sys
import time

HERE = Path(__file__).resolve().parent
SNAPSHOT_NAME = "content_dupes_snapshot.json"
ALLOWLIST_NAME = "content_dupes_allowlist.json"

DATA_REL = Path("apps/web/public/data")
# Families with per-slug JSON files plus the meta/faq schema the rules assume.
# blog/ has a different schema (7 essay files, no faqs) and is out of scope.
FAMILIES = ("alternatives", "comparisons", "combos", "glossary", "personas")
OVERLAY_FAMILIES = ("alternatives", "comparisons", "glossary", "personas", "integrations")
LOCALES = ("de", "es", "fr", "ja", "ko", "pt-BR")

NEAR_MIN_CHARS = 200
NEAR_TOKENS = 15
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def sha8(text: str) -> str:
    """Return the first 8 hex chars of the input's sha256 (stable finding ids)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def norm(text: str) -> str:
    """Collapse whitespace and casefold for duplicate comparison."""
    return " ".join(text.split()).casefold()


def fail(message: str) -> int:
    """Report an environment error (exit 2): never a silent green."""
    print(f"content-dupes: ERROR: {message}", file=sys.stderr)
    return 2


def load_json(path: Path) -> dict | list:
    """Read a JSON file or exit 2 naming it (fail loud, never skip)."""
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"missing required file: {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"unparseable JSON in {path}: {exc}") from exc
    if not isinstance(parsed, (dict, list)):
        raise SystemExit(f"expected a JSON object or array in {path}")
    return parsed


def slug_files(data_dir: Path, family: str) -> list[Path]:
    """Return the per-slug files of one family, excluding the _slugs index."""
    return sorted(p for p in (data_dir / family).glob("*.json") if p.name != "_slugs.json")


def iter_faqs(doc: dict) -> list[dict]:
    """Return the faq entries of a data file (empty when the file has none)."""
    faqs = doc.get("faqs")
    return [f for f in faqs if isinstance(f, dict)] if isinstance(faqs, list) else []


def check_faqs(data_dir: Path) -> dict[str, str]:
    """Find exact duplicate FAQ questions within/across same-family files."""
    findings: dict[str, str] = {}
    for family in FAMILIES:
        seen: dict[str, list[str]] = defaultdict(list)
        for path in slug_files(data_dir, family):
            doc = load_json(path)
            if not isinstance(doc, dict):
                continue
            slug = path.stem
            counts: dict[str, int] = defaultdict(int)
            for faq in iter_faqs(doc):
                question = faq.get("question")
                if not isinstance(question, str) or not norm(question):
                    continue
                key = norm(question)
                counts[key] += 1
                seen[key].append(slug)
            for key, count in counts.items():
                if count > 1:
                    findings[f"faq-within:{family}:{slug}:{sha8(key)}"] = (
                        f"{family}/{slug}: same question {count}x in one file ({key[:70]!r})"
                    )
        for key, slugs in seen.items():
            unique = sorted(set(slugs))
            if len(unique) > 1:
                for i, first in enumerate(unique):
                    for second in unique[i + 1 :]:
                        findings[f"faq-cross:{family}:{first}:{second}:{sha8(key)}"] = (
                            f"{family}/{first} x {family}/{second}: same question ({key[:70]!r})"
                        )
    return findings


def check_meta(data_dir: Path) -> dict[str, str]:
    """Find byte-identical metaTitle / metaDescription on two slugs."""
    findings: dict[str, str] = {}
    for family in FAMILIES:
        for field in ("metaTitle", "metaDescription"):
            owners: dict[str, list[str]] = defaultdict(list)
            for path in slug_files(data_dir, family):
                doc = load_json(path)
                if not isinstance(doc, dict):
                    continue
                value = doc.get(field)
                if isinstance(value, str) and value:
                    owners[value].append(path.stem)
            for value, slugs in owners.items():
                unique = sorted(set(slugs))
                if len(unique) > 1:
                    for i, first in enumerate(unique):
                        for second in unique[i + 1 :]:
                            findings[f"meta:{family}:{field}:{first}:{second}:{sha8(value)}"] = (
                                f"{family}/{first} x {family}/{second}: identical "
                                f"{field} ({value[:70]!r})"
                            )
    return findings


def gaia_texts(doc: dict, family: str) -> list[tuple[str, str]]:
    """Return (field, text) GAIA-column strings of one file."""
    out: list[tuple[str, str]] = []
    if family == "comparisons":
        for row in doc.get("rows") or []:
            if isinstance(row, dict) and isinstance(row.get("gaia"), str):
                out.append(("rows.gaia", row["gaia"]))
    if family == "alternatives":
        for field in ("gaiaAdvantages", "gaiaReplaces"):
            items = doc.get(field)
            if isinstance(items, list):
                out.extend((field, item) for item in items if isinstance(item, str))
    return [(field, text) for field, text in out if text.strip()]


def check_cells(data_dir: Path) -> dict[str, str]:
    """Find identical GAIA-column cell text reused across two or more files."""
    findings: dict[str, str] = {}
    for family in ("comparisons", "alternatives"):
        owners: dict[tuple[str, str], set[str]] = defaultdict(set)
        for path in slug_files(data_dir, family):
            doc = load_json(path)
            if not isinstance(doc, dict):
                continue
            for field, text in gaia_texts(doc, family):
                owners[(field, text)].add(path.stem)
        for (field, text), slugs in owners.items():
            if len(slugs) > 1:
                ordered = ",".join(sorted(slugs))
                findings[f"cell:{family}:{field}:{sha8(text)}:{ordered}"] = (
                    f"{family} x{len(slugs)} ({ordered}): reused GAIA cell ({text[:70]!r})"
                )
    return findings


def prose_texts(doc: dict) -> Iterator[tuple[str, str]]:
    """Yield (field label, text) for every paragraph-sized prose string."""
    for key, value in doc.items():
        if isinstance(value, str) and len(value) >= NEAR_MIN_CHARS:
            yield key, value
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, str) and len(item) >= NEAR_MIN_CHARS:
                    yield f"{key}[{i}]", item
                elif isinstance(item, dict):
                    for sub, text in item.items():
                        if isinstance(text, str) and len(text) >= NEAR_MIN_CHARS:
                            yield f"{key}.{sub}", text


def check_near_dupes(data_dir: Path, allowed: list[str]) -> tuple[dict[str, str], int]:
    """Find shared 15+-token runs inside one family (EN or one overlay)."""
    findings: dict[str, str] = {}
    skipped = 0
    populations: list[tuple[str, list[tuple[str, str, str]]]] = []
    for family in FAMILIES:
        items: list[tuple[str, str, str]] = []
        for path in slug_files(data_dir, family):
            doc = load_json(path)
            if isinstance(doc, dict):
                items.extend((path.stem, field, text) for field, text in prose_texts(doc))
        populations.append((family, items))
    for family in OVERLAY_FAMILIES:
        for locale in LOCALES:
            overlay = data_dir / "i18n" / family / f"{locale}.json"
            if not overlay.exists():
                continue
            doc = load_json(overlay)
            if not isinstance(doc, dict):
                continue
            items = [
                (slug, field, text)
                for slug, entry in doc.items()
                if isinstance(entry, dict)
                for field, text in prose_texts(entry)
            ]
            populations.append((f"{family}@{locale}", items))
    for pop, items in populations:
        grams: dict[tuple[str, ...], set[str]] = defaultdict(set)
        samples: dict[tuple[str, ...], str] = {}
        for slug, field, text in items:
            tokens = _TOKEN_RE.findall(text.lower())
            for i in range(len(tokens) - NEAR_TOKENS + 1):
                gram = tuple(tokens[i : i + NEAR_TOKENS])
                grams[gram].add(f"{slug}::{field}")
                samples.setdefault(gram, " ".join(gram))
        for gram, locs in grams.items():
            if len(locs) < 2:
                continue
            sample = samples[gram]
            if any(sub in sample for sub in allowed):
                skipped += 1
                continue
            ordered = sorted(locs)
            for i, first in enumerate(ordered):
                for second in ordered[i + 1 :]:
                    findings[f"near:{pop}:{first}<<{second}:{sha8(sample)}"] = (
                        f"{pop} {first} x {second}: shared {NEAR_TOKENS}+-token run "
                        f"({sample[:70]!r})"
                    )
    return findings, skipped


def check_reversed_pairs(data_dir: Path) -> dict[str, str]:
    """Find both-orders automate pairs with no canonicalSlug deferral."""
    findings: dict[str, str] = {}
    combos: dict[str, dict] = {}
    for path in slug_files(data_dir, "combos"):
        doc = load_json(path)
        if isinstance(doc, dict):
            combos[path.stem] = doc
    groups: dict[frozenset[str], list[str]] = defaultdict(list)
    for slug, doc in combos.items():
        first, second = doc.get("toolASlug"), doc.get("toolBSlug")
        if (
            isinstance(first, str)
            and isinstance(second, str)
            and first
            and second
            and first != second
        ):
            groups[frozenset((first, second))].append(slug)
    for pair, slugs in groups.items():
        if len(slugs) < 2:
            continue
        for i, first in enumerate(sorted(slugs)):
            for second in sorted(slugs)[i + 1 :]:
                first_defers = combos[first].get("canonicalSlug") == second
                second_defers = combos[second].get("canonicalSlug") == first
                if first_defers != second_defers:
                    continue
                reason = "both declare" if first_defers else "neither declares"
                findings[f"pair-reversed:{first}:{second}"] = (
                    f"combos/{first} x combos/{second} ({'/'.join(sorted(pair))}): "
                    f"{reason} canonicalSlug"
                )
    return findings


def check_no_winner(data_dir: Path) -> dict[str, str]:
    """Find compare/alternative-to same-tool pairs with no declared winner."""
    findings: dict[str, str] = {}
    comparisons = {p.stem: load_json(p) for p in slug_files(data_dir, "comparisons")}
    alternatives = {p.stem: load_json(p) for p in slug_files(data_dir, "alternatives")}
    for slug in sorted(set(comparisons) & set(alternatives)):
        first, second = comparisons[slug], alternatives[slug]
        if not isinstance(first, dict) or not isinstance(second, dict):
            continue
        if not first.get("canonicalSlug") and not second.get("canonicalSlug"):
            findings[f"pair-nowinner:{slug}"] = (
                f"compare/{slug} x alternative-to/{slug}: neither declares "
                "canonicalSlug (no declared winner)"
            )
    return findings


def fallback_shares(data_dir: Path) -> dict[str, float]:
    """Return per-overlay share of entries byte-identical to (or missing from) EN."""
    shares: dict[str, float] = {}
    for family in OVERLAY_FAMILIES:
        en_path = data_dir / "i18n" / family / "en.json"
        if not en_path.exists():
            continue
        en = load_json(en_path)
        if not isinstance(en, dict) or not en:
            continue
        for locale in LOCALES:
            overlay_path = data_dir / "i18n" / family / f"{locale}.json"
            if not overlay_path.exists():
                continue
            overlay = load_json(overlay_path)
            if not isinstance(overlay, dict):
                continue
            identical = sum(1 for key, entry in en.items() if overlay.get(key) == entry)
            missing = sum(1 for key in en if key not in overlay)
            shares[f"{family}/{locale}"] = round(100 * (identical + missing) / len(en), 1)
    return shares


def load_allowlist(path: Path) -> list[str]:
    """Read deliberate-constant substrings (each with a dated why) or fail."""
    if not path.exists():
        return []
    doc = load_json(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("contains"), list):
        raise SystemExit(f"malformed allowlist {path}: want {'contains': [...]}")
    allowed: list[str] = []
    for entry in doc["contains"]:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("text"), str)
            or not entry["text"]
            or not isinstance(entry.get("why"), str)
            or not entry["why"]
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(entry.get("date")))
        ):
            raise SystemExit(
                f"malformed allowlist entry in {path}: each needs text, why, "
                f"date=YYYY-MM-DD (got {entry!r})"
            )
        allowed.append(entry["text"].lower())
    return allowed


def read_snapshot(path: Path) -> tuple[dict[str, float], set[str]]:
    """Read the committed snapshot or fail loud (never default to empty)."""
    if not path.exists():
        raise SystemExit(
            f"missing snapshot {path} — generate it with "
            "`python3 scripts/checks/content_dupes.py --update-snapshot` and commit it"
        )
    doc = load_json(path)
    if (
        not isinstance(doc, dict)
        or not isinstance(doc.get("fallbacks"), dict)
        or not isinstance(doc.get("known"), list)
    ):
        raise SystemExit(f"malformed snapshot {path}: want fallbacks dict + known list")
    return (
        {str(k): float(v) for k, v in doc["fallbacks"].items()},
        {str(i) for i in doc["known"]},
    )


def write_snapshot(path: Path, fallbacks: dict[str, float], known: set[str]) -> None:
    """Record today's findings as the new baseline (review the diff)."""
    payload = {
        "_note": (
            "content-dupes baseline: every id in known existed when the snapshot "
            "was written; CI fails only on NEW ids or a RISING fallback share. "
            "Falling shares always pass. Regenerate with --update-snapshot and "
            "commit the diff so it stays reviewable."
        ),
        "fallbacks": dict(sorted(fallbacks.items())),
        "known": sorted(known),
    }
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def scan(data_dir: Path, allowed: list[str]) -> tuple[dict[str, str], dict[str, float], int]:
    """Run every rule; return (findings, fallback shares, allowlisted grams)."""
    findings: dict[str, str] = {}
    findings.update(check_faqs(data_dir))
    findings.update(check_meta(data_dir))
    findings.update(check_cells(data_dir))
    near, skipped = check_near_dupes(data_dir, allowed)
    findings.update(near)
    findings.update(check_reversed_pairs(data_dir))
    findings.update(check_no_winner(data_dir))
    return findings, fallback_shares(data_dir), skipped


def main(argv: list[str] | None = None) -> int:
    """Parse args, scan, and gate on new findings or rising fallbacks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=HERE.parents[1])
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--snapshot", type=Path, default=HERE / SNAPSHOT_NAME)
    parser.add_argument("--allowlist", type=Path, default=HERE / ALLOWLIST_NAME)
    parser.add_argument("--update-snapshot", action="store_true")
    args = parser.parse_args(argv)

    data_dir = args.data_dir or (args.root / DATA_REL)
    if not data_dir.is_dir():
        return fail(f"data dir missing: {data_dir}")

    started = time.monotonic()
    try:
        allowed = load_allowlist(args.allowlist)
        findings, shares, skipped = scan(data_dir, allowed)
    except SystemExit as exc:
        return fail(str(exc))
    elapsed = time.monotonic() - started

    counts: dict[str, int] = defaultdict(int)
    for finding_id in findings:
        counts[finding_id.split(":")[0]] += 1

    if args.update_snapshot:
        try:
            previous_known = read_snapshot(args.snapshot)[1]
        except SystemExit:
            previous_known = set()
        write_snapshot(args.snapshot, shares, set(findings))
        delta = len(findings) - len(previous_known)
        print(
            f"content-dupes: snapshot updated — {len(findings)} known finding(s) "
            f"({delta:+d}) across {len(shares)} overlays in {elapsed:.1f}s. "
            "Commit the diff so the change is reviewable."
        )
        return 0

    try:
        base_fallbacks, known = read_snapshot(args.snapshot)
    except SystemExit as exc:
        return fail(str(exc))

    new = {i: findings[i] for i in findings if i not in known}
    risen = {
        key: (base_fallbacks.get(key), value)
        for key, value in shares.items()
        if key in base_fallbacks and value > base_fallbacks[key]
    }
    fresh_overlays = [key for key in shares if key not in base_fallbacks]

    print(
        f"content-dupes: {len(findings)} finding(s) "
        f"({', '.join(f'{k}={v}' for k, v in sorted(counts.items()))}), "
        f"{skipped} allowlisted near-dupe gram(s), "
        f"{len(shares)} overlay fallback share(s), {elapsed:.1f}s"
    )
    for key in sorted(shares):
        base = base_fallbacks.get(key)
        arrow = "" if base is None else (" (RISE)" if key in risen else "")
        print(f"  fallback {key}: {shares[key]:.1f}% (base {base}){arrow}")
    for key in fresh_overlays:
        print(f"  fallback {key}: new overlay, recorded on --update-snapshot")

    if new or risen:
        shown = 0
        for finding_id in sorted(new):
            if shown >= 30:
                break
            print(f"NEW {finding_id} — {new[finding_id]}")
            shown += 1
        if len(new) > shown:
            print(f"... and {len(new) - shown} more new finding(s)")
        for key in sorted(risen):
            print(
                f"RISEN fallback {key}: {risen[key][0]:.1f}% -> {risen[key][1]:.1f}% "
                "(translate or remove the fallback; falling always passes)"
            )
        print(
            f"content-dupes: FAIL — {len(new)} new finding(s), "
            f"{len(risen)} risen fallback(s). Fix them, or justify and record with "
            "`python3 scripts/checks/content_dupes.py --update-snapshot`."
        )
        return 1
    fixed = sorted(set(known) - set(findings))
    if fixed:
        print(
            f"content-dupes: {len(fixed)} grandfathered finding(s) gone — lock the "
            "win in with --update-snapshot."
        )
    print("content-dupes: OK (no new findings, no rising fallbacks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
