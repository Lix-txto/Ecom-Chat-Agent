from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.config import settings
from app.api.v1 import auth, chat, status, admin, websocket

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: M6：在此启动 Redis pub/sub 监听任务（Celery → WS 通知桥接）
    yield
    # shutdown

app = FastAPI(
    title="FastAPI Template",
    version="0.5.0",
    lifespan=lifespan
)

API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(chat.router, prefix=API_PREFIX)
app.include_router(status.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(websocket.router, prefix=API_PREFIX)

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "healthy",
            "version": "0.1.0",
            "time": "2023-03-09 10:00:00",
            "features":["用户登录认证", 
            "多租户数据隔离",  
            "订单查询",
            "政策咨询",
            "退货申请",
            "人工审核",
            "实时状态同步",
            "管理员工作台"
            ]
            }

