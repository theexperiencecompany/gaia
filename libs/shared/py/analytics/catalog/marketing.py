"""Marketing-site and engagement-surface events: navigation, CTAs, blog, founder letter, what's new."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import WebEvent
from shared.py.analytics.catalog.properties import Identifier


class NavigationSidebarClicked(WebEvent):
    """The user clicked one of the app sidebar's top navigation buttons."""

    event: ClassVar[str] = "navigation:sidebar_clicked"
    budget_per_user_day: ClassVar[int] = 200

    destination: Literal["/dashboard", "/todos", "/integrations", "/workflows", "/c"]
    label: Literal["Home", "Tasks", "Integrations", "Workflows", "Chats"]


class NavigationNavbarLinkClicked(WebEvent):
    """The user clicked a plain link in the marketing navbar."""

    event: ClassVar[str] = "navigation:navbar_link_clicked"
    budget_per_user_day: ClassVar[int] = 10

    label: Literal["Pricing", "Docs"]
    href: Literal["/pricing", "https://docs.heygaia.io"]


class NavigationNavbarDropdownOpened(WebEvent):
    """The user hovered a marketing navbar dropdown open."""

    event: ClassVar[str] = "navigation:navbar_dropdown_opened"
    budget_per_user_day: ClassVar[int] = 50

    menu: Literal["product", "resources"]


class NavigationGithubClicked(WebEvent):
    """The user clicked the GitHub link in the marketing navbar."""

    event: ClassVar[str] = "navigation:github_clicked"
    budget_per_user_day: ClassVar[int] = 10

    source: Literal["navbar"]


class NavigationCtaClicked(WebEvent):
    """The user clicked a navigation CTA: login, signup, chat or a desktop download."""

    event: ClassVar[str] = "navigation:cta_clicked"
    budget_per_user_day: ClassVar[int] = 20

    destination: Literal["workos_oauth", "github_releases", "download", "/login", "/signup", "/c"]
    location: Literal["desktop_login_page", "login_modal"] | None = None
    is_logged_in: bool | None = None
    os: Literal["mac", "windows", "linux"] | None = None


class CtaGetStartedClicked(WebEvent):
    """The user clicked a Get Started style call to action on a marketing page."""

    event: ClassVar[str] = "cta:get_started_clicked"
    budget_per_user_day: ClassVar[int] = 10

    location: Literal["chat_demo"] | None = None
    has_small_text: bool | None = None


class BlogArticleViewed(WebEvent):
    """The user opened a blog post."""

    event: ClassVar[str] = "blog:article_viewed"
    budget_per_user_day: ClassVar[int] = 10

    slug: Identifier


class RedditPostViewed(WebEvent):
    """The user opened a Reddit post from a chat tool card."""

    event: ClassVar[str] = "reddit:post_viewed"
    budget_per_user_day: ClassVar[int] = 50

    subreddit: Identifier
    score: int
    num_comments: int
    has_selftext: bool
    has_external_link: bool


class ThanksPageViewed(WebEvent):
    """The user opened the thanks page."""

    event: ClassVar[str] = "thanks:page_viewed"
    budget_per_user_day: ClassVar[int] = 10


class FounderLetterShown(WebEvent):
    """The founder letter envelope rendered; the denominator of its funnel."""

    event: ClassVar[str] = "founder_letter:shown"
    budget_per_user_day: ClassVar[int] = 100

    discount_code: Identifier


class FounderLetterOpened(WebEvent):
    """The user opened the founder letter."""

    event: ClassVar[str] = "founder_letter:opened"
    budget_per_user_day: ClassVar[int] = 10

    first_open: bool
    discount_code: Identifier
    discount_percent: int


class FounderLetterDiscountCtaClicked(WebEvent):
    """The user clicked the founder letter's discount offer."""

    event: ClassVar[str] = "founder_letter:discount_cta_clicked"
    budget_per_user_day: ClassVar[int] = 10

    discount_code: Identifier
    discount_percent: int


class FounderLetterCodeCopied(WebEvent):
    """The user copied the founder letter's discount code."""

    event: ClassVar[str] = "founder_letter:code_copied"
    budget_per_user_day: ClassVar[int] = 50

    discount_code: Identifier


class FounderLetterMeetingClicked(WebEvent):
    """The user clicked the founder letter's book-a-meeting link."""

    event: ClassVar[str] = "founder_letter:meeting_clicked"
    budget_per_user_day: ClassVar[int] = 10


class FounderLetterDismissed(WebEvent):
    """The user dismissed the founder letter for good on this device."""

    event: ClassVar[str] = "founder_letter:dismissed"
    budget_per_user_day: ClassVar[int] = 10

    discount_code: Identifier


class WhatsNewCardShown(WebEvent):
    """The what's-new sidebar card rendered with releases loaded."""

    event: ClassVar[str] = "whats_new:card_shown"
    budget_per_user_day: ClassVar[int] = 100

    unseenCount: int


class WhatsNewCardClicked(WebEvent):
    """The user opened the what's-new modal from the sidebar card or the settings menu."""

    event: ClassVar[str] = "whats_new:card_clicked"
    budget_per_user_day: ClassVar[int] = 10

    source: Literal["sidebar_card", "settings_menu", "settings_menu_view_all"]
    releaseId: Identifier | None = None
    index: int | None = None


class WhatsNewCardDismissed(WebEvent):
    """The user dismissed the what's-new card until the next release."""

    event: ClassVar[str] = "whats_new:card_dismissed"
    budget_per_user_day: ClassVar[int] = 10

    releaseId: Identifier


class WhatsNewModalOpened(WebEvent):
    """The what's-new modal opened and marked every release seen."""

    event: ClassVar[str] = "whats_new:modal_opened"
    budget_per_user_day: ClassVar[int] = 10

    source: Literal["modal"]


class WhatsNewSlideViewed(WebEvent):
    """The user viewed one release in the what's-new modal."""

    event: ClassVar[str] = "whats_new:slide_viewed"
    budget_per_user_day: ClassVar[int] = 10

    releaseId: Identifier
    index: int


class WhatsNewDocsClicked(WebEvent):
    """The user clicked through to the full release notes."""

    event: ClassVar[str] = "whats_new:docs_clicked"
    budget_per_user_day: ClassVar[int] = 50

    releaseId: Identifier


class UseCasesPromptInserted(WebEvent):
    """The user inserted a use-case prompt into the composer; the title is user text, not sent."""

    event: ClassVar[str] = "use_cases:prompt_inserted"
    budget_per_user_day: ClassVar[int] = 50


class UseCasesClicked(WebEvent):
    """The user clicked Add to your GAIA on a use-case page."""

    event: ClassVar[str] = "use_cases:clicked"
    budget_per_user_day: ClassVar[int] = 10

    use_case_id: Identifier


__all__ = [
    "BlogArticleViewed",
    "CtaGetStartedClicked",
    "FounderLetterCodeCopied",
    "FounderLetterDiscountCtaClicked",
    "FounderLetterDismissed",
    "FounderLetterMeetingClicked",
    "FounderLetterOpened",
    "FounderLetterShown",
    "NavigationCtaClicked",
    "NavigationGithubClicked",
    "NavigationNavbarDropdownOpened",
    "NavigationNavbarLinkClicked",
    "NavigationSidebarClicked",
    "RedditPostViewed",
    "ThanksPageViewed",
    "UseCasesClicked",
    "UseCasesPromptInserted",
    "WhatsNewCardClicked",
    "WhatsNewCardDismissed",
    "WhatsNewCardShown",
    "WhatsNewDocsClicked",
    "WhatsNewModalOpened",
    "WhatsNewSlideViewed",
]
