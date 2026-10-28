"""LangGraph 工具定义：Check / Submit / Query 三个退款工具，桥接 services 层。

四条实现铁律（与 M4b 节点层约定一致）：
1. 【会话不入 state】LangGraph state 需经 Redis Checkpointer 序列化持久化，
   Session / Engine 一律禁止进入 state —— 每次工具调用内部自建短会话，用完即关。
2. 【身份不可伪造】user_id 只能由 API 层写入 state、节点读取后注入工具调用，
   绝不交给 LLM 生成 —— 防止提示注入伪造他人身份（提权查/退他人订单）。
3. 【返回 JSON 安全类型】返回值为 dict（str/int/float/list/bool），
   供 Generate 节点、消息卡片、Checkpointer 直接消费。
4. 【同步实现】底层 services 为同步；M5 异步端点用 run_in_threadpool 包装调用。
"""
import re
from typing import Optional, Annotated

from langchain_core.tools import tool, InjectedToolArg
from sqlmodel import Session

from app.core.database import sync_engine
from app.services import refund_service

# ---------------------------------------------------------------------------
# 实体抽取（启发式正则，M4b 节点兜底使用；之后可升级为 LLM 抽取）
# ---------------------------------------------------------------------------

# 大写字母开头的连字符编号：ORD-20261025-0001 / T-SHIP-RECENT
# (?!RF-) 排除退款单号；仅匹配大写（小写/口语化输入留给 M4b 的 LLM 抽取兜底）
_ORDER_NO_RE = re.compile(r"\b(?!RF-)[A-Z]{1,6}(?:-[A-Z0-9]+)+\b")
_REFUND_NO_RE = re.compile(r"\bRF-\d{14}-[0-9A-F]{6}\b")


def extract_order_no(text: str) -> Optional[str]:
    """从用户消息中启发式抽取订单号（取第一个匹配），无匹配返回 None。"""
    if not text:
        return None
    m = _ORDER_NO_RE.search(text)
    return m.group(0) if m else None


def extract_refund_no(text: str) -> Optional[str]:
    """从用户消息中抽取退款单号（RF-时间戳-随机码），无匹配返回 None。"""
    if not text:
        return None
    m = _REFUND_NO_RE.search(text)
    return m.group(0) if m else None


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------


def _new_session() -> Session:
    """每次调用独立短会话：事务边界清晰、可被线程池并发调用。"""
    return Session(sync_engine)


@tool
def check_refund_eligibility(order_no: str, user_id: Annotated[int, InjectedToolArg]) -> dict:
    """检查指定订单当前是否符合退款资格，返回结论、原因与订单摘要。

    Args:
        order_no: 订单编号，例如 ORD-20261025-0001。
    """
    with _new_session() as session:
        result = refund_service.check_refund_eligibility(session, order_no, user_id)
        return result.model_dump(mode="json")


@tool
def submit_refund_application(order_no: str, user_id: int, reason: str = "") -> dict:
    """为指定订单提交退款申请：金额不超过阈值自动批准，超过则转人工审核。

    Args:
        order_no: 订单编号。
        user_id: 用户 ID（由系统注入，模型不应生成）。
        reason: 用户填写的退款原因，可为空。
    """
    with _new_session() as session:
        result = refund_service.create_refund_application(
            session, order_no, user_id, reason
        )
        return result.model_dump(mode="json")


@tool
def query_refund_status(
    user_id: int, refund_no: Optional[str] = None, order_no: Optional[str] = None
) -> dict:
    """按退款单号或订单号查询退款处理进度。

    Args:
        user_id: 用户 ID（由系统注入，模型不应生成）。
        refund_no: 退款单号（RF- 开头），与 order_no 二选一。
        order_no: 订单编号，与 refund_no 二选一。
    """
    with _new_session() as session:
        info = refund_service.query_refund_status(
            session, user_id, refund_no=refund_no, order_no=order_no
        )
    if info is None:
        return {"found": False, "message": "未找到对应的退款记录"}
    return {"found": True, **info.model_dump(mode="json")}


__all__ = [
    "check_refund_eligibility",
    "submit_refund_application",
    "query_refund_status",
    "extract_order_no",
    "extract_refund_no",
]
