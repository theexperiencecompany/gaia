#!/usr/bin/env python3
"""Snapshot Composio tools and verify builtin skill tool references.

This script does three things:
1. Fetches real Composio tools per integration toolkit.
2. Scans source files for custom tools registered via
   ``@composio.tools.custom_tool(...)``.
3. Verifies tool names used in ``app/agents/skills/builtin/*/SKILL.md``
   are present in the fetched inventory.

Usage:
    cd apps/api
    python scripts/sync_composio_tools.py

    # Restrict to one or more toolkits
    python scripts/sync_composio_tools.py --toolkit GMAIL --toolkit NOTION

    # Restrict by integration id(s) from oauth_config.py
    python scripts/sync_composio_tools.py --integration gmail
"""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


BACKEND_DIR = Path(__file__).parent.parent
DEFAULT_OUTPUT_DIR = (
    BACKEND_DIR.parent.parent / ".agents" / "plans" / "composio_tools_output"
)
sys.path.insert(0, str(BACKEND_DIR))

if not os.getenv("ENV"):
    os.environ["ENV"] = "development"


from app.config.oauth_config import OAUTH_INTEGRATIONS  # noqa: E402
from app.config.settings import settings  # noqa: E402
from composio import Composio  # noqa: E402


TOOL_NAME_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+)\b")
CUSTOM_TOOL_FILE_PATTERNS = [
    "app/agents/tools/*_tool.py",
    "app/services/composio/custom_tools/*.py",
]


@dataclass(frozen=True)
class IntegrationToolkit:
    integration_id: str
    integration_name: str
    toolkit: str
    toolkit_version: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch Composio tools, write inventories to files, and verify "
            "builtin skill tool references."
        )
    )
    parser.add_argument(
        "--toolkit",
        action="append",
        default=[],
        help="Toolkit slug(s) to scan, e.g. GMAIL",
    )
    parser.add_argument(
        "--integration",
        action="append",
        default=[],
        help="Integration id(s) from oauth config, e.g. gmail",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Max tools fetched per toolkit from Composio (default: 1000)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=(
            "Output directory (absolute or relative to apps/api). "
            f"Default: {DEFAULT_OUTPUT_DIR}"
        ),
    )
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Exit 0 even when unknown tool references are found.",
    )
    return parser.parse_args()


def load_integration_toolkits() -> dict[str, IntegrationToolkit]:
    toolkits: dict[str, IntegrationToolkit] = {}

    for integration in OAUTH_INTEGRATIONS:
        composio_config = integration.composio_config
        if not composio_config:
            continue

        toolkit = composio_config.toolkit.upper()
        if toolkit in toolkits:
            continue

        toolkits[toolkit] = IntegrationToolkit(
            integration_id=integration.id,
            integration_name=integration.name,
            toolkit=toolkit,
            toolkit_version=composio_config.toolkit_version,
        )

    return toolkits


def resolve_toolkits_to_scan(
    all_toolkits: dict[str, IntegrationToolkit],
    toolkit_filters: list[str],
    integration_filters: list[str],
) -> list[str]:
    selected: set[str] = set()

    integration_to_toolkit = {
        value.integration_id.lower(): key for key, value in all_toolkits.items()
    }

    for integration_id in integration_filters:
        resolved = integration_to_toolkit.get(integration_id.lower())
        if not resolved:
            valid = ", ".join(sorted(integration_to_toolkit))
            raise ValueError(
                f"Unknown integration '{integration_id}'. Valid ids: {valid}"
            )
        selected.add(resolved)

    for toolkit in toolkit_filters:
        selected.add(toolkit.upper())

    if not selected:
        selected = set(all_toolkits.keys())

    return sorted(selected)


def build_toolkit_versions(
    all_toolkits: dict[str, IntegrationToolkit],
) -> dict[str, str]:
    versions: dict[str, str] = {}
    for metadata in all_toolkits.values():
        if metadata.toolkit_version:
            versions[metadata.toolkit.lower()] = metadata.toolkit_version
    return versions


