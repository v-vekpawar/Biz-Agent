"""
Graph assembly: wires the orchestrator, specialist nodes, critic, and synthesizer into the LangGraph StateGraph, plus the two conditional routing functions that drive the dynamic specialist ordering and the retry loop.
"""

from langgraph.graph import END, StateGraph

from ..agents.critic import critic_node
from ..agents.orchestrator import orchestrator_node
from ..agents.specialists import SPECIALISTS, make_specialist_node
from ..agents.synthesizer import synthesizer_node
from ..state import AgentState

def route_next(state: AgentState) -> str:
    order = state["plan"].get("specialists", [])
    done = set(state["specialist_outputs"].keys())
    for name in order:
        if name not in done:
            return name
    return "synthesizer"

def route_after_critic(state: AgentState) -> str:
    name = state.get("last_specialist")
    if name is None or name not in state["specialist_outputs"]:
        return route_next(state)
    verdict = state["critic_verdicts"].get(name)
    if verdict and verdict.get("will_retry"):
        return name
    return route_next(state)

def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("orchestrator", orchestrator_node)
    for name, (role, use_search) in SPECIALISTS.items():
        graph.add_node(name, make_specialist_node(name, role, use_search))
    graph.add_node("critic", critic_node)
    graph.add_node("synthesizer", synthesizer_node)

    graph.set_entry_point("orchestrator")

    routing_map = {name: name for name in SPECIALISTS}
    routing_map["synthesizer"] = "synthesizer"

    graph.add_conditional_edges("orchestrator", route_next, routing_map)
    for name in SPECIALISTS:
        graph.add_edge(name, "critic")
    graph.add_conditional_edges("critic", route_after_critic, routing_map)

    graph.add_edge("synthesizer", END)

    return graph.compile()
