from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from langchain_core.embeddings import Embeddings
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    RemoveMessage,
    ToolMessage,
)
from langchain_core.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder,
    SystemMessagePromptTemplate,
)
from langchain_core.runnables import RunnableLambda
from langgraph.graph.graph import CompiledGraph

from agents.common.agent import BaseAgent
from agents.common.constants import FINALIZER, MESSAGES
from agents.common.state import BaseAgentState, SubTask, SubTaskStatus
from agents.k8s.tools.logs import fetch_pod_logs_tool
from agents.k8s.tools.query import k8s_query_tool
from services.k8s import IK8sClient
from utils.models.factory import IModel, ModelType


class TestAgentState(BaseAgentState):
    """Test agent state class."""

    k8s_client: IK8sClient | None = None  # Make k8s_client optional with default None


class TestAgent(BaseAgent):
    """Concrete implementation of BaseAgent for testing."""

    def __init__(self, model: IModel):
        super().__init__(
            name="TestAgent",
            model=model,
            tools=[k8s_query_tool, fetch_pod_logs_tool],
            system_prompt="You are a test agent",
            state_class=TestAgentState,
        )


@pytest.fixture
def mock_models():
    return {
        ModelType.GPT4O: Mock(spec=IModel),
        ModelType.TEXT_EMBEDDING_3_LARGE: Mock(spec=Embeddings),
    }


@pytest.fixture
def mock_graph():
    return Mock()


@pytest.fixture
def mock_config():
    return Mock()


@pytest.fixture
def mock_k8s_client():
    return Mock(spec=IK8sClient)


