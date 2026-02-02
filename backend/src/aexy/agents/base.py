"""Base agent class for LangGraph-based AI agents."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Annotated, TypedDict, Sequence
import operator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.language_models import BaseChatModel
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from aexy.core.config import settings


class AgentState(TypedDict):
    """State for agent execution."""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    record_id: str | None
    record_data: dict
    context: dict
    steps: Annotated[list[dict], operator.add]  # Accumulate steps like messages
    final_output: dict | None
    error: str | None


class BaseAgent(ABC):
    """Base class for LangGraph-based agents."""

    name: str = "base_agent"
    description: str = "Base agent class"
    default_model: str = "claude-3-sonnet-20240229"

    def __init__(
        self,
        model: str | None = None,
        llm_provider: str = "claude",
        max_iterations: int = 10,
        timeout_seconds: int = 300,
    ):
        self.model_name = model or self.default_model
        self.llm_provider = llm_provider
        self.max_iterations = max_iterations
        self.timeout_seconds = timeout_seconds
        self._llm: BaseChatModel | None = None
        self._tools: list[BaseTool] = []
        self._graph: StateGraph | None = None

    @property
    def llm(self) -> BaseChatModel:
        """Get the LLM instance based on provider."""
        if self._llm is None:
            if self.llm_provider == "gemini":
                self._llm = ChatGoogleGenerativeAI(
                    model=self.model_name if self.model_name.startswith("gemini") else "gemini-1.5-pro",
                    google_api_key=settings.llm.gemini_api_key,
                    max_output_tokens=4096,
                )
            else:
                # Default to Claude
                self._llm = ChatAnthropic(
                    model=self.model_name,
                    anthropic_api_key=settings.llm.anthropic_api_key,
                    max_tokens=4096,
                )
        return self._llm

    @property
    @abstractmethod
    def tools(self) -> list[BaseTool]:
        """Define the tools available to this agent."""
        pass

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Define the system prompt for this agent."""
        pass

    @property
    def goal(self) -> str:
        """Define the agent's goal."""
        return self.description

    def _get_llm_with_tools(self) -> BaseChatModel:
        """Get LLM bound with tools."""
        if self.tools:
            return self.llm.bind_tools(self.tools)
        return self.llm

    def _should_continue(self, state: AgentState) -> str:
        """Determine if agent should continue or end."""
        messages = state["messages"]

        # Check iteration limit
        if len(state.get("steps", [])) >= self.max_iterations:
            return "end"

        # Check for error
        if state.get("error"):
            return "end"

        # Check if last message has tool calls
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                return "tools"

        return "end"

    def _call_model(self, state: AgentState) -> dict:
        """Call the LLM with current state."""
        messages = state["messages"]
        llm = self._get_llm_with_tools()

        try:
            response = llm.invoke(messages)

            # Record step
            step = {
                "type": "llm_call",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "input_messages": len(messages),
                "has_tool_calls": bool(getattr(response, "tool_calls", None)),
            }

            return {
                "messages": [response],
                "steps": [step],
            }
        except Exception as e:
            return {
                "error": str(e),
                "steps": [{
                    "type": "error",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": str(e),
                }],
            }

    async def _process_tools(self, state: AgentState) -> dict:
        """Process tool calls asynchronously."""
        messages = state["messages"]
        last_message = messages[-1]

        if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
            return {"messages": []}

        tool_node = ToolNode(self.tools)
        try:
            # Use ainvoke for async tool execution
            result = await tool_node.ainvoke({"messages": [last_message]})
            result_messages = result.get("messages", [])

            # Record tool steps with outputs
            steps = []
            for i, tool_call in enumerate(last_message.tool_calls):
                tool_name = tool_call.get("name", "unknown")
                tool_args = tool_call.get("args", {})
                tool_call_id = tool_call.get("id", "")

                # Find the corresponding tool output message
                tool_output = None
                for msg in result_messages:
                    if hasattr(msg, "tool_call_id") and msg.tool_call_id == tool_call_id:
                        tool_output = msg.content
                        break

                # If no matching output found, try by index
                if tool_output is None and i < len(result_messages):
                    tool_output = result_messages[i].content if hasattr(result_messages[i], "content") else str(result_messages[i])

                steps.append({
                    "type": "tool_call",
                    "id": tool_call_id,
                    "tool": tool_name,
                    "input": tool_args,
                    "output": tool_output,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            return {
                "messages": result_messages,
                "steps": steps,
            }
        except Exception as e:
            return {
                "messages": [ToolMessage(
                    content=f"Error executing tools: {str(e)}",
                    tool_call_id=last_message.tool_calls[0].get("id", ""),
                )],
                "steps": [{
                    "type": "error",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": str(e),
                }],
            }

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph state graph."""
        graph = StateGraph(AgentState)

        # Add nodes
        graph.add_node("agent", self._call_model)
        graph.add_node("tools", self._process_tools)

        # Add edges
        graph.set_entry_point("agent")
        graph.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "tools": "tools",
                "end": END,
            }
        )
        graph.add_edge("tools", "agent")

        return graph

    @property
    def graph(self) -> StateGraph:
        """Get the compiled graph."""
        if self._graph is None:
            self._graph = self._build_graph()
        return self._graph

    def build_initial_message(
        self,
        record_data: dict,
        context: dict,
    ) -> str:
        """Build the initial user message for the agent."""
        return f"""
Context:
{self._format_context(context)}

Record Data:
{self._format_record(record_data)}

Goal: {self.goal}

IMPORTANT: You MUST use the available tools to accomplish this task. Do not just describe what you would do - actually call the tools. Start by using a tool immediately.
"""

    def _format_context(self, context: dict) -> str:
        """Format context for the prompt."""
        if not context:
            return "No additional context provided."
        return "\n".join(f"- {k}: {v}" for k, v in context.items())

    def _format_record(self, record_data: dict) -> str:
        """Format record data for the prompt."""
        if not record_data:
            return "No record data provided."
        values = record_data.get("values", {})
        return "\n".join(f"- {k}: {v}" for k, v in values.items())

    async def run(
        self,
        record_id: str | None = None,
        record_data: dict | None = None,
        context: dict | None = None,
        conversation_history: list[BaseMessage] | None = None,
    ) -> dict:
        """Execute the agent.

        Args:
            record_id: Optional CRM record ID for context
            record_data: Optional record data dict
            context: Additional context for the agent
            conversation_history: Optional list of previous messages for multi-turn conversation
        """
        record_data = record_data or {}
        context = context or {}

        # Build initial messages
        if conversation_history:
            # For continuation of conversation, prepend system prompt and use history
            messages = [HumanMessage(content=self.system_prompt)]
            messages.extend(conversation_history)
        else:
            # Fresh conversation - build initial message
            initial_message = self.build_initial_message(record_data, context)
            messages = [
                HumanMessage(content=self.system_prompt + "\n\n" + initial_message)
            ]

        state: AgentState = {
            "messages": messages,
            "record_id": record_id,
            "record_data": record_data,
            "context": context,
            "steps": [],
            "final_output": None,
            "error": None,
        }

        # Compile and run graph
        compiled = self.graph.compile()

        try:
            final_state = await compiled.ainvoke(state)

            # Extract final output
            if final_state["messages"]:
                last_message = final_state["messages"][-1]
                if isinstance(last_message, AIMessage):
                    final_state["final_output"] = {
                        "content": last_message.content,
                        "tool_calls": getattr(last_message, "tool_calls", []),
                    }

            return {
                "status": "failed" if final_state.get("error") else "completed",
                "output": final_state.get("final_output"),
                "steps": final_state.get("steps", []),
                "error": final_state.get("error"),
            }
        except Exception as e:
            return {
                "status": "failed",
                "output": None,
                "steps": state.get("steps", []),
                "error": str(e),
            }