def fetch_composio_tools(
    composio: Composio,
    toolkit: str,
    limit: int,
) -> tuple[list[dict[str, str]], str | None]:
    try:
        tools = composio.tools.get_raw_composio_tools(
            toolkits=[toolkit],
            limit=limit,
        )
    except Exception as exc:
        return [], str(exc)

    by_slug: dict[str, dict[str, str]] = {}
    for tool in tools:
        slug = getattr(tool, "slug", "")
        if not slug:
            continue
        by_slug[slug] = {
            "slug": slug,
            "description": getattr(tool, "description", "") or "",
        }

    return sorted(by_slug.values(), key=lambda value: value["slug"]), None


def discover_custom_tool_files() -> list[Path]:
    paths: set[Path] = set()
    for pattern in CUSTOM_TOOL_FILE_PATTERNS:
        for file_path in BACKEND_DIR.glob(pattern):
            if file_path.is_file() and not file_path.name.startswith("__"):
                paths.add(file_path)
    return sorted(paths)


def extract_custom_toolkit_from_decorator(decorator: ast.AST) -> str | None:
    if not isinstance(decorator, ast.Call):
        return None

    if not isinstance(decorator.func, ast.Attribute):
        return None

    if decorator.func.attr != "custom_tool":
        return None

    for keyword in decorator.keywords:
        if keyword.arg != "toolkit":
            continue
        if isinstance(keyword.value, ast.Constant) and isinstance(
            keyword.value.value,
            str,
        ):
            return keyword.value.value.upper()

    return None


def scan_custom_tools() -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
    tools_by_toolkit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    parse_errors: list[dict[str, str]] = []

    for file_path in discover_custom_tool_files():
        rel_path = file_path.relative_to(BACKEND_DIR).as_posix()

        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception as exc:
            parse_errors.append({"file": rel_path, "error": str(exc)})
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            toolkit = None
            for decorator in node.decorator_list:
                toolkit = extract_custom_toolkit_from_decorator(decorator)
                if toolkit:
                    break

            if not toolkit:
                continue

            slug = f"{toolkit}_{node.name.upper()}"
            tools_by_toolkit[toolkit].append(
                {
                    "slug": slug,
                    "file": rel_path,
                    "line": node.lineno,
                }
            )

    deduped: dict[str, list[dict[str, Any]]] = {}
    for toolkit, records in tools_by_toolkit.items():
        by_slug: dict[str, dict[str, Any]] = {}
        for record in records:
            by_slug.setdefault(record["slug"], record)
        deduped[toolkit] = sorted(by_slug.values(), key=lambda value: value["slug"])

    return deduped, parse_errors


def parse_skill_frontmatter(content: str) -> dict[str, Any]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break

    if end_index is None:
        return {}

    frontmatter = "\n".join(lines[1:end_index])
    parsed = yaml.safe_load(frontmatter)
    if isinstance(parsed, dict):
        return parsed
    return {}


