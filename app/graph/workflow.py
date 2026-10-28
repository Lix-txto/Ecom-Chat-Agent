"""LangGraph 工作流组装与编译。

- build_workflow(checkpointer) : 纯组装函数（测试传 MemorySaver）
- get_workflow()               : 进程级单例，默认 Redis Checkpointer（失败回退内存）
- invoke_agent(...)            : M5 API 层将直接复用的调用入口
"""
import logging
import threading

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.graph.nodes import (
    audit_check_node,
    generate_node,
    intent_router,
    order_query_node,
    refund_handle_node,
    retrieve_node,
)
from app.graph.state import AgentState

logger = logging.getLogger(__name__)

_workflow = None
_lock = threading.Lock()


def route_after_intent(state: AgentState) -> str:
    intent = state.get("intent")
    if intent == "order_query":
        return "order_query"
    if intent in ("refund_request", "refund_status"):
        return "refund_handle"
    if intent == "policy_qa":
        return "retrieve"
    return "generate"


def build_workflow(checkpointer=None):
    graph = StateGraph(AgentState)

    graph.add_node("intent_router", intent_router)
    graph.add_node("order_query", order_query_node)
    graph.add_node("refund_handle", refund_handle_node)
    graph.add_node("audit_check", audit_check_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)

    graph.add_edge(START, "intent_router")
    graph.add_conditional_edges("intent_router", route_after_intent)
    graph.add_edge("order_query", "generate")
    graph.add_edge("refund_handle", "audit_check")
    graph.add_edge("audit_check", "generate")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)

    return graph.compile(checkpointer=checkpointer)


def _default_checkpointer():
    """优先 Redis（对齐原项目），容器不可用时降级内存并告警。"""
    try:
        import redis as redis_lib
        from langgraph.checkpoint.redis import RedisSaver

        client = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        saver = RedisSaver(redis_client=client)
        saver.setup()  # 创建 RediSearch 索引（redis-stack 才支持）
        logger.info("LangGraph Checkpointer: Redis (%s)", settings.REDIS_URL)
        return saver
    except Exception as exc:  # 模块缺失 / 容器未启动 / 缺 RediSearch
        logger.warning("Redis Checkpointer 不可用，回退内存（%s）", exc)
        return InMemorySaver()


def get_workflow():
    global _workflow
    with _lock:
        if _workflow is None:
            _workflow = build_workflow(_default_checkpointer())
    return _workflow


def invoke_agent(
    user_id: int,
    session_id: str,
    text: str,
    graph=None,
    thread_id: str | None = None,
) -> dict:
    """统一调用入口：M5 的 chat API / 前端都将复用。

    thread_id 默认取 session_id —— 同一会话共享 LangGraph 线程态
    （消息历史 + order_no 等实体跨轮保留）。
    """
    graph = graph or get_workflow()
    has_checkpointer = getattr(graph, "checkpointer", None) is not None
    config = (
        {"configurable": {"thread_id": thread_id or session_id}}
        if has_checkpointer
        else None
    )
    return graph.invoke(
        {
            "user_id": user_id,
            "session_id": session_id,
            "messages": [HumanMessage(content=text)],
        },
        config,
    )
