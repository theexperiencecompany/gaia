"""GitHub plan-and-execute subgraph built from reusable configuration."""

import asyncio
from typing import Sequence

from app.agents.prompts.github_node_prompts import (
    ASSIGNEE_MANAGEMENT_PROMPT,
    BRANCH_MANAGEMENT_PROMPT,
    COMMENT_MANAGEMENT_PROMPT,
    COMMIT_OPERATIONS_PROMPT,
    ISSUE_MANAGEMENT_PROMPT,
    LABEL_MANAGEMENT_PROMPT,
    PR_REVIEW_MANAGEMENT_PROMPT,
    PULL_REQUEST_MANAGEMENT_PROMPT,
    REPOSITORY_CONTENT_PROMPT,
    REPOSITORY_MANAGEMENT_PROMPT,
)
from app.config.loggers import langchain_logger as logger
from app.langchain.core.framework.plan_and_execute import (
    OrchestratorNodeConfig,
    OrchestratorSubgraphConfig,
    build_orchestrator_subgraph,
)
from app.services.composio.composio_service import get_composio_service
from langchain_core.language_models import LanguageModelLike
from langgraph.graph.state import CompiledStateGraph

# Pull Request Management Tools
PULL_REQUEST_TOOLS = [
    "GITHUB_CREATE_A_PULL_REQUEST",
    "GITHUB_GET_A_PULL_REQUEST",
    "GITHUB_LIST_PULL_REQUESTS",
    "GITHUB_UPDATE_A_PULL_REQUEST",
    "GITHUB_MERGE_A_PULL_REQUEST",
    "GITHUB_LIST_COMMITS_ON_A_PULL_REQUEST",
    "GITHUB_LIST_PULL_REQUESTS_FILES",
]

# PR Review Management Tools
PR_REVIEW_TOOLS = [
    "GITHUB_REQUEST_REVIEWERS_FOR_A_PULL_REQUEST",
    "GITHUB_REMOVE_REQUESTED_REVIEWERS_FROM_A_PULL_REQUEST",
    "GITHUB_CREATE_A_REVIEW_FOR_A_PULL_REQUEST",
    "GITHUB_SUBMIT_A_REVIEW_FOR_A_PULL_REQUEST",
    "GITHUB_GET_A_REVIEW_FOR_A_PULL_REQUEST",
    "GITHUB_LIST_REVIEWS_FOR_A_PULL_REQUEST",
    "GITHUB_DISMISS_A_REVIEW_FOR_A_PULL_REQUEST",
]

# Issue Management Tools
ISSUE_TOOLS = [
    "GITHUB_CREATE_AN_ISSUE",
    "GITHUB_GET_AN_ISSUE",
    "GITHUB_UPDATE_AN_ISSUE",
    "GITHUB_LIST_REPOSITORY_ISSUES",
    "GITHUB_LOCK_AN_ISSUE",
    "GITHUB_UNLOCK_AN_ISSUE",
    "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS",
]

# Assignee Management Tools
ASSIGNEE_TOOLS = [
    "GITHUB_ADD_ASSIGNEES_TO_AN_ISSUE",
    "GITHUB_REMOVE_ASSIGNEES_FROM_AN_ISSUE",
    "GITHUB_LIST_ASSIGNEES",
    "GITHUB_CHECK_IF_A_USER_CAN_BE_ASSIGNED",
]

# Label Management Tools
LABEL_TOOLS = [
    "GITHUB_CREATE_A_LABEL",
    "GITHUB_GET_A_LABEL",
    "GITHUB_UPDATE_A_LABEL",
    "GITHUB_DELETE_A_LABEL",
    "GITHUB_LIST_LABELS_FOR_A_REPOSITORY",
    "GITHUB_ADD_LABELS_TO_AN_ISSUE",
    "GITHUB_REMOVE_A_LABEL_FROM_AN_ISSUE",
    "GITHUB_LIST_LABELS_FOR_AN_ISSUE",
    "GITHUB_SET_LABELS_FOR_AN_ISSUE",
]

# Comment Management Tools
COMMENT_TOOLS = [
    "GITHUB_CREATE_AN_ISSUE_COMMENT",
    "GITHUB_GET_AN_ISSUE_COMMENT",
    "GITHUB_UPDATE_AN_ISSUE_COMMENT",
    "GITHUB_DELETE_AN_ISSUE_COMMENT",
    "GITHUB_LIST_ISSUE_COMMENTS",
    "GITHUB_CREATE_A_COMMIT_COMMENT",
    "GITHUB_LIST_COMMIT_COMMENTS_FOR_A_REPOSITORY",
    "GITHUB_CREATE_A_REVIEW_COMMENT_FOR_A_PULL_REQUEST",
    "GITHUB_GET_A_REVIEW_COMMENT_FOR_A_PULL_REQUEST",
    "GITHUB_LIST_REVIEW_COMMENTS_ON_A_PULL_REQUEST",
]

# Commit Operations Tools
COMMIT_TOOLS = [
    "GITHUB_GET_A_COMMIT",
    "GITHUB_LIST_COMMITS",
    "GITHUB_COMPARE_TWO_COMMITS",
    "GITHUB_LIST_BRANCHES_FOR_HEAD_COMMIT",
]

# Repository Management Tools
REPOSITORY_MANAGEMENT_TOOLS = [
    "GITHUB_GET_A_REPOSITORY",
    "GITHUB_CREATE_A_REPOSITORY_FOR_THE_AUTHENTICATED_USER",
    "GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER",
    "GITHUB_LIST_ORGANIZATION_REPOSITORIES",
    "GITHUB_CREATE_A_FORK",
    "GITHUB_SEARCH_REPOSITORIES",
    "GITHUB_ADD_A_REPOSITORY_COLLABORATOR",
]

