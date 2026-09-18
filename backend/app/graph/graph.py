from langgraph.graph import StateGraph, END

from app.graph.state import AgentState
from app.graph import nodes


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("load_store", nodes.load_store)
    graph.add_node("find_user", nodes.find_user)
    graph.add_node("classify_intent", nodes.classify_intent)
    graph.add_node("search_products", nodes.search_products)
    graph.add_node("route_to_chatwoot", nodes.route_to_chatwoot)
    graph.add_node("compose_response", nodes.compose_response)
    graph.add_node("send_reply", nodes.send_reply)

    graph.set_entry_point("load_store")
    graph.add_edge("load_store", "find_user")
    graph.add_edge("find_user", "classify_intent")
    graph.add_edge("classify_intent", "search_products")
    graph.add_edge("search_products", "route_to_chatwoot")
    graph.add_edge("route_to_chatwoot", "compose_response")
    graph.add_edge("compose_response", "send_reply")
    graph.add_edge("send_reply", END)

    return graph.compile()


_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph
