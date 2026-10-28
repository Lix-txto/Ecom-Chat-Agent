"""pytest 全局配置：在任何 app 模块被导入前固定测试环境变量。

注意：进程环境变量优先级高于 .env 文件，因此这里的 JWT_SECRET_KEY
会覆盖 .env 的真实值 —— 保证测试可重复、不依赖用户本地配置。
服务进程（uvicorn）不受影响，两者互不干扰。
"""
import os

os.environ.setdefault("JWT_SECRET_KEY", "pytest-secret-key-not-for-production")
os.environ.setdefault("POSTGRES_PASSWORD", "admin")
