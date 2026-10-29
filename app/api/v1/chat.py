"""聊天 API：Agent 引擎（同步）× FastAPI（异步）的边界处理。

- graph 经 Depends 注入 → 测试可 override 为内存 Checkpointer 图
- 每轮对话持久化 MessageCard：用户原文 + 助手回复（按意图挂结构化卡片）
- history 按 user_id 过滤：session_id 不可作为越权凭据
"""
from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from langgraph.graph.state import CompiledStateGraph
from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.schemas import ChatHistoryItem, ChatRequest, ChatResponse
from app.core.database import get_session, sync_engine
from app.core.security import get_current_user
from app.graph.workflow import get_workflow, invoke_agent
from app.models import MessageCard, MessageRole, User

router = APIRouter(tags=["chat"])


def _get_graph() -> CompiledStateGraph:
    return get_workflow()


def _card_for(intent: str, result: dict) -> tuple[str | None, dict | None]:
    """按意图挑选落库的结构化卡片。"""
    if intent == "order_query":
        return "order_info", result.get("order_info")
    if intent == "refund_request":
        application = result.get("refund_application")
        if application:
            return "refund_application", application
        return "eligibility", result.get("eligibility_result")
    if intent == "refund_status":
        return "refund_status", result.get("refund_status_result")
    if intent == "policy_qa":
        return "policy", {"chunks": result.get("retrieved_chunks")}
    return None, None


def _persist_turn(user_id: int, session_id: str, user_text: str, result: dict) -> None:
    """线程池内执行：同步会话写两条消息。"""
    intent = result.get("intent") or "general_chat"
    card_type, card_payload = _card_for(intent, result)
    with Session(sync_engine) as session:
        session.add(MessageCard(
            session_id=session_id, user_id=user_id,
            role=MessageRole.USER, content=user_text,
        ))
        session.add(MessageCard(
            session_id=session_id, user_id=user_id,
            role=MessageRole.ASSISTANT,
            content=result.get("final_response") or "",
            card_type=card_type, card_payload=card_payload,
        ))
        session.commit()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    user: User = Depends(get_current_user),
    graph: CompiledStateGraph = Depends(_get_graph),
):
    result = await run_in_threadpool(
        invoke_agent, user.id, req.session_id, req.message, graph
    )
    await run_in_threadpool(_persist_turn, user.id, req.session_id, req.message, result)
    return ChatResponse(
        session_id=req.session_id,
        reply=result.get("final_response") or "",
        intent=result.get("intent") or "general_chat",
        order_no=result.get("order_no"),
        refund_no=(result.get("refund_application") or {}).get("refund_no"),
        needs_audit=bool(result.get("needs_audit")),
    )


@router.get("/chat/history/{session_id}", response_model=list[ChatHistoryItem])
async def chat_history(
    session_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.exec(
            select(MessageCard)
            .where(MessageCard.session_id == session_id)
            .where(MessageCard.user_id == user.id)
            .order_by(MessageCard.id)
        )
    ).all()
    return [
        ChatHistoryItem(
            role=r.role.value,
            content=r.content,
            card_type=r.card_type,
            card_payload=r.card_payload,
            created_at=r.created_at,
        )
        for r in rows
    ]
