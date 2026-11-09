# Ecom-Chat-Agent · 电商智能客服 Agent

基于 FastAPI \+ SQLModel \+ LangGraph \+ Celery \+ Gradio 的电商智能客服 Agent：
订单查询、退款办理（规则引擎 \+ 自动/人工分流）、政策知识库 RAG 问答。
退款批准后由 Celery 异步完成打款闭环，结果经 Redis pub/sub 实时推送 WebSocket。

## 架构

```text
Gradio 前端 ──HTTP/WS──> FastAPI API 层 ──依赖注入──> LangGraph 工作流
                            │      │                      │
                            │      │               Intent Router（LLM+关键词兜底）
                            │      │               ├─ Order Query   ─┐
                            │      │               ├─ Refund Handle ─┼→ Generate
                            │      │               ├─ Retrieve(RAG) ─┘
                            │      │               └─ Audit Check ──→ dispatcher
                            │      │                      │
                            │      └──> Services 层（退款规则引擎，零外部依赖）
                            │             │
                            │             └──> PostgreSQL（SQLModel + pgvector）
                            │
                            └──> Redis pub/sub <── Celery Worker
                                 （打款模拟/短信/管理员通知，跨进程事件桥）
```

## 技术栈

Python 3\.12 · uv · FastAPI · SQLModel · Alembic · PostgreSQL \+ pgvector ·
Redis（LangGraph Checkpointer \+ pub/sub）· Celery · LangGraph · LangChain ·
DeepSeek（Chat）· 硅基流动 bge\-m3（Embedding，1024 维）· Gradio · pytest

## 项目结构

```text
Ecom-Chat-Agent/
├── app/                  # 后端包：api / services / tasks / graph / models / core
├── frontend/             # Gradio 前端（纯 HTTP 客户端，与 app 包零 import 耦合）
├── scripts/              # seed_data.py / etl_policy.py
├── alembic/              # 数据库迁移
├── tests/                # 135 个离线测试
├── start_worker.sh       # Celery worker 启动
├── start_frontend.sh     # Gradio 启动（→ http://localhost:7860）
└── pyproject.toml
```

## 快速开始

```bash
# 0) 依赖与环境
uv sync
uv add gradio requests            # 前端依赖（如未安装）
docker compose up -d              # postgres(pgvector) + redis-stack
# 1) 建表 + 种子数据 + 知识库 ETL
uv run alembic upgrade head
uv run python -m scripts.seed_data     # admin/admin123、zhangsan/zhangsan123 + 订单
uv run python -m scripts.etl_policy    # 政策切块 → 向量化 → knowledge_chunks
# 2) 三进程启动（各开一个终端）
uv run uvicorn app.main:app --port 8000 --reload   # API + WebSocket
bash start_worker.sh                               # Celery worker（3 个任务）
bash start_frontend.sh                             # Gradio → http://localhost:7860
```

## \.env 配置

|键|必需|说明|
|---|---|---|
|`POSTGRES_*`|✅|数据库连接|
|`JWT_SECRET_KEY`|✅|`openssl rand -hex 32` 生成|
|`DEEPSEEK_API_KEY`|可选|留空自动降级（见下）|
|`SILICONFLOW_API_KEY`|可选|留空自动降级（见下）|
|`EMBEDDING_DIM`|可选|默认 1024；**变更必须配迁移 \+ 重建测试库**|
|`CELERY_ENABLED`|可选|`false` 时派发为 no\-op（纯 API 调试）|
|`PAYMENT_SIMULATION_SECONDS`|可选|打款模拟时长|
|`API_BASE_URL` / `FRONTEND_PORT`|可选|前端指向的 API 地址 / Gradio 端口|
|**降级设计**：两个 API Key 留空时系统自动降级为——关键词路由 / 模板回复 / Hash 嵌入，|||
|全链路仍可离线运行与测试（135 个测试零 LLM token、零 broker）。|||

