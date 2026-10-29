"""LangGraph 节点定义。

数据流：
    START → intent_router
      ├─ order_query ──────────────┐
      ├─ refund_handle → audit_check ┤→ generate → END
      ├─ retrieve ─────────────────┘
      └─ (general_chat) ───────────┘

节点纪律：
1. 节点返回【部分状态 dict】，只写自己负责的键。
2. 节点不持有 Session；需要数据库时内部开短会话或调用 tools 层。
3. user_id 只从 state 读取（API 层注入），LLM 永远接触不到该参数。
4. LLM 不可用时全链路退化为确定性路径 —— 离线可测。
"""
import json
import re
from datetime import datetime, timezone
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.database import sync_engine
from app.graph.llm import get_chat_model, get_embeddings, llm_enabled
from app.graph.state import AgentState, Intent
from app.graph.tools import (
    check_refund_eligibility,
    extract_order_no,
    extract_refund_no,
    query_refund_status,
    submit_refund_application,
)
from app.models import KnowledgeChunk, Order, OrderStatus
from app.tasks.dispatcher import dispatch_admin_notification, dispatch_refund_payment


RETRIEVE_TOP_K = 3

_ORDER_STATUS_LABELS = {
    "pending_payment": "待支付",
    "paid": "已支付（待发货）",
    "shipped": "已发货",
    "completed": "已完成",
    "refund_requested": "退款处理中",
    "refunded": "已退款",
    "closed": "已关闭",
}
_REFUND_STATUS_LABELS = {
    "pending": "待审核",
    "auto_approved": "已通过",
    "processing": "退款处理中",
    "refunded": "已退款",
    "rejected": "已拒绝",
}
_GENERAL_GREETING = (
    "您好！我是商城智能客服助手，可以帮您查询订单、办理退款、"
    "查询退款进度或解答购物政策问题，请问有什么可以帮您？"
)


# ---------- 共用小工具 ----------


def _last_human_text(state: AgentState) -> str:
    for m in reversed(state.get("messages") or []):
        if isinstance(m, HumanMessage):
            return m.content if isinstance(m.content, str) else ""
    return ""


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# ================= Intent Router =================


class _IntentClassification(BaseModel):
    intent: Intent
    order_no: Optional[str] = Field(
        default=None, description="消息中出现的订单号，没有则为 null"
    )
    refund_no: Optional[str] = Field(
        default=None, description="消息中出现的退款单号（RF- 开头），没有则为 null"
    )


_INTENT_SYSTEM_PROMPT = """你是电商客服系统的意图分类器。把用户消息分类为以下之一：
- order_query: 查询订单 / 物流 / 发货进度
- refund_request: 申请退款 / 退货
- refund_status: 查询退款进度 / 到账情况
- policy_qa: 咨询政策规则（退货政策、运费、保修、时效等）
- general_chat: 问候或其他闲聊
同时抽取消息中出现的订单号与退款单号，没有则为 null。只输出结构化结果。"""

_POLICY_FIRST_RE = re.compile(r"政策|规定|流程|运费|保修")
_REFUND_WORD_RE = re.compile(r"退[款货钱掉]|要退|想退|申请退")
_REFUND_STATUS_RE = re.compile(r"进度|状态|到账|多久|处理得|怎么样|如何了|查询|查一下|退款单")


def _classify_keywords(text: str) -> str:
    """确定性兜底路由（优先级即顺序，测试锁定行为）。"""
    if _POLICY_FIRST_RE.search(text):
        return Intent.POLICY_QA.value
    if extract_refund_no(text):
        return Intent.REFUND_STATUS.value
    if _REFUND_WORD_RE.search(text):
        if _REFUND_STATUS_RE.search(text):
            return Intent.REFUND_STATUS.value
        return Intent.REFUND_REQUEST.value
    if extract_order_no(text) or re.search(r"订单|物流|发货|快递|到哪", text):
        return Intent.ORDER_QUERY.value
    if re.search(r"多久|几天|怎么退|如何退|能不能退|可以退吗", text):
        return Intent.POLICY_QA.value
    return Intent.GENERAL_CHAT.value


def _classify_with_llm(text: str) -> Optional[_IntentClassification]:
    llm = get_chat_model()
    if llm is None or not text.strip():
        return None
    try:
        structured = llm.with_structured_output(_IntentClassification)
        return structured.invoke(
            [SystemMessage(content=_INTENT_SYSTEM_PROMPT), HumanMessage(content=text)]
        )
    except Exception:
        return None  # LLM 失败 → 关键词兜底


