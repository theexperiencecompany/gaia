"""Tests for openui_prompts — spec-driven, independent of implementation details."""

import pytest


def test_suppressed_tools_match_tool_fields():
    from app.models.chat_models import tool_fields
    from app.agents.prompts.openui_prompts import OPENUI_SUPPRESSED_TOOLS

    for tool in tool_fields:
        assert tool in OPENUI_SUPPRESSED_TOOLS, (
            f"{tool} missing from OPENUI_SUPPRESSED_TOOLS"
        )


def test_no_extra_suppressed_tools():
    from app.models.chat_models import tool_fields
    from app.agents.prompts.openui_prompts import OPENUI_SUPPRESSED_TOOLS

    tool_fields_set = set(tool_fields)
    for tool in OPENUI_SUPPRESSED_TOOLS:
        assert tool in tool_fields_set, (
            f"{tool} in OPENUI_SUPPRESSED_TOOLS but not in tool_fields"
        )


def test_instructions_contains_each_suppressed_tool():
    from app.agents.prompts.openui_prompts import (
        OPENUI_SUPPRESSED_TOOLS,
        OPENUI_INSTRUCTIONS,
    )

    for tool in OPENUI_SUPPRESSED_TOOLS:
        assert tool in OPENUI_INSTRUCTIONS, (
            f"Tool {tool} not mentioned in OPENUI_INSTRUCTIONS"
        )


def test_instructions_contains_all_component_names():
    from app.agents.prompts.openui_prompts import OPENUI_INSTRUCTIONS

    components = [
        "DataCard",
        "ResultList",
        "ComparisonTable",
        "StatusCard",
        "ActionCard",
        "TagGroup",
        "FileTree",
        "Accordion",
        "TabsBlock",
        "ProgressList",
        "StatRow",
        "SelectableList",
        "AvatarList",
        "KbdBlock",
        "BarChart",
        "LineChart",
        "AreaChart",
        "PieChart",
        "ScatterChart",
        "RadarChart",
        "GaugeChart",
        "ImageBlock",
        "ImageGallery",
        "VideoBlock",
        "AudioPlayer",
        "MapBlock",
        "CalendarMini",
        "NumberTicker",
        "Carousel",
        "TreeView",
        "Timeline",
        "AlertBanner",
        "Steps",
        "CodeDiff",
        "TextDocument",
    ]
    for name in components:
        assert name in OPENUI_INSTRUCTIONS, (
            f"Component {name} not documented in OPENUI_INSTRUCTIONS"
        )


def test_instructions_is_nonempty_string():
    from app.agents.prompts.openui_prompts import OPENUI_INSTRUCTIONS

    assert isinstance(OPENUI_INSTRUCTIONS, str)
    assert len(OPENUI_INSTRUCTIONS) > 500


def test_suppressed_tools_is_list_of_strings():
    from app.agents.prompts.openui_prompts import OPENUI_SUPPRESSED_TOOLS

    assert isinstance(OPENUI_SUPPRESSED_TOOLS, list)
    for item in OPENUI_SUPPRESSED_TOOLS:
        assert isinstance(item, str)


def test_enable_openui_removed_from_settings():
    """
    Verify ENABLE_OPENUI is not defined in any settings class.
    Uses AST parsing to avoid triggering the module-level get_settings() call
    which requires live Infisical credentials.
    """
    import ast
    import pathlib

    settings_path = (
        pathlib.Path(__file__).parent.parent / "app" / "config" / "settings.py"
    )
    source = settings_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(settings_path))

    for node in ast.walk(tree):
        # Check annotated assignments (e.g. ENABLE_OPENUI: bool = True)
        if isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id == "ENABLE_OPENUI":
                pytest.fail(
                    "ENABLE_OPENUI annotated field found in settings.py — it should have been removed"
                )
        # Check plain assignments (e.g. ENABLE_OPENUI = True)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "ENABLE_OPENUI":
                    pytest.fail(
                        "ENABLE_OPENUI assignment found in settings.py — it should have been removed"
                    )
