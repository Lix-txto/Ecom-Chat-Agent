"""LangGraph 状态定义。

设计要点：
1. TypedDict 而非 Pydantic：LangGraph 的 channel 以 dict 形式读写状态，
   Redis Checkpointer 持久化时按 dict 序列化，TypedDict 零成本兼容。
2. messages 使用 add_messages 归约器：新消息追加而非覆盖，并按 id 去重更新。
3. total=False：所有键可选 —— 图中每个节点只写自己负责的键。
4. 可序列化纪律：state 只允许 int / str / bool / dict / list 等 JSON 安全类型；
   Session / Engine / ORM 对象一律禁止入 state（工具在内部自建会话的原因）。
"""
from enum import Enum
from typing import Annotated, Optional

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class Intent(str, Enum):
    """意图路由枚举：Intent Router 节点（M4b）产出。"""

    ORDER_QUERY = "order_query"        # 查订单
    REFUND_REQUEST = "refund_request"  # 申请退款
    REFUND_STATUS = "refund_status"    # 查退款进度
    POLICY_QA = "policy_qa"            # 政策咨询（走 RAG）
    GENERAL_CHAT = "general_chat"      # 闲聊 / 兜底


class AgentState(TypedDict, total=False):
    # ---- 请求上下文（API 层 invoke 时注入，节点只读）----
    user_id: int
    session_id: str

    # ---- 消息流 ----
    messages: Annotated[list[AnyMessage], add_messages]

    # ---- 路由与实体（Intent Router / 实体抽取节点产出，M4b）----
    intent: Optional[str]      # 存 Intent 成员值；str 枚举天然可序列化
    order_no: Optional[str]
    refund_no: Optional[str]

    # ---- 工具 / 节点输出（JSON 可序列化 dict）----
    eligibility_result: Optional[dict]
    refund_application: Optional[dict]
    refund_status_result: Optional[dict]
    order_info: Optional[dict]          # Order Query 节点产出（M4b）
    retrieved_chunks: Optional[list[dict]]  # Retrieve 节点产出（M4b，RAG）

    # ---- 审计分流（Audit Check 节点消费）----
    needs_audit: bool

    # ---- 最终输出（Generate 节点产出）----
    final_response: Optional[str]
