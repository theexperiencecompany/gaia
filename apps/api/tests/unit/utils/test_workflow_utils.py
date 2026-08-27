"""Config extraction helpers in workflow_utils: fail loud when the key is absent."""

from langchain_core.runnables.config import RunnableConfig
import pytest

from app.utils.workflow_utils import WorkflowConfigError, get_user_id, get_workflow_id


@pytest.mark.unit
class TestGetWorkflowId:
    def test_returns_the_configurable_workflow_id(self) -> None:
        config: RunnableConfig = {"configurable": {"workflow_id": "wf_9f674ef3558f"}}
        assert get_workflow_id(config) == "wf_9f674ef3558f"

    def test_a_config_without_a_workflow_id_says_workflow_runs_only(self) -> None:
        # The playbook tools are bound to the executor in chat runs too, so the
        # error is what the model reads when it calls one outside a workflow.
        config: RunnableConfig = {"configurable": {"user_id": "u1"}}
        with pytest.raises(WorkflowConfigError, match="workflow run"):
            get_workflow_id(config)

    def test_a_config_with_no_configurable_raises_the_same_error(self) -> None:
        with pytest.raises(WorkflowConfigError, match="workflow run"):
            get_workflow_id({})

    def test_an_empty_workflow_id_is_treated_as_missing(self) -> None:
        config: RunnableConfig = {"configurable": {"workflow_id": ""}}
        with pytest.raises(WorkflowConfigError, match="workflow run"):
            get_workflow_id(config)


@pytest.mark.unit
class TestGetUserId:
    def test_returns_the_configurable_user_id(self) -> None:
        config: RunnableConfig = {"configurable": {"user_id": "u1"}}
        assert get_user_id(config) == "u1"

    def test_a_config_without_a_user_raises(self) -> None:
        with pytest.raises(WorkflowConfigError, match="authentication"):
            get_user_id({"configurable": {}})