def intent_router(state: AgentState) -> dict:
    text = _last_human_text(state)

    llm_result = _classify_with_llm(text) if llm_enabled() else None
    intent = (
        llm_result.intent.value if llm_result is not None else _classify_keywords(text)
    )

    # 实体：正则优先（格式精确），LLM 结果作模糊补充
    order_no = extract_order_no(text)
    refund_no = extract_refund_no(text)
    if llm_result is not None:
        order_no = order_no or (llm_result.order_no or "").strip() or None
        refund_no = refund_no or (llm_result.refund_no or "").strip() or None

    updates: dict = {"intent": intent}
    # 关键：抽不到就不写键 → 保留线程内上一轮的值（多轮对话连续性）
    if order_no:
        updates["order_no"] = order_no
    if refund_no:
        updates["refund_no"] = refund_no
    return updates


# ================= Order Query =================


def order_query_node(state: AgentState) -> dict:
    order_no = state.get("order_no")
    user_id = state.get("user_id")

    if not order_no:
        return {
            "order_info": {
                "found": False,
                "message": "请提供您的订单号（形如 ORD-20261025-0001），我来为您查询订单。",
            }
        }

    with Session(sync_engine) as session:
        order = session.exec(
            select(Order).where(Order.order_no == order_no, Order.user_id == user_id)
        ).first()

    if order is None:
        return {"order_info": {"found": False, "message": "未找到该订单，请核对订单号。"}}

    status = (
        order.status.value if isinstance(order.status, OrderStatus) else str(order.status)
    )
    return {
        "order_info": {
            "found": True,
            "order_no": order.order_no,
            "product_name": order.product_name,
            "quantity": order.quantity,
            "amount": str(order.amount),
            "status": status,
            "created_at": _as_utc(order.created_at).isoformat(),
        }
    }


# ================= Refund Handle =================


def refund_handle_node(state: AgentState) -> dict:
    intent = state.get("intent")
    user_id = state.get("user_id")
    text = _last_human_text(state)

    # ---- 查询退款进度 ----
    if intent == Intent.REFUND_STATUS.value:
        refund_no = state.get("refund_no")
        order_no = state.get("order_no")
        if not refund_no and not order_no:
            return {
                "refund_status_result": {
                    "found": False,
                    "message": "请提供退款单号（RF- 开头）或订单号，我来为您查询退款进度。",
                }
            }
        out = query_refund_status.invoke(
            {"user_id": user_id, "refund_no": refund_no, "order_no": order_no}
        )
        return {"refund_status_result": out}

    # ---- 申请退款（默认路径）----
    order_no = state.get("order_no")
    if not order_no:
        return {
            "refund_application": {
                "success": False,
                "message": "请提供您的订单号（形如 ORD-20261025-0001），我来为您办理退款。",
            }
        }

    eligibility = check_refund_eligibility.invoke(
        {"order_no": order_no, "user_id": user_id}
    )
    updates: dict = {"eligibility_result": eligibility}

    if eligibility.get("eligible"):
        # 会话语境即退款原因（服务层会清洗截断）
        application = submit_refund_application.invoke(
            {"order_no": order_no, "user_id": user_id, "reason": text}
        )
        updates["refund_application"] = application
    # 不合格时 refund_application 保持缺席 → generate 读 eligibility.reason
    return updates


# ================= Audit Check =================


def audit_check_node(state: AgentState) -> dict:
    """审计分流：派发 Celery 任务（唯一 agent 侧派发点，服务层保持零 Celery 依赖）。

    - 自动批准 → dispatch_refund_payment（worker 异步打款 → REFUNDED → WS 推送）
    - 转人工   → dispatch_admin_notification（提醒管理员，经 pub/sub 广播到管理员 WS）
    测试环境 CELERY_ENABLED=false，派发为 no-op。
    """
    application = state.get("refund_application")
    needs_audit = bool(application and application.get("needs_manual_review"))

    if application and application.get("success") and application.get("refund_no"):
        refund_no = application["refund_no"]
        if needs_audit:
            dispatch_admin_notification(refund_no)
        elif application.get("auto_approved"):
            dispatch_refund_payment(refund_no)

    return {"needs_audit": needs_audit}



# ================= Retrieve（RAG） =================


