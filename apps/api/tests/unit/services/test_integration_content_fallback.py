"""Unit tests for the deterministic marketplace fallback builder.

The fallback is the backend-side safety net behind the LLM inference: pure,
deterministic, and tool-grounded. Every published page must carry copy no
other page has, so the sharpest tests assert cross-page uniqueness directly.
"""

from app.constants.integrations import FAQ_COUNT, HOW_IT_WORKS_COUNT, USE_CASES_COUNT
from app.models.integration_models import StoredIntegrationTool
from app.services.integrations.integration_content_fallback import (
    build_fallback_content,
    build_fallback_description,
    humanize_tool_name,
)


def _tools() -> list[StoredIntegrationTool]:
    return [
        StoredIntegrationTool(
            name="search_papers", description="Search arXiv for papers by keyword."
        ),
        StoredIntegrationTool(name="fetch_pdf", description="Download a paper PDF as text."),
        StoredIntegrationTool(name="list_authors"),
    ]


class TestHumanizeToolName:
    def test_underscores_and_dashes(self):
        assert humanize_tool_name("send_message") == "send message"
        assert humanize_tool_name("get-repo-info") == "get repo info"

    def test_lowercases(self):
        assert humanize_tool_name("FetchPDF") == "fetchpdf"


class TestBuildFallbackDescription:
    def test_names_real_tools(self):
        desc = build_fallback_description("ArXiv", _tools(), "education")

        assert "ArXiv" in desc
        assert "search papers" in desc
        assert "education" in desc

    def test_validator_safe_length(self):
        tools = [StoredIntegrationTool(name=f"tool_{i}_with_a_long_name") for i in range(20)]
        desc = build_fallback_description("X" * 100, tools, "other")

        assert len(desc) <= 500

    def test_handles_no_tools(self):
        desc = build_fallback_description("ArXiv", [], "education")

        assert "ArXiv" in desc


class TestBuildFallbackContent:
    def test_satisfies_cardinality_contract(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "education", "none")

        assert len(content.use_cases) == USE_CASES_COUNT
        assert len(content.how_it_works) == HOW_IT_WORKS_COUNT
        assert len(content.faqs) == FAQ_COUNT

    def test_every_use_case_names_a_real_tool(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "education", "none")
        humanized = {humanize_tool_name(t.name) for t in _tools()}

        for line in content.use_cases:
            assert any(tool in line.lower() for tool in humanized), line

    def test_capability_faq_inventories_top_tools(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "education", "none")
        capability = content.faqs[1]

        assert "search papers" in capability.answer
        assert "fetch pdf" in capability.answer

    def test_tool_specific_faq_uses_real_description(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "education", "none")
        specific = content.faqs[2]

        assert "search papers" in specific.question
        assert "arXiv" in specific.answer

    def test_oauth_connect_copy(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "education", "oauth")

        assert "OAuth consent" in content.how_it_works[0].body
        assert "OAuth consent" in content.faqs[0].answer

    def test_bearer_connect_copy(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "education", "bearer")

        assert "API token" in content.how_it_works[0].body
        assert "API token" in content.faqs[0].answer

    def test_no_auth_connect_copy(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "education", "none")

        assert "No credentials needed" in content.how_it_works[0].body

    def test_unknown_auth_stays_generic(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "education", None)

        assert "if asked" in content.how_it_works[0].body

    def test_deterministic(self):
        first = build_fallback_content("ArXiv", "desc", _tools(), "education", "none")
        second = build_fallback_content("ArXiv", "desc", _tools(), "education", "none")

        assert first == second

    def test_empty_tools_still_satisfies_contract(self):
        content = build_fallback_content("ArXiv", "desc", [], "education", "none")

        assert len(content.use_cases) == USE_CASES_COUNT
        assert len(content.faqs) == FAQ_COUNT

    def test_blank_category_defaults(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "", "none")

        assert "other" in content.how_it_works[2].body


class TestSameCategoryUniqueness:
    """Same-category pages must differ by more than the name."""

    def _other_tools(self) -> list[StoredIntegrationTool]:
        return [
            StoredIntegrationTool(name="grade_quiz", description="Grade a student quiz."),
            StoredIntegrationTool(
                name="assign_homework", description="Assign homework with a due date."
            ),
        ]

    def test_use_cases_share_no_line(self):
        left = build_fallback_content("ArXiv", "desc", _tools(), "education", "none")
        right = build_fallback_content(
            "SchoolHub", "desc", self._other_tools(), "education", "none"
        )

        assert set(left.use_cases).isdisjoint(right.use_cases)

    def test_faq_answers_differ_beyond_name(self):
        left = build_fallback_content("ArXiv", "desc", _tools(), "education", "none")
        right = build_fallback_content(
            "SchoolHub", "desc", self._other_tools(), "education", "none"
        )

        def normalized(faqs):
            # Strip the integration name so a shared template can't pass.
            return [f.answer.replace("ArXiv", "N").replace("SchoolHub", "N") for f in faqs]

        differing = sum(
            a != b for a, b in zip(normalized(left.faqs), normalized(right.faqs), strict=True)
        )
        assert differing >= 3