# Repository Content Tools
REPOSITORY_CONTENT_TOOLS = [
    "GITHUB_GET_REPOSITORY_CONTENT",
    "GITHUB_CREATE_OR_UPDATE_FILE_CONTENTS",
    "GITHUB_DELETE_A_FILE",
    "GITHUB_GET_A_REPOSITORY_README",
]

# Branch Management Tools
BRANCH_TOOLS = [
    "GITHUB_GET_A_BRANCH",
    "GITHUB_LIST_BRANCHES",
    "GITHUB_MERGE_A_BRANCH",
    "GITHUB_GET_BRANCH_PROTECTION",
    "GITHUB_UPDATE_BRANCH_PROTECTION",
    "GITHUB_DELETE_BRANCH_PROTECTION",
]

# All tools used in GitHub subgraph (merged from all categories)
GITHUB_TOOLS = (
    PULL_REQUEST_TOOLS
    + PR_REVIEW_TOOLS
    + ISSUE_TOOLS
    + ASSIGNEE_TOOLS
    + LABEL_TOOLS
    + COMMENT_TOOLS
    + COMMIT_TOOLS
    + REPOSITORY_MANAGEMENT_TOOLS
    + REPOSITORY_CONTENT_TOOLS
    + BRANCH_TOOLS
)


async def get_node_configs() -> Sequence[OrchestratorNodeConfig]:
    """Get the list of GitHub node configurations."""
    composio_service = get_composio_service()

    (
        pull_request_tools,
        pr_review_tools,
        issue_tools,
        assignee_tools,
        label_tools,
        comment_tools,
        commit_tools,
        repository_management_tools,
        repository_content_tools,
        branch_tools,
    ) = await asyncio.gather(
        composio_service.get_tools_by_name(PULL_REQUEST_TOOLS),
        composio_service.get_tools_by_name(PR_REVIEW_TOOLS),
        composio_service.get_tools_by_name(ISSUE_TOOLS),
        composio_service.get_tools_by_name(ASSIGNEE_TOOLS),
        composio_service.get_tools_by_name(LABEL_TOOLS),
        composio_service.get_tools_by_name(COMMENT_TOOLS),
        composio_service.get_tools_by_name(COMMIT_TOOLS),
        composio_service.get_tools_by_name(REPOSITORY_MANAGEMENT_TOOLS),
        composio_service.get_tools_by_name(REPOSITORY_CONTENT_TOOLS),
        composio_service.get_tools_by_name(BRANCH_TOOLS),
    )

    return (
        OrchestratorNodeConfig(
            name="pull_request_management",
            description="Create, manage, and merge pull requests with commits and files listing",
            system_prompt=PULL_REQUEST_MANAGEMENT_PROMPT,
            tools=pull_request_tools,
        ),
        OrchestratorNodeConfig(
            name="pr_review_management",
            description="Manage PR reviews and reviewers: request/remove reviewers, create/submit/dismiss reviews",
            system_prompt=PR_REVIEW_MANAGEMENT_PROMPT,
            tools=pr_review_tools,
        ),
        OrchestratorNodeConfig(
            name="issue_management",
            description="Track bugs, features, and tasks: create, update, lock, search issues",
            system_prompt=ISSUE_MANAGEMENT_PROMPT,
            tools=issue_tools,
        ),
        OrchestratorNodeConfig(
            name="assignee_management",
            description="Manage issue/PR assignees: add, remove, list, and check assignee eligibility",
            system_prompt=ASSIGNEE_MANAGEMENT_PROMPT,
            tools=assignee_tools,
        ),
        OrchestratorNodeConfig(
            name="label_management",
            description="Organize with labels: create, update, delete labels, manage label assignments",
            system_prompt=LABEL_MANAGEMENT_PROMPT,
            tools=label_tools,
        ),
        OrchestratorNodeConfig(
            name="comment_management",
            description="Manage comments on issues, PRs, and commits: create, update, delete, list",
            system_prompt=COMMENT_MANAGEMENT_PROMPT,
            tools=comment_tools,
        ),
        OrchestratorNodeConfig(
            name="commit_operations",
            description="Inspect commits: get details, list history, compare commits, find branches",
            system_prompt=COMMIT_OPERATIONS_PROMPT,
            tools=commit_tools,
        ),
        OrchestratorNodeConfig(
            name="repository_management",
            description="Manage repositories: get, create, list, fork, search, add collaborators",
            system_prompt=REPOSITORY_MANAGEMENT_PROMPT,
            tools=repository_management_tools,
        ),
        OrchestratorNodeConfig(
            name="repository_content",
            description="Manage repository files: get content, create/update/delete files, get README",
            system_prompt=REPOSITORY_CONTENT_PROMPT,
            tools=repository_content_tools,
        ),
        OrchestratorNodeConfig(
            name="branch_management",
            description="Manage branches: get, list, merge branches, manage branch protection",
            system_prompt=BRANCH_MANAGEMENT_PROMPT,
            tools=branch_tools,
        ),
    )


async def create_github_subgraph(llm: LanguageModelLike) -> CompiledStateGraph:
    """Factory function to create and compile the GitHub sub-agent subgraph.

    Args:
        llm: Language model to use for the subgraph

    Returns:
        CompiledStateGraph with automatic message filtering and cleanup
    """
    logger.info("Creating GitHub subgraph using plan-and-execute framework")

    config = OrchestratorSubgraphConfig(
        provider_name="GitHub",
        agent_name="github_agent",
        node_configs=await get_node_configs(),
        llm=llm,
    )

    graph = build_orchestrator_subgraph(config)
    logger.info("GitHub subgraph created successfully")

    return graph