## 演示剧本

> **演示准备**：种子订单刻意覆盖各规则分支，但其中没有 ≤100 元且在退货期内的小额单
> （59 元的 ORD\-20261025\-0002 已过 7 天退货期，是"超期不可退"的演示素材）。
> 建议直接在 `scripts/seed_data.py` 的 `SEED_ORDERS` 追加一行（assert 同步改 6）：
> 
> ```python
> ("ORD-20261029-0059", "无线鼠标", 1, "59.00", OrderStatus.SHIPPED, 2),
> ```
> 
> 临时演示也可手动补插：
> 
> ```bash
> docker exec agent_db psql -U postgres -d knowledge_base -c \
>   "INSERT INTO orders (order_no, user_id, product_name, quantity, amount, status, created_at, updated_at) \
>    VALUES ('ORD-20261029-0059', 2, '演示小额商品', 1, 59.00, 'SHIPPED', now(), now());"
> ```
> 
> 

### 幕一：小额自动退款（≤100 元，免审核）

1. zhangsan 登录前端 → 聊天 `帮我退掉 ORD-20261029-0059`

2. 回复含退款单号（RF\- 前缀）

3. worker 日志：`PROCESSING → 打款成功 → [SMS 模拟]`

4. "退款进度查询"面板输入订单号 → 已自动通过 → 已退款

5. psql 中订单/退款双 `REFUNDED`；用户 WS 收到 `refund.completed`

### 幕二：大额人工审核（\>100 元，转人工）

1. 聊天 `帮我退掉 ORD-20261025-0001`（299 元耳机）→ 提示转人工审核

2. 退出 → admin 登录 → 审核页出现待审任务

3. 批准 → 提示派发 → worker 打款日志 → 列表自动刷新

4. 重复决策返回 409

### 幕三：政策 RAG 问答

聊天 `退货政策是什么` → 检索 knowledge\_chunks → 生成回答。

### 加演：护栏与拒绝分支

- 重复退款同一订单 → 防重话术，不产生新退款单

- 退超期单 `ORD-20261025-0002` / 未支付单 `ORD-20261027-0002` → "不可退"拒绝

### 收官验尸

```bash
docker exec agent_db psql -U postgres -d knowledge_base -c \
  "SELECT o.order_no, o.status AS order_status, r.refund_no, r.status AS refund_status, r.processed_at \
   FROM refunds r JOIN orders o ON o.id=r.order_id ORDER BY r.id DESC LIMIT 4;"
```

## API 一览

|方法|路径|权限|说明|
|---|---|---|---|
|POST|`/api/v1/auth/login`|公开|OAuth2 表单登录 → JWT（时效 1 小时）|
|GET|`/api/v1/auth/me`|登录|当前用户信息|
|POST|`/api/v1/chat`|登录|Agent 对话（reply / intent / refund\_no / needs\_audit）|
|GET|`/api/v1/chat/history/{session_id}`|登录|会话历史（按 user\_id 隔离）|
|GET|`/api/v1/status/refunds/{order_no}`|登录|退款进度轮询（**参数是订单号**，非 RF 号）|
|GET|`/api/v1/admin/audits`|管理员|待审任务列表|
|POST|`/api/v1/admin/audits/{id}/decision`|管理员|approve / reject（重复决策 409）|
|WS|`/api/v1/ws/{session_id}?token=JWT`|登录|实时推送（refund\.completed / audit\.pending）|
|GET|`/health`|公开|健康检查|
|Swagger：`http://localhost:8000/docs`（Authorize 按钮填 token 可用）。||||

## 退款状态机

```text
提交 → PENDING ──(金额≤100 自动)──→ AUTO_APPROVED ──→ PROCESSING ──→ REFUNDED
         │
         └──(金额>100 转人工)──→ approve → AUTO_APPROVED
                              → reject  → REJECTED（订单恢复 SHIPPED）
任务侧防护：REFUNDED 幂等跳过；PENDING / REJECTED 拒绝执行
```