def collect_skill_tool_references(
    skills_dir: Path,
    known_prefixes: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    references: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []

    skill_paths = sorted(skills_dir.glob("*/SKILL.md"))
    for skill_path in skill_paths:
        rel_path = skill_path.relative_to(BACKEND_DIR).as_posix()

        try:
            content = skill_path.read_text(encoding="utf-8")
        except Exception as exc:
            parse_errors.append({"file": rel_path, "error": str(exc)})
            continue

        metadata = parse_skill_frontmatter(content)
        skill_name = str(metadata.get("name") or skill_path.parent.name)
        target = str(metadata.get("target") or "executor")

        for line_number, line in enumerate(content.splitlines(), start=1):
            for tool_name in TOOL_NAME_PATTERN.findall(line):
                prefix = tool_name.split("_", 1)[0]
                if prefix not in known_prefixes:
                    continue

                references.append(
                    {
                        "tool": tool_name,
                        "skill": skill_name,
                        "target": target,
                        "path": rel_path,
                        "line": line_number,
                        "context": line.strip(),
                    }
                )

    return references, parse_errors


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def build_unknown_tool_report(
    references: list[dict[str, Any]],
    available_tools: set[str],
) -> list[dict[str, Any]]:
    unknown_by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for reference in references:
        tool_name = reference["tool"]
        if tool_name not in available_tools:
            unknown_by_tool[tool_name].append(reference)

    sorted_available = sorted(available_tools)
    report: list[dict[str, Any]] = []

    for tool_name in sorted(unknown_by_tool):
        suggestions = difflib.get_close_matches(
            tool_name,
            sorted_available,
            n=3,
            cutoff=0.65,
        )
        report.append(
            {
                "tool": tool_name,
                "suggestions": suggestions,
                "references": unknown_by_tool[tool_name],
            }
        )

    return report


def write_markdown_report(
    path: Path,
    generated_at: str,
    toolkits: list[str],
    total_available_tools: int,
    total_references: int,
    unknown_tools: list[dict[str, Any]],
    fetch_errors: list[dict[str, str]],
    skill_parse_errors: list[dict[str, str]],
    custom_scan_errors: list[dict[str, str]],
) -> None:
    lines: list[str] = []
    lines.append("# Composio Tool Verification")
    lines.append("")
    lines.append(f"Generated: {generated_at}")
    lines.append(f"Toolkits scanned: {', '.join(toolkits)}")
    lines.append(f"Available tools: {total_available_tools}")
    lines.append(f"Skill tool references scanned: {total_references}")
    lines.append(f"Unknown references: {len(unknown_tools)}")
    lines.append("")

    if unknown_tools:
        lines.append("## Unknown Tool References")
        lines.append("")
        for item in unknown_tools:
            lines.append(f"### {item['tool']}")
            if item["suggestions"]:
                lines.append(f"- Suggestions: {', '.join(item['suggestions'])}")
            for ref in item["references"]:
                location = f"{ref['path']}:{ref['line']}"
                lines.append(f"- {location} ({ref['skill']})")
            lines.append("")
    else:
        lines.append("## Unknown Tool References")
        lines.append("")
        lines.append("No unknown references detected.")
        lines.append("")

    if fetch_errors:
        lines.append("## Toolkit Fetch Errors")
        lines.append("")
        for error in fetch_errors:
            lines.append(f"- {error['toolkit']}: {error['error']}")
        lines.append("")

    if skill_parse_errors:
        lines.append("## Skill Parse Errors")
        lines.append("")
        for error in skill_parse_errors:
            lines.append(f"- {error['file']}: {error['error']}")
        lines.append("")

    if custom_scan_errors:
        lines.append("## Custom Tool Scan Errors")
        lines.append("")
        for error in custom_scan_errors:
            lines.append(f"- {error['file']}: {error['error']}")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()

    all_toolkits = load_integration_toolkits()
    selected_toolkits = resolve_toolkits_to_scan(
        all_toolkits=all_toolkits,
        toolkit_filters=args.toolkit,
        integration_filters=args.integration,
    )

    if not settings.COMPOSIO_KEY:
        print("ERROR: COMPOSIO_KEY is not set.")
        return 2

    toolkit_versions = build_toolkit_versions(all_toolkits)
    composio = Composio(
        api_key=settings.COMPOSIO_KEY,
        timeout=120,
        toolkit_versions=toolkit_versions or None,
    )

    print("=" * 80)
    print("COMPOSIO TOOLS SYNC")
    print("=" * 80)
    print(f"Toolkits requested: {', '.join(selected_toolkits)}")

    composio_tools_by_toolkit: dict[str, list[dict[str, str]]] = {}
    fetch_errors: list[dict[str, str]] = []

    for toolkit in selected_toolkits:
        print(f"Fetching Composio tools for {toolkit}...")
        tools, error = fetch_composio_tools(composio, toolkit=toolkit, limit=args.limit)
        composio_tools_by_toolkit[toolkit] = tools
        if error:
            fetch_errors.append({"toolkit": toolkit, "error": error})
            print(f"  ERROR: {error}")
            continue
        print(f"  OK: {len(tools)} tools")

    custom_tools_by_toolkit, custom_scan_errors = scan_custom_tools()

    selected_set = set(selected_toolkits)
    if args.toolkit or args.integration:
        custom_tools_by_toolkit = {
            toolkit: records
            for toolkit, records in custom_tools_by_toolkit.items()
            if toolkit in selected_set
        }

    known_prefixes = selected_set | set(custom_tools_by_toolkit)

    inventory_toolkits = sorted(
        set(composio_tools_by_toolkit) | set(custom_tools_by_toolkit)
    )

    output_dir = (BACKEND_DIR / args.output_dir).resolve()
    toolkits_dir = output_dir / "toolkits"
    verification_dir = output_dir / "verification"

    generated_at = datetime.now(timezone.utc).isoformat()

    all_available_tools: set[str] = set()
    toolkit_summaries: dict[str, dict[str, Any]] = {}

    for toolkit in inventory_toolkits:
        composio_tools = composio_tools_by_toolkit.get(toolkit, [])
        custom_tools = custom_tools_by_toolkit.get(toolkit, [])

        composio_slugs = sorted({tool["slug"] for tool in composio_tools})
        custom_slugs = sorted({tool["slug"] for tool in custom_tools})
        all_slugs = sorted(set(composio_slugs) | set(custom_slugs))
        all_available_tools.update(all_slugs)

        integration_meta = all_toolkits.get(toolkit)
        summary_payload = {
            "generated_at": generated_at,
            "integration": (
                asdict(integration_meta)
                if integration_meta
                else {
                    "integration_id": None,
                    "integration_name": None,
                    "toolkit": toolkit,
                    "toolkit_version": None,
                }
            ),
            "toolkit": toolkit,
            "counts": {
                "composio": len(composio_slugs),
                "custom": len(custom_slugs),
                "total": len(all_slugs),
            },
            "composio_tools": composio_tools,
            "custom_tools": custom_tools,
            "all_tools": all_slugs,
        }

        toolkit_summaries[toolkit] = summary_payload

        write_json(toolkits_dir / f"{toolkit}.json", summary_payload)
        (toolkits_dir / f"{toolkit}.txt").write_text(
            "\n".join(all_slugs) + ("\n" if all_slugs else ""),
            encoding="utf-8",
        )

    skills_dir = BACKEND_DIR / "app" / "agents" / "skills" / "builtin"
    skill_refs, skill_parse_errors = collect_skill_tool_references(
        skills_dir=skills_dir,
        known_prefixes=known_prefixes,
    )
    unknown_tools = build_unknown_tool_report(skill_refs, all_available_tools)

    write_json(output_dir / "toolkits_summary.json", toolkit_summaries)
    write_json(output_dir / "all_tools.json", sorted(all_available_tools))
    (output_dir / "all_tools.txt").write_text(
        "\n".join(sorted(all_available_tools)) + "\n",
        encoding="utf-8",
    )

    verification_payload = {
        "generated_at": generated_at,
        "toolkits_scanned": inventory_toolkits,
        "counts": {
            "available_tools": len(all_available_tools),
            "skill_references": len(skill_refs),
            "unknown_references": len(unknown_tools),
        },
        "unknown_tools": unknown_tools,
        "fetch_errors": fetch_errors,
        "skill_parse_errors": skill_parse_errors,
        "custom_scan_errors": custom_scan_errors,
    }

    write_json(verification_dir / "report.json", verification_payload)
    write_json(verification_dir / "skill_tool_references.json", skill_refs)
    write_markdown_report(
        path=verification_dir / "report.md",
        generated_at=generated_at,
        toolkits=inventory_toolkits,
        total_available_tools=len(all_available_tools),
        total_references=len(skill_refs),
        unknown_tools=unknown_tools,
        fetch_errors=fetch_errors,
        skill_parse_errors=skill_parse_errors,
        custom_scan_errors=custom_scan_errors,
    )

    print("-" * 80)
    print(f"Output directory: {output_dir}")
    print(f"Available tools: {len(all_available_tools)}")
    print(f"Skill references scanned: {len(skill_refs)}")
    print(f"Unknown references: {len(unknown_tools)}")

    if fetch_errors:
        print(f"Toolkit fetch errors: {len(fetch_errors)}")
    if skill_parse_errors:
        print(f"Skill parse errors: {len(skill_parse_errors)}")
    if custom_scan_errors:
        print(f"Custom scan errors: {len(custom_scan_errors)}")

    if (unknown_tools or fetch_errors or skill_parse_errors or custom_scan_errors) and (
        not args.no_fail
    ):
        print("Result: FAIL (unknown references or errors detected)")
        return 1

    print("Result: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
