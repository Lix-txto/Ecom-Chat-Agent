from contextlib import asynccontextmanager
from typing import Any
from fastapi import FastAPI, Depends
from app.core.config import settings
from app.core.security import get_current_user
from app.models import User


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup：M6 在此初始化 Redis 连接池等
    yield
    # shutdown

app = FastAPI(
    title="FastAPI Template",
    version="0.2.0",
    lifespan=lifespan
)

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

# TODO(M5): 迁入正式 router；此处为 M2 鉴权链路手动验证端点
@app.get("/me")
async def me(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role.value,
    }