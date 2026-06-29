# PPT/PDF转复习提纲和考试例题智能系统

基于DeepAgent的智能系统，能够将PPT/PDF文件转化为复习提纲和考试例题。

## 功能特性

- **多智能体协作**：8个专业智能体分工协作
- **Agentic RAG**：混合检索方案，支持知识点问答解释
- **记忆系统**：短期、长期、工作记忆三层架构
- **自进化系统**：基于DSPy + GEPA的反射式进化优化
- **多模态支持**：图表理解、公式识别、表格提取
- **正式产品基础**：支持登录鉴权、owner隔离、审计查询、PostgreSQL/Redis/S3生产后端、Docker Compose和CI验证。

## 当前实现状态

### MVP-9 Agentic Study Pipeline

下一阶段实现计划：构建确定性、可追踪的 study-agent 工作流，在 simple RAG、Graph RAG Lite 和 Agentic RAG 之间自动路由学习查询；收集 evidence；生成带引用的复习内容；并验证结果应直接返回还是标记为人工审核。

Study Agent queries now require explicit `document_ids` and prefer persisted chunks created from the authenticated user's processed `normalized_document` artifacts. Query-time chunking remains as an observable fallback when chunks are missing, incomplete, or stale; vector provider integration remains a future scaling step.

Study Agent queries also create safe trace summaries for product observability. Trace metadata records route, index fallback, confidence, recall, latency, and review status without storing raw private query text, generated answers, chunk content, or source snippets.

Study Agent workflow supervision now exposes a safe stage timeline for intake, planning, retrieval, generation, verification, review gate, and trace. Workflow diagnostics are compact and privacy-safe: they include status, counts, mode/category labels, fallback and review reason codes, but not raw queries, generated answers, chunks, prompts, hidden reasoning, or secrets.

RAG route policy P2 is now represented in deterministic evaluation fixtures and reports. The fixture set covers direct lookup, definition, concept relation, learning path, multi-document synthesis, question generation, and outline fragment cases; evaluation reports include privacy-safe policy status and category summaries without raw query, answer, chunk, prompt, or source snippet text.

The frontend workbench includes a Study Agent panel for one or more ready documents, grounded answer/question/note generation, citation display, confidence, and review status.

### MVP-8 Production Readiness Foundation

当前代码已进入 MVP-8 Production Readiness Foundation 阶段：

- FastAPI 提供 `/api/documents`、`/api/jobs`、`/api/exports`、`/api/feedback`、`/api/review-tasks` 等产品接口。
- Auth API 提供 `/api/auth/login` 和 `/api/auth/me`，正式产品路径使用 Bearer token。
- 数据库模型覆盖 documents、processing_jobs、content_versions、export_jobs、feedback、review_tasks、audit_events。
- 生产目标为 PostgreSQL；SQLite 仍用于单元测试和本地轻量路径。
- `StorageBackend` 支持本地文件系统和 S3/MinIO，生产 profile 使用 S3-compatible backend。
- 队列支持进程内测试队列和 Redis 稳定 JSON payload 队列，worker 可独立运行。
- 前端 Vite/React 已切换为 API 驱动，支持用户切换、上传、状态查看、版本内容、反馈、导出和 review task 列表。
- `x-user-id` 只保留为 `ALLOW_DEV_USER_HEADER=true` 的开发/测试覆盖路径；production 必须关闭。
- 审计事件会持久化关键动作，并过滤 raw content、token、secret、authorization 等敏感字段。
- `/ready` 会检查 database、queue、storage，依赖不可用时返回 503。

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

CI 使用 `requirements-ci.txt` 安装已验证的测试/运行基础依赖；`requirements.txt` 中的 provider SDK 占位项需要在接入真实供应商包名前单独确认。

### 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，配置API密钥等
```

### 运行系统

```bash
python -m src.main
```

### 运行 API

```bash
uvicorn src.api.app:app --reload
```

前端默认请求 `http://localhost:8000`。如需修改 API 地址：

```bash
cd frontend
VITE_API_BASE=http://localhost:8000 npm run dev
```

### 生产化本地组合

```bash
cp .env.example .env
# 将 .env 中 SECRET_KEY 改成强随机值，并确认 MinIO bucket `study-agent` 已创建
docker compose config
docker compose up --build
```

- `APP_ENV=production` 会强制 `ALLOW_DEV_USER_HEADER=false`，并要求 PostgreSQL、Redis、S3/MinIO 配置完整。
- 空库首次启动会用 `BOOTSTRAP_ADMIN_EMAIL` 和 `BOOTSTRAP_ADMIN_PASSWORD` 创建首个 admin；已有用户时不会覆盖。
- `CORS_ORIGINS` 控制前端 dev server 到 API 的跨端口访问，默认包含 `localhost:5173`。
- Compose 不自动创建 MinIO bucket；bucket 缺失时 `/ready` 会保持 not ready。
- 默认 compose 中的 `SECRET_KEY` placeholder 会被应用拒绝，正式启动前必须通过 `.env` 或环境变量覆盖。

## 项目结构

```
newtest/
├── src/                    # 源代码
│   ├── agents/            # 智能体层
│   ├── api/               # FastAPI产品接口
│   ├── coordinator/       # 协调器层
│   ├── db/                # ORM模型和迁移
│   ├── knowledge/         # 知识处理
│   ├── parsers/           # 文档解析
│   ├── services/          # 服务层
│   ├── storage/           # local 与 S3-compatible 对象存储抽象
│   ├── workers/           # Redis payload worker 与内部处理/导出任务
│   └── utils/             # 工具函数
├── frontend/              # React内部Beta工作台
├── tests/                 # 测试
├── docs/                  # 文档
├── requirements.txt       # 依赖
└── README.md              # 项目说明
```

## 技术栈

- **LLM**：MiMo V2.5
- **PDF解析**：Marker
- **RAG**：LangChain + ChromaDB
- **知识图谱**：NetworkX
- **自进化**：DSPy + GEPA
- **Web框架**：FastAPI
- **前端**：Vite + React

## 开发指南

### 运行测试

```bash
pytest tests/ -v
```

### 前端构建

```bash
cd frontend
npm ci
npm run build
```

## 产品化边界

- `x-user-id` 只用于 development/test override；production 必须使用登录 token。
- 当前正式产品基础不包含企业 SSO、团队/组织租户、计费、配额或长期 refresh token。
- Redis/S3/PostgreSQL 已作为生产基础路径接入，但云上高可用、备份、密钥轮换和IaC仍属于后续上线工程。
- Compose 是 production-like 本地运行形态，不等同于云生产部署。
- 自进化能力仍处于设计/实验边界，不作为 MVP-8 产品运行前置。
- 普通 RAG、Graph RAG、Agentic RAG 的自动路由实验保留到 MVP-9，MVP-8 优先保证产品运行底座可靠。

### 代码格式化

```bash
black src/ tests/
isort src/ tests/
```

### 类型检查

```bash
mypy src/
```

## 许可证

MIT License
