# PPT/PDF转复习提纲和考试例题智能系统

基于DeepAgent的智能系统，能够将PPT/PDF文件转化为复习提纲和考试例题。

## 功能特性

- **多智能体协作**：8个专业智能体分工协作
- **Agentic RAG**：混合检索方案，支持知识点问答解释
- **记忆系统**：短期、长期、工作记忆三层架构
- **自进化系统**：基于DSPy + GEPA的反射式进化优化
- **多模态支持**：图表理解、公式识别、表格提取
- **内部Beta产品闭环**：支持轻量用户上传PPT/PDF、查看处理任务、读取提纲/题目版本、提交反馈、创建导出任务，并对文档/任务/导出执行owner隔离。

## 当前实现状态

当前代码已进入 MVP-7 内部Beta阶段：

- FastAPI 提供 `/api/documents`、`/api/jobs`、`/api/exports`、`/api/feedback`、`/api/review-tasks` 等产品接口。
- 数据库模型覆盖 documents、processing_jobs、content_versions、export_jobs、feedback、review_tasks、audit_events。
- 本地 `StorageBackend` 用于上传文件、导出产物和测试环境对象存储。
- 前端 Vite/React 已切换为 API 驱动，支持用户切换、上传、状态查看、版本内容、反馈、导出和 review task 列表。
- 内部Beta用户上下文通过 `x-user-id` 请求头传入；这是测试用轻量身份，不是正式认证系统。
- 审计事件会持久化关键动作，并过滤 raw content、token、secret、authorization 等敏感字段。

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

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
│   ├── storage/           # 本地对象存储抽象
│   ├── workers/           # 内部处理/导出任务
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

## 内部Beta边界

- 当前 `x-user-id` 只用于内部Beta owner隔离测试，不代表真实认证/授权。
- 当前队列是进程内/测试友好的实现，不是 Redis/Celery 生产队列。
- 当前对象存储默认使用本地文件系统，不是 S3/MinIO 生产对象存储。
- 当前前端用于内部产品闭环验证，不包含正式部署、计费、团队管理或企业级权限。
- 自进化能力仍处于设计/实验边界，不作为 MVP-7 产品闭环的运行前置。

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
