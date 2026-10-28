"""模型层共享工具。"""
from datetime import datetime, timezone

def utc_now() -> datetime:
    """统一的时间源：所有写入 DB 的 datetime 必须经由本函数（tz-aware UTC）。"""
    return datetime.now(timezone.utc)