class TestBaseAgent:
    """Test base agent class."""

    def test_name(self, mock_models):
        agent = TestAgent(mock_models[ModelType.GPT4O])
        assert agent.name == "TestAgent"

    def test_agent_init(self, mock_models):
        agent = TestAgent(mock_models[ModelType.GPT4O])
        assert agent.tools == [k8s_query_tool, fetch_pod_logs_tool]
        assert agent.model == mock_models[ModelType.GPT4O]
        assert agent.graph is not None
        assert agent.chain is not None

    def test_agent_node(self, mock_models):
        # Given
        agent = TestAgent(mock_models[ModelType.GPT4O])

        # When
        result = agent.agent_node()

        # Then
        assert result is not None
        assert isinstance(result, CompiledGraph)

    def test_create_chain(self, mock_models):
        # Given
        agent = TestAgent(mock_models[ModelType.GPT4O])

        # When
        chain = agent._create_chain("You are a test agent")

        # Then
        assert chain is not None
        assert len(chain.steps) == 2  # noqa

        # check step 1: chat prompt
        assert isinstance(chain.steps[0], ChatPromptTemplate) == True  # noqa
        assert len(chain.steps[0].messages) == 3  # noqa
        # check step 1 > message 1
        assert isinstance(chain.steps[0].messages[0], SystemMessagePromptTemplate)
        assert chain.steps[0].messages[0].prompt.template == "You are a test agent"
        # check step 1 > message 2
        assert isinstance(chain.steps[0].messages[1], MessagesPlaceholder)
        # check step 1 > message 3
        assert isinstance(chain.steps[0].messages[2], HumanMessagePromptTemplate)

        # check step 2: model
        assert isinstance(chain.steps[1], RunnableLambda)

    def test_build_graph(self, mock_models):
        # Given
        agent = TestAgent(mock_models[ModelType.GPT4O])

        # When
        graph = agent._build_graph(TestAgentState)

        # Then
        # check nodes.
        assert len(graph.nodes) == 5  # noqa
        assert graph.nodes.keys() == {
            "__start__",
            "subtask_selector",
            "agent",
            "tools",
            "finalizer",
        }
        # check edges.
        assert len(graph.builder.edges) == 3  # noqa
        assert graph.builder.edges == {
            ("tools", "agent"),
            ("__start__", "subtask_selector"),
            ("finalizer", "__end__"),
        }
        # check conditional edges.
        assert len(graph.builder.branches) == 2  # noqa

    @pytest.mark.parametrize(
        "given_state, expected_output",
        [
            # Test case when there is a subtask assigned to the agent.
            (
                TestAgentState(
                    my_task=None,
                    is_last_step=False,
                    messages=[],
                    subtasks=[
                        SubTask(description="test", assigned_to=FINALIZER),
                        SubTask(description="test", assigned_to="TestAgent"),
                    ],
                    k8s_client=Mock(spec=IK8sClient),
                ),
                {
                    "my_task": SubTask(description="test", assigned_to="TestAgent"),
                },
            ),
            # Test case when there is no subtask assigned to the agent.
            (
                TestAgentState(
                    my_task=None,
                    is_last_step=False,
                    messages=[],
                    subtasks=[
                        SubTask(description="test", assigned_to=FINALIZER),
                    ],
                    k8s_client=Mock(spec=IK8sClient),
                ),
                {
                    "is_last_step": True,
                    MESSAGES: [
                        AIMessage(
                            content="All my subtasks are already completed.",
                            name="TestAgent",
                        )
                    ],
                },
            ),
            # Test case when there all subtasks assigned to the agent are completed.
            (
                TestAgentState(
                    my_task=None,
                    is_last_step=False,
                    messages=[],
                    subtasks=[
                        SubTask(description="test", assigned_to=FINALIZER),
                        SubTask(
                            description="test1",
                            assigned_to="TestAgent",
                            status=SubTaskStatus.COMPLETED,
                        ),
                        SubTask(
                            description="test2",
                            assigned_to="TestAgent",
                            status=SubTaskStatus.COMPLETED,
                        ),
                    ],
                    k8s_client=Mock(spec=IK8sClient),
                ),
                {
                    "is_last_step": True,
                    MESSAGES: [
                        AIMessage(
                            content="All my subtasks are already completed.",
                            name="TestAgent",
                        )
                    ],
                },
            ),
        ],
    )
    def test_subtask_selector_node(
        self, mock_models, given_state: TestAgentState, expected_output: dict
    ):
        agent = TestAgent(mock_models[ModelType.GPT4O])
        assert agent._subtask_selector_node(given_state) == expected_output

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "given_invoke_response, given_invoke_error, given_state, expected_output, expected_invoke_inputs",
        [
            # Test case when the model returns a response.
            (
                AIMessage(content="This is a dummy response from model."),
                None,
                TestAgentState(
                    my_task=SubTask(description="test task 1", assigned_to="TestAgent"),
                    is_last_step=False,
                    messages=[AIMessage(content="dummy message 1")],
                    k8s_client=Mock(spec=IK8sClient),
                ),
                {
                    MESSAGES: [
                        AIMessage(
                            content="This is a dummy response from model.",
                            additional_kwargs={"owner": "TestAgent"},
                        )
                    ]
                },
                {
                    "messages": [AIMessage(content="dummy message 1")],
                    "query": "test task 1",
                },
            ),
            # Test case when the model raises an exception.
            (
                None,
                ValueError("This is a dummy exception from model."),
                TestAgentState(
                    my_task=SubTask(description="test task 1", assigned_to="TestAgent"),
                    is_last_step=False,
                    messages=[AIMessage(content="dummy message 1")],
                    k8s_client=Mock(spec=IK8sClient),
                ),
                {
                    MESSAGES: [
                        AIMessage(
                            content="Sorry, I encountered an error while processing the request. "
                            "Error: This is a dummy exception from model.",
                            name="TestAgent",
                        )
                    ]
                },
                {
                    "messages": [AIMessage(content="dummy message 1")],
                    "query": "test task 1",
                },
            ),
            # Test case when the recursive limit is reached.
            (
                AIMessage(
                    content="This is a dummy response from model.",
                    tool_calls=[
                        {
                            "name": "test_tool",
                            "args": {"arg1": "value1"},
                            "id": "test_id",
                        }
                    ],
                ),
                None,
                TestAgentState(
                    my_task=SubTask(description="test task 1", assigned_to="TestAgent"),
                    is_last_step=True,
                    messages=[AIMessage(content="dummy message 1")],
                    k8s_client=Mock(spec=IK8sClient),
                ),
                {
                    MESSAGES: [
                        AIMessage(
                            content="Sorry, I need more steps to process the request.",
                            name="TestAgent",
                        )
                    ]
                },
                {
                    "messages": [AIMessage(content="dummy message 1")],
                    "query": "test task 1",
                },
            ),
        ],
    )
    async def test_model_node(
        self,
        mock_models,
        mock_config,
        given_invoke_response: BaseMessage,
        given_invoke_error: Exception,
        given_state: TestAgentState,
        expected_output: dict,
        expected_invoke_inputs: dict,
    ):
        # Given
        agent = TestAgent(mock_models[ModelType.GPT4O])
        agent.chain = AsyncMock()
        agent._invoke_chain = AsyncMock()
        if given_invoke_response is not None:
            agent._invoke_chain.return_value = given_invoke_response
        elif given_invoke_error is not None:
            agent._invoke_chain.side_effect = given_invoke_error

        # When
        result = await agent._model_node(given_state, mock_config)
        assert result == expected_output

        # Then
        if expected_invoke_inputs != {}:
            agent._invoke_chain.assert_called_once_with(given_state, mock_config)

    @pytest.mark.parametrize(
        "given_message, expected_output",
        [
            # Test case when the AIMessage have None additional_kwargs.
            (
                AIMessage(content="dummy"),
                False,
            ),
            # Test case when the AIMessage have no owner key in additional_kwargs.
            (
                AIMessage(content="dummy", additional_kwargs={"key": "value"}),
                False,
            ),
            # Test case when the AIMessage have different owner in additional_kwargs.
            (
                AIMessage(
                    content="dummy",
                    additional_kwargs={"owner": "value"},
                    tool_calls=[
                        {
                            "args": {
                                "uri": "/api/v1/namespaces/default/secrets/test-user1-admin"
                            },
                            "id": "call_JZM1Sbccr9nQ49KLT21qG4W6",
                            "name": "k8s_query_tool",
                            "type": "tool_call",
                        }
                    ],
                ),
                False,
            ),
            # Test case when the AIMessage have TestAgent owner in additional_kwargs.
            (
                AIMessage(
                    content="dummy",
                    additional_kwargs={"owner": "TestAgent"},
                    tool_calls=[
                        {
                            "args": {
                                "uri": "/api/v1/namespaces/default/secrets/test-user1-admin"
                            },
                            "id": "call_JZM1Sbccr9nQ49KLT21qG4W6",
                            "name": "k8s_query_tool",
                            "type": "tool_call",
                        }
                    ],
                ),
                True,
            ),
            # Test case when the ToolMessage have non-relevant tool name.
            (
                ToolMessage(
                    content="dummy",
                    name="google_query_tool",
                    tool_call_id="call_JZM1Sbccr9nQ49KLT21qG4W6",
                ),
                False,
            ),
            # Test case when the ToolMessage have relevant tool name.
            (
                ToolMessage(
                    content="dummy",
                    name="k8s_query_tool",
                    tool_call_id="call_JZM1Sbccr9nQ49KLT21qG4W6",
                ),
                True,
            ),
            # Test case when the ToolMessage have relevant tool name.
            (
                ToolMessage(
                    content="dummy",
                    name="fetch_pod_logs_tool",
                    tool_call_id="call_JZM1Sbccr9nQ49KLT21qG4W6",
                ),
                True,
            ),
        ],
    )
    def test_is_internal_message(
        self,
        mock_models,
        given_message: BaseMessage,
        expected_output: bool,
    ):
        # Given
        agent = TestAgent(mock_models[ModelType.GPT4O])

        # When
        assert agent.is_internal_message(given_message) == expected_output

    @pytest.mark.parametrize(
        "given_state, expected_output",
        [
            # Test case when the subtask is not completed and tool call messages exists.
            (
                TestAgentState(
                    my_task=SubTask(
                        description="test task 1",
                        assigned_to="TestAgent",
                        status=SubTaskStatus.PENDING,
                    ),
                    is_last_step=False,
                    messages=[
                        AIMessage(
                            id="1",
                            content="dummy",
                            additional_kwargs={"owner": "TestAgent"},
                            tool_calls=[
                                {
                                    "args": {
                                        "uri": "/api/v1/namespaces/default/secrets/test-user1-admin"
                                    },
                                    "id": "call_JZM1Sbccr9nQ49KLT21qG4W6",
                                    "name": "k8s_query_tool",
                                    "type": "tool_call",
                                }
                            ],
                        ),
                        ToolMessage(
                            id="2",
                            content="dummy",
                            name="k8s_query_tool",
                            tool_call_id="call_JZM1Sbccr9nQ49KLT21qG4W6",
                        ),
                        AIMessage(id="3", content="final answer"),
                    ],
                    k8s_client=Mock(spec=IK8sClient),
                ),
                {
                    "messages": [
                        RemoveMessage(content="", id="1"),
                        RemoveMessage(content="", id="2"),
                    ],
                    "my_task": None,
                },
            ),
        ],
    )
    def test_finalizer_node(
        self,
        mock_models,
        given_state: TestAgentState,
        expected_output: dict,
    ):
        # Given
        agent = TestAgent(mock_models[ModelType.GPT4O])
        agent.chain = MagicMock()

        # When
        assert agent._finalizer_node(given_state, mock_config) == expected_output
        assert given_state.my_task.status == SubTaskStatus.COMPLETED