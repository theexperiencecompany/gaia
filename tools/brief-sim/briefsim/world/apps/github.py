"""GitHub through Composio: each slug answers with GitHub's own JSON, paginated as GitHub pages it."""

from collections.abc import Callable
from datetime import datetime

from briefsim.world.model import AppState, GithubItem

REPO = "sim-co/gaia"
JsonObject = dict[str, object]


def _stamp(at: datetime | None) -> str | None:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ") if at else None


def issue_url(item: GithubItem) -> str:
    return f"https://github.com/{REPO}/{'pull' if item.kind == 'pr' else 'issues'}/{item.number}"


def _render(item: GithubItem) -> JsonObject:
    rendered: JsonObject = {
        "id": 3_000_000_000 + item.number,
        "number": item.number,
        "title": item.title,
        "state": item.state,
        "html_url": issue_url(item),
        "url": f"https://api.github.com/repos/{REPO}/issues/{item.number}",
        "repository_url": f"https://api.github.com/repos/{REPO}",
        "user": {"login": item.author, "type": "User"},
        "labels": [{"name": label} for label in item.labels],
        "assignees": [{"login": a} for a in item.assignees],
        "assignee": {"login": item.assignees[0]} if item.assignees else None,
        "comments": 0,
        "created_at": _stamp(item.created),
        "updated_at": _stamp(item.updated),
        "closed_at": _stamp(item.closed_at),
        "draft": False,
        "body": "",
    }
    if item.kind == "pr":
        rendered["pull_request"] = {
            "url": f"https://api.github.com/repos/{REPO}/pulls/{item.number}",
            "html_url": issue_url(item),
            "merged_at": None,
        }
        rendered["requested_reviewers"] = [{"login": r} for r in item.reviewers]
    return rendered


def _page(items: list[GithubItem], args: JsonObject, default_size: int) -> list[GithubItem]:
    size = int(str(args.get("per_page") or default_size))
    page = int(str(args.get("page") or 1))
    ordered = sorted(items, key=lambda i: i.updated, reverse=True)
    return ordered[(page - 1) * size : page * size]


def _matches(item: GithubItem, query: str, me: str) -> bool:
    terms = query.lower().split()
    checks = {
        "is:open": item.state == "open",
        "state:open": item.state == "open",
        "is:closed": item.state == "closed",
        "is:pr": item.kind == "pr",
        "type:pr": item.kind == "pr",
        "is:issue": item.kind == "issue",
        "type:issue": item.kind == "issue",
    }
    for term in terms:
        if term in checks and not checks[term]:
            return False
        key, _, value = term.partition(":")
        who = me if value == "@me" else value
        if key == "assignee" and who not in item.assignees:
            return False
        if key in {"review-requested", "user-review-requested"} and who not in item.reviewers:
            return False
        if key == "author" and item.author != who:
            return False
        if key in {"involves", "mentions"} and who not in {
            item.author,
            *item.assignees,
            *item.reviewers,
        }:
            return False
    return True


def _search(state: AppState, args: JsonObject, me: str) -> JsonObject:
    hits = [i for i in state.github.values() if _matches(i, str(args.get("q") or ""), me)]
    return {
        "total_count": len(hits),
        "incomplete_results": False,
        "items": [_render(i) for i in _page(hits, args, 30)],
    }


def _assigned(state: AppState, args: JsonObject, me: str) -> JsonObject:
    wanted = str(args.get("state") or "open")
    hits = [
        i
        for i in state.github.values()
        if me in i.assignees and (wanted == "all" or i.state == wanted)
    ]
    return {"details": [_render(i) for i in _page(hits, args, 30)]}


def _pull_requests(state: AppState, args: JsonObject, me: str) -> JsonObject:
    wanted = str(args.get("state") or "open")
    prs = [
        i
        for i in state.github.values()
        if i.kind == "pr" and (wanted == "all" or i.state == wanted)
    ]
    if args.get("for_authenticated_user"):
        prs = [i for i in prs if me in {i.author, *i.reviewers, *i.assignees}]
    page = _page(prs, args, 20)
    return {"pull_requests": [_render(i) for i in page], "total_count": len(prs)}


def _notifications(state: AppState, args: JsonObject, me: str) -> JsonObject:
    notes = [
        {
            "id": str(90_000 + i.number),
            "unread": True,
            "reason": "review_requested" if me in i.reviewers else "assign",
            "updated_at": _stamp(i.updated),
            "last_read_at": None,
            "subject": {
                "title": i.title,
                "url": f"https://api.github.com/repos/{REPO}/issues/{i.number}",
                "type": "PullRequest" if i.kind == "pr" else "Issue",
            },
            "repository": {"full_name": REPO, "html_url": f"https://github.com/{REPO}"},
        }
        for i in _page(
            [
                i
                for i in state.github.values()
                if i.state == "open" and me in {*i.reviewers, *i.assignees}
            ],
            args,
            50,
        )
    ]
    return {"details": notes}


def _me(_state: AppState, _args: JsonObject, me: str) -> JsonObject:
    return {
        "login": me,
        "id": 59_133_722,
        "name": "Sim Founder",
        "html_url": f"https://github.com/{me}",
    }


HANDLERS: dict[str, Callable[[AppState, JsonObject, str], JsonObject]] = {
    "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS": _search,
    "GITHUB_LIST_ISSUES_ASSIGNED_TO_THE_AUTHENTICATED_USER": _assigned,
    "GITHUB_FIND_PULL_REQUESTS": _pull_requests,
    "GITHUB_LIST_NOTIFICATIONS_FOR_THE_AUTHENTICATED_USER": _notifications,
    "GITHUB_GET_THE_AUTHENTICATED_USER": _me,
}
