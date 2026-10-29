"""状态查询 API（前端轮询）：按订单号查退款进度。"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session

from app.core.database import sync_engine
from app.core.security import get_current_user
from app.models import User
from app.services.refund_service import RefundStatusInfo, query_refund_status

router = APIRouter(tags=["status"])


@router.get("/status/refunds/{order_no}", response_model=RefundStatusInfo)
async def refund_status(
    order_no: str, user: User = Depends(get_current_user)
):
    def _query() -> RefundStatusInfo | None:
        with Session(sync_engine) as session:
            return query_refund_status(session, user.id, order_no=order_no)

    info = await run_in_threadpool(_query)
    if info is None:
        raise HTTPException(status_code=404, detail="未找到对应的退款记录")
    return info
