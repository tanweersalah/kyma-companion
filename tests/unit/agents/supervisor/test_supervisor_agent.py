import json
from unittest.mock import Mock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agents.common.constants import COMMON, EXIT
from agents.common.state import AgentState, SubTask
from agents.common.utils import filter_messages
from agents.k8s.constants import K8S_AGENT
from agents.kyma.agent import KYMA_AGENT
from agents.supervisor.agent import FINALIZER, SupervisorAgent
from agents.supervisor.state import SupervisorState


class TestSupervisorAgent:

    @pytest.fixture
    def supervisor_agent(self):
        agent = SupervisorAgent(Mock(), [K8S_AGENT, KYMA_AGENT, COMMON, FINALIZER])  # noqa
        agent.supervisor_chain = Mock()
        return agent  # noqa

    @pytest.mark.parametrize(
        "mock_supervisor_chain_invoke_return, subtasks, messages, expected_next, expected_subtasks, expected_error",
        [
            (
                AIMessage(content=f"""{{"next": "{K8S_AGENT}"}}"""),
                [
                    SubTask(
                        description="Task 1", assigned_to=K8S_AGENT, status="pending"
                    ),
                    SubTask(
                        description="Task 2", assigned_to=KYMA_AGENT, status="pending"
                    ),
                ],
                [
                    HumanMessage(content="Test message 1"),
                    AIMessage(content="Test message 2"),
                ],
                K8S_AGENT,
                [
                    SubTask(
                        description="Task 1", assigned_to=K8S_AGENT, status="pending"
                    ),
                    SubTask(
                        description="Task 2", assigned_to=KYMA_AGENT, status="pending"
                    ),
                ],
                None,
            ),
            (
                AIMessage(content=f"""{{"next": "{KYMA_AGENT}"}}"""),
                [
                    SubTask(
                        description="Task 2",
                        assigned_to=KYMA_AGENT,
                        status="in_progress",
                    )
                ],
                [AIMessage(content="Fake message")],
                KYMA_AGENT,
                [
                    SubTask(
                        description="Task 2",
                        assigned_to=KYMA_AGENT,
                        status="in_progress",
                    )
                ],
                None,
            ),
            (
                AIMessage(content=f"""{{"next": "{FINALIZER}"}}"""),
                [
                    SubTask(
                        description="Task 3", assigned_to=K8S_AGENT, status="completed"
                    )
                ],
                [],
                FINALIZER,
                [
                    SubTask(
                        description="Task 3", assigned_to=K8S_AGENT, status="completed"
                    )
                ],
                None,
            ),
            (
                Exception("Test error"),
                [
                    SubTask(
                        description="Task 4", assigned_to=KYMA_AGENT, status="pending"
                    )
                ],
                [HumanMessage(content="Error test")],
                None,
                [
                    SubTask(
                        description="Task 4", assigned_to=KYMA_AGENT, status="pending"
                    )
                ],
                "Sorry, I encountered an error while processing the request. Error: Test error",
            ),
        ],
    )
    @patch("agents.k8s.agent.get_logger", Mock())
    def test_agent_node(
        self,
        supervisor_agent,
        mock_supervisor_chain_invoke_return,
        subtasks,
        messages,
        expected_next,
        expected_subtasks,
        expected_error,
    ):
        # Setup
        if isinstance(mock_supervisor_chain_invoke_return, Exception):
            supervisor_agent.supervisor_chain.invoke = Mock(
                side_effect=mock_supervisor_chain_invoke_return
            )
        else:
            supervisor_agent.supervisor_chain.invoke = Mock(
                return_value=mock_supervisor_chain_invoke_return
            )

        state = AgentState(messages=messages, subtasks=subtasks)

        # Execute
        route_node = supervisor_agent._route
        result = route_node(state)

        # Assert
        supervisor_agent.supervisor_chain.invoke.assert_called_once_with(
            input={
                "messages": filter_messages(messages),
                "subtasks": json.dumps([subtask.__dict__ for subtask in subtasks]),
            }
        )

        if expected_error:
            assert result["messages"][0].content == expected_error
        else:
            assert result["next"] == expected_next
            assert "error" not in result

    @pytest.mark.parametrize(
        "description, input_query, conversation_messages, final_response_content, expected_output, expected_error",
        [
            (
                "Generates final response successfully",
                "How do I deploy a Kyma function?",
                [
                    HumanMessage(content="How do I deploy a Kyma function?"),
                    AIMessage(
                        content="To deploy a Kyma function, you need to...",
                        name="KymaAgent",
                    ),
                    AIMessage(
                        content="In Kubernetes, deployment involves...",
                        name="KubernetesAgent",
                    ),
                ],
                "To deploy a Kyma function, follow these steps: 1. Create a function file. "
                "2. Use the Kyma CLI to deploy. 3. Verify the deployment in the Kyma dashboard.",
                {
                    'messages': [
                        AIMessage(
                            content='To deploy a Kyma function, follow these steps: '
                                    '1. Create a function file. '
                                    '2. Use the Kyma CLI to deploy. '
                                    '3. Verify the deployment in the Kyma dashboard.',
                            name='Finalizer'
                        )
                    ],
                    'next': '__end__'
                },
                None,
            ),
            (
                "Generates empty final response",
                "What is Kubernetes?",
                [
                    HumanMessage(content="What is Kubernetes?"),
                    AIMessage(
                        content="Kubernetes is a container orchestration platform.",
                        name="KubernetesAgent",
                    ),
                ],
                "",
                {
                    'messages': [
                        AIMessage(
                            content='',
                            name='Finalizer'
                        )
                    ],
                    'next': '__end__'
                },
                None,
            ),
            (
                "Handles exception during final response generation",
                "What is Kubernetes?",
                [
                    HumanMessage(content="What is Kubernetes?"),
                    AIMessage(
                        content="Kubernetes is a container orchestration platform.",
                        name="KubernetesAgent",
                    ),
                ],
                None,
                {
                    'messages': [
                        AIMessage(
                            content='Sorry, I encountered an error while processing the request. '
                                    'Error: Error in finalizer node: Test error',
                            name='Finalizer')
                    ]
                },
                "Error in finalizer node: Test error",
            ),
        ],
    )
    @patch("agents.k8s.agent.get_logger", Mock())
    def test_agent_generate_final_response(
        self,
        supervisor_agent,
        description,
        input_query,
        conversation_messages,
        final_response_content,
        expected_output,
        expected_error,
    ):
        state = SupervisorState(messages=conversation_messages)

        mock_final_response_chain = Mock()
        if expected_error:
            mock_final_response_chain.invoke.side_effect = Exception(expected_error)
        else:
            mock_final_response_chain.invoke.return_value.content = (
                final_response_content
            )

        with patch.object(
            supervisor_agent, "_final_response_chain", return_value=mock_final_response_chain
        ):
            result = supervisor_agent._generate_final_response(state)

        assert result == expected_output
        mock_final_response_chain.invoke.assert_called_once_with(
            {"messages": conversation_messages}
        )