def retrieve_node(state: AgentState) -> dict:
    text = _last_human_text(state)
    if not text:
        return {"retrieved_chunks": []}

    embeddings = get_embeddings()
    query_vec = embeddings.embed_query(text)
    distance = KnowledgeChunk.embedding.cosine_distance(query_vec)

    with Session(sync_engine) as session:
        rows = session.exec(
            select(KnowledgeChunk, distance)
            .where(KnowledgeChunk.embedding.is_not(None))
            .order_by(distance)
            .limit(RETRIEVE_TOP_K)
        ).all()

    chunks = [
        {
            "source": row.source,
            "content": row.content,
            "meta": row.meta,
            "score": round(1.0 - dist, 4),  # 余弦相似度
        }
        for row, dist in rows
    ]
    return {"retrieved_chunks": chunks}


# ================= Generate =================

_GENERATE_SYSTEM_PROMPT = (
    "你是电商平台的智能客服助手。请严格依据【参考数据】回答用户问题，"
    "不得编造订单号、退款单号、金额或状态等事实信息。"
    "用中文回复，简洁友好，控制在 120 字以内。"
    "如果参考数据不足以回答，请如实说明并引导用户提供订单号或退款单号。"
)


def _generate_with_llm(state: AgentState, text: str) -> Optional[str]:
    llm = get_chat_model()
    if llm is None:
        return None
    ctx: dict = {}
    for key in (
        "order_info",
        "eligibility_result",
        "refund_application",
        "refund_status_result",
    ):
        if state.get(key):
            ctx[key] = state[key]
    chunks = state.get("retrieved_chunks") or []
    if chunks:
        ctx["policy_snippets"] = [c["content"] for c in chunks[:2]]

    messages = [
        SystemMessage(content=_GENERATE_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"用户问题：{text}\n\n"
                f"参考数据（JSON）：{json.dumps(ctx, ensure_ascii=False)}"
            )
        ),
    ]
    try:
        return llm.invoke(messages).content
    except Exception:
        return None  # 网络等异常 → 模板兜底


def _order_query_text(state: AgentState) -> str:
    info = state.get("order_info") or {}
    if not info.get("found"):
        return info.get("message", "请提供订单号后我来为您查询。")
    label = _ORDER_STATUS_LABELS.get(info["status"], info["status"])
    return (
        f"为您查询到订单 {info['order_no']}：{info['product_name']} ×{info['quantity']}，"
        f"金额 ¥{info['amount']}，当前状态：{label}，下单时间 {info['created_at'][:10]}。"
    )


def _refund_request_text(state: AgentState) -> str:
    application = state.get("refund_application")
    if application is None:
        eligibility = state.get("eligibility_result")
        if eligibility:
            return eligibility.get("reason", "该订单目前无法退款。")
        return "请提供订单号后我再为您办理退款。"
    if application.get("success"):
        message = application.get("message", "")
        refund_no = application.get("refund_no")
        return f"{message}（退款单号：{refund_no}）" if refund_no else message
    return application.get("message", "退款申请未能提交。")


def _refund_status_text(state: AgentState) -> str:
    info = state.get("refund_status_result") or {}
    if not info.get("found"):
        return info.get("message", "未找到对应的退款记录。")
    label = _REFUND_STATUS_LABELS.get(info["status"], info["status"])
    return (
        f"您的退款单 {info['refund_no']}（订单 {info['order_no']}，"
        f"商品：{info['product_name']}）当前状态：{label}，"
        f"退款金额 ¥{info['amount']}，申请时间 {info['requested_at'][:10]}。"
    )


def _policy_text(state: AgentState) -> str:
    chunks = state.get("retrieved_chunks") or []
    if not chunks:
        return "暂时没有找到相关政策信息，您可以换个问法或联系人工客服。"
    body = "\n\n".join(c["content"] for c in chunks[:2])
    if len(body) > 600:
        body = body[:600] + "…"
    return f"根据商城政策：\n{body}"


def _template_response(state: AgentState, intent: str) -> str:
    if intent == Intent.ORDER_QUERY.value:
        return _order_query_text(state)
    if intent == Intent.REFUND_REQUEST.value:
        return _refund_request_text(state)
    if intent == Intent.REFUND_STATUS.value:
        return _refund_status_text(state)
    if intent == Intent.POLICY_QA.value:
        return _policy_text(state)
    return _GENERAL_GREETING


def generate_node(state: AgentState) -> dict:
    intent = state.get("intent") or Intent.GENERAL_CHAT.value
    text = _last_human_text(state)

    response = _generate_with_llm(state, text) if llm_enabled() else None
    if not response:
        response = _template_response(state, intent)

    # 同时把回复追加进消息历史（Checkpointer 线程内可回看）
    return {"final_response": response, "messages": [AIMessage(content=response)]}