## 项目宪章（十诫）

1. **时间**：一律 `utc_now()`（tz\-aware UTC）；禁用 `datetime.now()` / `datetime.utcnow()`

2. **金额**：一律 Decimal；阈值比较前显式 `Decimal(str(x))`

3. **分层**：services 零外部依赖（无 Celery / LLM / FastAPI）；Celery 派发只经 `tasks/dispatcher.py`

4. **身份**：user\_id 仅由系统注入（state / API 层），LLM 永远不可生成；token 的 role 只展示，鉴权回查 DB

5. **安全**：资源不存在与越权访问返回同一文案（防枚举）；401=认证失败、403=无权限、409=重复决策

6. **会话**：Session / Engine 禁入 LangGraph state（可序列化纪律）；工具与任务内部自建短会话

7. **可测性**：无 API Key 自动降级（关键词路由 / 模板生成 / Hash 嵌入）；`CELERY_ENABLED=false` 时派发为 no\-op

8. **测试隔离**：pytest 使用独立库 `knowledge_base_test`（模型含 pgvector / JSONB，SQLite 不可用）

9. **任务**：支付任务幂等 \+ 状态机防护（REFUNDED 跳过 / PENDING、REJECTED 拒绝执行）

10. **供应商**：Chat=DeepSeek、Embedding=硅基流动 bge\-m3；`EMBEDDING_DIM` 变更必须配迁移 \+ 重建测试库

## 测试

```bash
uv run pytest            # 135 passed（全程离线，零 LLM token、零 broker 依赖）
uv run pytest --collect-only -q | tail -n 2   # 交叉验证总数
```

### 测试总账（诚实落账）

|里程碑|数量|覆盖|
|---|---|---|
|M2|9|服务层基础|
|M3|19|LangGraph 工作流|
|M4a|23|退款规则引擎穷举|
|M4b|37|工具层 \+ 节点端到端|
|M5|28|API 层 \+ 任务/事件桥|
|M6|16|异步支付闭环|
|M7|3|前端契约与标签对齐|
|**合计**|**135**||
|（此前曾在 M5/M6 轮误写 24/15，正确数字以上表与 `pytest --collect-only -q` 实测为准。）|||
|分层覆盖：服务层规则穷举 → 工具层 → 节点/工作流端到端 → API 层 → 任务/事件桥 → 前端契约。|||

## 已知简化（生产加固清单）

- 支付为模拟（`PAYMENT_SIMULATION_SECONDS` 控制时长）；真实接入需沙箱环境 \+ 对账

- JWT 无 refresh token；无限流与请求审计

- reject 后订单统一恢复 SHIPPED（未记录退款前状态）

- Gradio 为演示前端；消息卡片 payload 未做富渲染；生产建议替换为 SPA

- 单机部署；生产需 worker 多副本 \+ 消息重试 / 死信队列

## 踩坑备忘（开发期实录）

- **枚举大小写**：PG enum 存的是名字（大写）。SQL 过滤写 `'SHIPPED'` / `'PENDING'` / `'ADMIN'`，
小写会报 `invalid input value for enum`

- **JWT 时效 1 小时**（exp\-iat=3600）：`无法校验的 Token` 即过期，重新登录即可

- **时间戳列名**：`refunds` 表无 `created_at`，用 `processed_at` 等语义化列

- **表名**：SQLModel 默认复数化，审核表为 `audit_logs`

- **CELERY\_ENABLED=false 时**：聊天返回 needs\_audit 等字段但 worker 无日志——不是 bug，派发为 no\-op

## 重置

```bash
uv run alembic downgrade base && uv run alembic upgrade head
uv run python -m scripts.seed_data
uv run python -m scripts.etl_policy
```

⚠️ 会清空全部数据（含退款记录）；正式演示前重置可顺带验证全链路可重建性。
