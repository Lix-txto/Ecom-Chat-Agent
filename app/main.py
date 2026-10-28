from fastapi import FastAPI

app = FastAPI(
    title="FastAPI Template",
    description="我不是人机",
    version="0.1.0"
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
