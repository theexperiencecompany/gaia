"""Unit tests for the deterministic marketplace fallback builder.

The fallback is the backend-side safety net behind the LLM inference: pure,
deterministic, and tool-grounded. Every published page must carry copy no
other page has, so the sharpest tests assert cross-page uniqueness directly.
"""

from app.constants.integrations import FAQ_COUNT, HOW_IT_WORKS_COUNT, USE_CASES_COUNT
from app.models.integration_models import StoredIntegrationTool
from app.services.integrations.integration_content_fallback import (
    _first_sentence,
    build_fallback_content,
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


class TestFirstSentence:
    """Exact-output tests: every separator, trim, and boundary branch."""

    def test_collapses_whitespace(self):
        assert _first_sentence("  hello    world  ") == "hello world"

    def test_none_and_blank_is_none(self):
        assert _first_sentence(None) is None
        assert _first_sentence("") is None
        assert _first_sentence("   ") is None

    def test_period_separator(self):
        assert _first_sentence("Alpha. Beta") == "Alpha."

    def test_exclamation_separator(self):
        assert _first_sentence("Wow! Really works") == "Wow."

    def test_question_separator(self):
        assert _first_sentence("Really? Yes indeed") == "Really."

    def test_strips_trailing_punctuation_before_separator(self):
        assert _first_sentence("Really?! Yes indeed") == "Really."

    def test_multi_separator_takes_first(self):
        assert _first_sentence("One. Two. Three") == "One."

    def test_sentence_ending_in_x_keeps_it(self):
        assert _first_sentence("MatrixX. Next part here") == "MatrixX."

    def test_x_before_comma_survives_trim(self):
        text = "k " * 65 + "AB QZX, " + "tail words " * 30

        assert _first_sentence(text) == ("k " * 65 + "AB QZX") + "…"

    def test_explicit_max_len(self):
        assert _first_sentence("word " * 40, max_len=120) == ("word " * 23).strip() + "…"

    def test_trim_boundary_space(self):
        prefix = "k " * 45 + "z" * 47
        text = prefix + "X " + "tail words " * 30

        assert _first_sentence(text) == (prefix + "X") + "…"

    def test_no_space_trim_uses_hard_cut(self):
        assert _first_sentence("x" * 300) == "x" * 139 + "…"

    def test_single_sentence_kept_whole(self):
        assert _first_sentence("Hello world.") == "Hello world."

    def test_exact_boundary_length_kept(self):
        assert _first_sentence("x" * 140) == "x" * 140

    def test_trims_at_word_boundary_with_ellipsis(self):
        text = "word " * 60

        assert _first_sentence(text) == ("word " * 27).strip() + "…"

    def test_trim_strips_trailing_comma(self):
        text = "k " * 67 + "zz, " + "tail words " * 30

        assert _first_sentence(text) == ("k " * 67 + "zz") + "…"


def _two_tools() -> list[StoredIntegrationTool]:
    return [
        StoredIntegrationTool(
            name="search_papers", description="Search arXiv for papers by keyword."
        ),
        StoredIntegrationTool(name="fetch_pdf", description="Download a paper PDF as text."),
    ]


def _three_tools_no_first_description() -> list[StoredIntegrationTool]:
    return [
        StoredIntegrationTool(name="search_papers"),
        StoredIntegrationTool(name="fetch_pdf", description="Download a paper PDF as text."),
        StoredIntegrationTool(name="list_authors", description="List the authors."),
    ]


def _five_tools() -> list[StoredIntegrationTool]:
    # The first tool carries no description so the tool-specific FAQ exercises
    # the inventory ("N more") branch instead of the description-snippet one.
    return [
        StoredIntegrationTool(name="search_papers"),
        StoredIntegrationTool(name="fetch_pdf", description="Download a paper PDF as text."),
        StoredIntegrationTool(name="list_authors", description="List the authors."),
        StoredIntegrationTool(name="save_library", description="Save to the library."),
        StoredIntegrationTool(name="share_digest", description="Share a digest."),
    ]


class TestExactFallbackContent:
    """Pin the deterministic copy verbatim: every literal is the contract."""

    def test_exact_use_cases(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "education", "none")

        assert content.use_cases == [
            "Ask GAIA to search papers in ArXiv — Search arXiv for papers by keyword.",
            "Tell GAIA to fetch pdf in ArXiv — Download a paper PDF as text.",
            "Have GAIA list authors in ArXiv with a plain-English instruction",
            "Let GAIA search papers in ArXiv with a plain-English instruction",
            "Get GAIA to fetch pdf in ArXiv with a plain-English instruction",
        ]
        assert all("ArXiv" in line for line in content.use_cases)

    def test_duplicate_descriptions_share_no_line(self):
        tools = [
            StoredIntegrationTool(name="do_this", description="Do things well."),
            StoredIntegrationTool(name="do_that", description="Do things well."),
        ]
        content = build_fallback_content("ArXiv", "desc", tools, "education", "none")

        assert "Do things well." in content.use_cases[0]
        assert content.use_cases[1].endswith("with a plain-English instruction")

    def test_exact_how_it_works(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "education", "oauth")
        steps = content.how_it_works

        assert steps[0].title == "Connect ArXiv to GAIA"
        assert steps[0].body == (
            'Open the GAIA Marketplace, find ArXiv, and click "Add to your GAIA". '
            "Approve access on the OAuth consent screen — "
            "you're connected in under two minutes. "
            "Once authorised, all 3 ArXiv actions are ready to use."
        )
        assert steps[1].title == "Tell GAIA what to do in plain English"
        assert steps[1].body == (
            'Describe the outcome — for example "search papers and show me the '
            'result" or "run fetch pdf every morning". GAIA maps it to the '
            "right ArXiv actions and reports back in chat."
        )
        assert steps[2].title == "GAIA runs ArXiv on autopilot"
        assert steps[2].body == (
            "Schedule it — a daily ArXiv briefing or an alert when search papers "
            "returns something new — and GAIA runs it around the clock "
            "across your education stack."
        )

    def test_exact_bearer_connect_copy(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "education", "bearer")

        assert "Paste your ArXiv API token when asked" in content.how_it_works[0].body

    def test_exact_capability_answer(self):
        content = build_fallback_content(
            "ArXiv", "A handy tool for research work", _tools(), "education", "none"
        )

        assert content.faqs[1].answer == (
            "A handy tool for research work GAIA exposes all 3 ArXiv actions — "
            "including search papers, fetch pdf, list authors — so you can run any "
            "of them by describing it in plain English. It can also combine ArXiv "
            "with your other tools, for example summarising ArXiv activity in a "
            "scheduled daily briefing. "
            "For example: Search arXiv for papers by keyword."
        )

    def test_exact_tool_answer(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "education", "none")

        assert content.faqs[2].answer == (
            "Search arXiv for papers by keyword. Just describe it in plain English — "
            'for example "search papers and show me the result" — and GAIA calls '
            "the action for you."
        )

    def test_many_tools_list_remaining_count(self):
        content = build_fallback_content("ArXiv", "desc", _five_tools(), "education", "none")

        assert content.faqs[2].answer == (
            "Anything the available ArXiv actions support — "
            "search papers, fetch pdf, list authors and 2 more — combined with "
            "your email, calendar, and tasks. Describe the outcome once and GAIA "
            "runs it on schedule."
        )

    def test_already_mentioned_description_not_prepended(self):
        content = build_fallback_content(
            "ArXiv", "GAIA exposes all 3 ArXiv actions", _tools(), "education", "none"
        )

        assert content.faqs[1].answer.startswith("GAIA exposes all 3 ArXiv actions —")

    def test_connect_faq_names_integration(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "education", "none")

        assert "find ArXiv" in content.faqs[0].answer

    def test_free_faq_names_integration(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "education", "none")

        assert "like ArXiv are" in content.faqs[3].answer

    def test_no_named_tools_yields_no_content(self):
        assert build_fallback_content("ArXiv", "desc", [], "education", "none") is None
        blank = [StoredIntegrationTool(name="  ")]
        assert build_fallback_content("ArXiv", "desc", blank, "education", "none") is None

    def test_long_description_trims_at_120(self):
        description = "word " * 40
        content = build_fallback_content("ArXiv", description, _tools(), "education", "none")

        assert content.faqs[1].answer.startswith(
            ("word " * 23).strip() + "… GAIA exposes all 3 ArXiv actions"
        )

    def test_spaceless_prefix_trims_to_hard_cut(self):
        description = "x" * 150 + " tail here"
        content = build_fallback_content("ArXiv", description, _tools(), "education", "none")

        assert content.faqs[1].answer.startswith("x" * 119 + "… GAIA exposes")

    def test_five_tool_description_lists_three(self):
        content = build_fallback_content("ArXiv", "desc", _five_tools(), "education", "none")

        assert content.faqs[1].answer.startswith(
            "GAIA exposes all 5 ArXiv actions — including search papers, fetch pdf, list authors —"
        )

    def test_two_tool_counts(self):
        content = build_fallback_content("ArXiv", "desc", _two_tools(), "education", "none")

        assert "all 2 ArXiv actions are ready" in content.how_it_works[0].body
        assert content.faqs[1].answer.startswith(
            "GAIA exposes all 2 ArXiv actions — including search papers, fetch pdf —"
        )
        assert "run fetch pdf every morning" in content.how_it_works[1].body

    def test_three_tools_without_first_description_uses_else_answer(self):
        content = build_fallback_content(
            "ArXiv", "desc", _three_tools_no_first_description(), "education", "none"
        )

        assert content.faqs[2].answer == (
            "Describe the outcome in plain English — for example "
            '"search papers and report back" — and GAIA runs the ArXiv '
            "education actions for you."
        )

    def test_blank_category_exact_body(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "", "none")

        assert content.how_it_works[2].body == (
            "Schedule it — a daily ArXiv briefing or an alert when search papers "
            "returns something new — and GAIA runs it around the clock "
            "across your other stack."
        )

    def test_whitespace_category_defaults(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "   ", "none")

        assert " your other stack" in content.how_it_works[2].body

    def test_how_it_works_names_integration(self):
        content = build_fallback_content("ArXiv", "desc", _tools(), "education", "none")
        steps = content.how_it_works

        assert "ArXiv" in steps[0].title
        assert "find ArXiv" in steps[0].body
        assert "ArXiv" in steps[2].title


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
