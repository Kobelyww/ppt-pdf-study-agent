# PPT/PDF转复习提纲和考试例题智能系统设计文档

## 0. 当前实现状态：MVP-8 正式产品基础

截至当前实现，项目已经从 MVP-7 内部Beta产品闭环推进到 MVP-8 Production Readiness Foundation。MVP-8 的目标不是继续扩大智能能力，而是先把正式产品运行底座补齐：身份、授权、数据库、队列、对象存储、健康检查、部署形态和CI。

- **认证**：新增 `POST /api/auth/login` 和 `GET /api/auth/me`。正式产品路径使用 HMAC-signed JWT-shaped Bearer token；`x-user-id` 只允许在 `ALLOW_DEV_USER_HEADER=true` 的开发/测试模式作为 override。
- **首个管理员**：production 空库启动时可通过 `BOOTSTRAP_ADMIN_EMAIL` 和 `BOOTSTRAP_ADMIN_PASSWORD` 创建首个 admin，已有用户时不会覆盖。
- **前端跨域**：API 通过 `CORS_ORIGINS` 显式允许 Vite dev server 等前端 origin 发送 `Authorization` 请求。
- **授权**：文档、任务、版本、导出、反馈、review task 和审计查询都以 authenticated user 为准。跨用户访问已有资源返回 `403`，不存在资源返回 `404`。
- **数据库**：生产目标为 PostgreSQL，Alembic 迁移包含 users auth 字段、review/audit/job/document 常用查询索引；SQLite 仍用于快速单元测试。
- **队列/Worker**：生产路径支持 Redis-backed stable JSON payload，worker 可独立运行；文档处理和导出任务带 owner 约束、失败落库、completed 幂等 guard 和 stale running job recovery。
- **对象存储**：`StorageBackend` 支持 local 与 S3/MinIO-compatible backend。API 和 worker 通过 storage URI 交互，上传/导出对象 key 做安全化处理。
- **可运维性**：`/health` 轻量返回组件状态，`/ready` 检查 database、queue、storage，依赖不可用时返回 `503`。
- **部署**：`docker-compose.yml` 提供 API、worker、PostgreSQL(pgvector)、Redis、MinIO 的 production-like 本地组合；`.env.example` 记录必要变量。
- **CI**：GitHub Actions 运行 backend `pytest -q`、`docker compose config` 和 frontend `npm run build`。
- **RAG边界**：普通 RAG、Graph RAG、Agentic RAG 的自动路由实验保留到 MVP-9；MVP-8 只确保未来实验能落在可靠产品底座上。

### 0.1 MVP-8 验收边界

- 用户必须能通过登录 token 调用产品 API。
- `APP_ENV=production` 必须禁止 `ALLOW_DEV_USER_HEADER`，并拒绝 placeholder `SECRET_KEY`。
- Compose 不自动创建 MinIO bucket；bucket 缺失应让 `/ready` 失败，而不是静默降级。
- Docker Compose 是 production-like 本地部署，不代表云上高可用生产部署。
- 本阶段不包含企业 SSO、组织/租户管理、计费、refresh token、Kubernetes、Terraform 或云托管运维。

## 0.2 历史基线：MVP-7 内部Beta产品闭环

截至当前实现，项目已经从纯后端能力原型推进到内部Beta产品闭环：

- **前端**：`frontend/` 使用 Vite + React，已接入真实 API，支持用户切换、PPT/PDF上传、文档列表、任务状态、提纲版本、题目版本、反馈、导出和 review task 列表。
- **后端 API**：`src/api/` 提供文档、任务、版本、提纲、题目、导出、反馈、review task 和健康检查接口。
- **数据库**：`src/db/models.py` 覆盖 documents、processing_jobs、parsed_sections、knowledge_points、outlines、questions、document_artifacts、content_versions、export_jobs、feedback、review_tasks、audit_events。
- **存储**：`src/storage/backend.py` 定义 `StorageBackend`，当前实现以本地文件系统作为内部Beta对象存储，所有 API/worker 通过 storage URI 访问文件。
- **任务处理**：`src/workers/tasks.py` 支持文档处理任务生成 normalized artifact、outline version 和 question_set version，并支持导出任务产物写入存储。
- **权限边界**：内部Beta通过请求头 `x-user-id` 建立轻量用户上下文，文档、任务、版本、反馈、review task 和导出围绕 owner 隔离。
- **审计**：关键动作会写入 `audit_events`，包括 document upload、job retry、export create、feedback create、review decision；审计 metadata 过滤 raw content、authorization、token、secret、password 等敏感内容。
- **验证**：后端测试覆盖 owner 隔离、审计过滤、上传/处理/版本/导出链路；前端通过 TypeScript + Vite build 验证 API 驱动界面。

### 0.1 内部Beta边界和非目标

- `x-user-id` 是内部Beta测试身份，不是正式认证；正式产品仍需要真实 auth、session、RBAC/ABAC 和租户模型。
- 当前队列为进程内/测试友好实现，生产化 Redis/Celery/RQ 不在 MVP-7 范围内。
- 当前对象存储为本地文件系统，生产 S3/MinIO、生命周期策略和多副本容灾不在 MVP-7 范围内。
- 当前导出任务验证 Markdown/JSON/LaTeX/PDF 的内容写入路径，正式 PDF 渲染、模板系统和下载签名 URL 仍需后续阶段实现。
- 自进化系统、Graph RAG/Agentic RAG 自动路由实验仍保留为后续能力，不作为内部Beta产品闭环上线前置。

## 1. 项目概述

### 1.1 项目目标
构建一个基于DeepAgent的智能系统，能够将PPT/PDF文件转化为复习提纲和考试例题，支持理工科内容，具备Agentic RAG系统、记忆系统和自进化系统。使用MiMo V2.5作为基座大模型，支持多模态解析。

### 1.2 核心特性
- **多智能体协作**：6个专业智能体分工协作
- **层级协调器架构**：主协调器管理子协调器
- **Agentic RAG系统**：支持理工科公式和图表的检索增强生成
- **记忆系统**：短期、长期、工作记忆三层架构
- **自进化系统**：Hermes 7步进化管道
- **Human-in-Loop**：混合评估模式
- **结构化输出**：支持Markdown、LaTeX、JSON格式
- **MCP服务集成**：按需集成各种服务

## 2. 系统架构

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    用户界面层 (UI Layer)                      │
├─────────────────────────────────────────────────────────────┤
│  CLI界面  │  Web界面  │  API接口  │  MCP客户端               │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    协调器层 (Coordinator Layer)               │
├─────────────────────────────────────────────────────────────┤
│  主协调器 (MainCoordinator)  │  子协调器 (SubCoordinators)   │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    智能体层 (Agent Layer)                     │
├─────────────────────────────────────────────────────────────┤
│  文档解析Agent │ 内容理解Agent │ 提纲生成Agent │ 例题生成Agent │
│  知识提取Agent │ 质量评估Agent │ 自进化Agent   │ 人工审核Agent │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    服务层 (Service Layer)                     │
├─────────────────────────────────────────────────────────────┤
│  RAG服务 │ 记忆服务 │ 进化服务 │ 评估服务 │ 工具服务         │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    基础设施层 (Infrastructure Layer)          │
├─────────────────────────────────────────────────────────────┤
│  LLM服务 │ 向量数据库 │ 文件系统 │ 缓存 │ 日志              │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 核心组件

#### 2.2.1 协调器层

**主协调器 (MainCoordinator)**
- **职责**：整体流程控制、子协调器管理、错误恢复
- **接口设计**：
  ```python
  class MainCoordinator:
      def __init__(self, sub_coordinators: dict[str, SubCoordinator], memory_service: MemoryService):
          self.sub_coordinators = sub_coordinators
          self.memory_service = memory_service
          self.state = CoordinatorState()
      
      async def invoke(self, request: CoordinatorRequest) -> CoordinatorResponse:
          """执行协调流程"""
          
      async def stream(self, request: CoordinatorRequest, callback: Callable) -> None:
          """流式执行协调流程"""
          
      async def checkpoint(self) -> None:
          """保存检查点"""
          
      def get_status(self) -> CoordinatorStatus:
          """获取协调器状态"""
  ```
- **状态管理**：
  ```python
  class CoordinatorState:
      def __init__(self):
          self.current_stage: str = "idle"
          self.completed_stages: list[str] = []
          self.results: dict[str, Any] = {}
          self.errors: list[Error] = []
          self.checkpoints: list[Checkpoint] = []
      
      def advance_stage(self) -> None:
          """推进到下一阶段"""
          
      def save_checkpoint(self) -> Checkpoint:
          """保存检查点"""
          
      def restore_checkpoint(self, checkpoint: Checkpoint) -> None:
          """恢复检查点"""
  ```

**子协调器**：
1. **文档处理协调器**：
   ```python
   class DocumentProcessingCoordinator(SubCoordinator):
       async def process(self, document: Document) -> ProcessedDocument:
           """处理文档：解析、提取、结构化"""
           
       async def parse_pdf(self, pdf_path: str) -> ParsedContent:
           """解析PDF文件"""
           
       async def parse_ppt(self, ppt_path: str) -> ParsedContent:
           """解析PPT文件"""
   ```

2. **内容生成协调器**：
   ```python
   class ContentGenerationCoordinator(SubCoordinator):
       async def generate(self, knowledge_graph: KnowledgeGraph, requirements: Requirements) -> GeneratedContent:
           """生成内容：提纲、例题"""
           
       async def generate_outline(self, knowledge_graph: KnowledgeGraph) -> Outline:
           """生成复习提纲"""
           
       async def generate_questions(self, knowledge_points: list[KnowledgePoint], difficulty: DifficultyLevel) -> list[Question]:
           """生成考试例题"""
   ```

3. **质量控制协调器**：
   ```python
   class QualityControlCoordinator(SubCoordinator):
       async def evaluate(self, content: GeneratedContent, source: ProcessedDocument) -> QualityReport:
           """评估内容质量"""
           
       async def review(self, content: GeneratedContent) -> ReviewResult:
           """人工审核"""
           
       async def approve(self, content: GeneratedContent) -> ApprovalResult:
           """批准内容"""
   ```

4. **自进化协调器**：
   ```python
   class SelfEvolutionCoordinator(SubCoordinator):
       async def optimize(self, target: str, eval_source: str = "synthetic") -> OptimizationResult:
           """优化目标（技能、工具描述、提示词）"""
           
       async def evaluate_optimization(self, before: BaselineMetrics, after: OptimizedMetrics) -> bool:
           """评估优化效果"""
           
       async def deploy_optimization(self, optimization: Optimization) -> DeploymentResult:
           """部署优化结果"""
   ```

#### 2.2.2 智能体层

**文档解析Agent**
- **输入**：PPT/PDF文件路径
- **输出**：结构化内容（章节、知识点、公式、图表）
- **工具**：PDF解析器、PPT解析器、OCR工具
- **接口设计**：
  ```python
  class DocumentParsingAgent(BaseAgent):
      role = "文档解析专家"
      system_prompt = """你是一个专业的文档解析专家，能够从PPT和PDF文件中提取结构化内容。
      你需要识别章节结构、知识点、数学公式、图表和表格。"""
      
      async def invoke(self, file_path: str) -> ParsedDocument:
          """解析文档"""
          
      async def extract_formulas(self, text: str) -> list[Formula]:
          """提取数学公式"""
          
      async def extract_tables(self, content: Any) -> list[Table]:
          """提取表格数据"""
  ```

**内容理解Agent**
- **输入**：结构化内容
- **输出**：知识图谱、概念关系、重点难点
- **工具**：NLP工具、概念提取器
- **接口设计**：
  ```python
  class ContentUnderstandingAgent(BaseAgent):
      role = "内容理解专家"
      system_prompt = """你是一个内容理解专家，能够从结构化内容中构建知识图谱。
      你需要识别概念、术语、公式，以及它们之间的关系。"""
      
      async def invoke(self, content: ParsedDocument) -> KnowledgeGraph:
          """构建知识图谱"""
          
      async def identify_concepts(self, text: str) -> list[Concept]:
          """识别概念"""
          
      async def extract_relationships(self, concepts: list[Concept]) -> list[Relationship]:
          """提取关系"""
  ```

**提纲生成Agent**
- **输入**：知识图谱、用户需求
- **输出**：复习提纲（Markdown/LaTeX格式）
- **工具**：模板引擎、格式转换器
- **接口设计**：
  ```python
  class OutlineGenerationAgent(BaseAgent):
      role = "提纲生成专家"
      system_prompt = """你是一个提纲生成专家，能够根据知识图谱生成结构清晰的复习提纲。
      你需要包含核心概念、关键公式、注意事项和复习建议。"""
      
      async def invoke(self, knowledge_graph: KnowledgeGraph, requirements: Requirements) -> Outline:
          """生成复习提纲"""
          
      async def format_outline(self, outline: Outline, format: OutputFormat) -> str:
          """格式化提纲"""
  ```

**例题生成Agent**
- **输入**：知识点、难度要求
- **输出**：考试例题（选择题、填空题、解答题）
- **工具**：题目生成器、答案验证器
- **接口设计**：
  ```python
  class QuestionGenerationAgent(BaseAgent):
      role = "例题生成专家"
      system_prompt = """你是一个例题生成专家，能够根据知识点生成高质量的考试例题。
      你需要生成不同类型的题目（选择题、填空题、解答题），并确保答案正确。"""
      
      async def invoke(self, knowledge_points: list[KnowledgePoint], difficulty: DifficultyLevel, question_type: QuestionType) -> Question:
          """生成考试例题"""
          
      async def verify_answer(self, question: Question, answer: Answer) -> bool:
          """验证答案正确性"""
  ```

**知识提取Agent**
- **输入**：原始文档内容
- **输出**：结构化知识点
- **工具**：实体识别、关系抽取
- **接口设计**：
  ```python
  class KnowledgeExtractionAgent(BaseAgent):
      role = "知识提取专家"
      system_prompt = """你是一个知识提取专家，能够从原始文档内容中提取结构化知识点。
      你需要识别核心概念、重要公式、关键步骤和注意事项。"""
      
      async def invoke(self, content: str) -> list[KnowledgePoint]:
          """提取知识点"""
          
      async def categorize_knowledge(self, points: list[KnowledgePoint]) -> dict[str, list[KnowledgePoint]]:
          """分类知识点"""
  ```

**质量评估Agent**
- **输入**：生成的内容
- **输出**：质量评分、改进建议
- **工具**：评估指标、对比分析
- **接口设计**：
  ```python
  class QualityEvaluationAgent(BaseAgent):
      role = "质量评估专家"
      system_prompt = """你是一个质量评估专家，能够评估生成内容的质量。
      你需要评估准确性、完整性、可读性，并提供改进建议。"""
      
      async def invoke(self, content: GeneratedContent, source: ProcessedDocument) -> EvaluationResult:
          """评估内容质量"""
          
      async def suggest_improvements(self, evaluation: EvaluationResult) -> list[Improvement]:
          """提供改进建议"""
  ```

**自进化Agent**
- **输入**：用户反馈、质量评估
- **输出**：优化的提示词、改进的策略
- **工具**：DSPy + GEPA优化器
- **接口设计**：
  ```python
  class SelfEvolutionAgent(BaseAgent):
      role = "自进化专家"
      system_prompt = """你是一个自进化专家，能够使用DSPy + GEPA优化系统性能。
      你需要分析当前问题，生成改进候选，评估效果，并部署最佳方案。"""
      
      async def invoke(self, target: str, eval_source: str = "synthetic") -> EvolutionResult:
          """执行自进化"""
          
      async def analyze_current_issues(self, target: str) -> list[Issue]:
          """分析当前问题"""
          
      async def generate_candidates(self, issues: list[Issue]) -> list[Candidate]:
          """生成改进候选"""
  ```

**人工审核Agent**
- **输入**：待审核内容
- **输出**：审核结果、修改建议
- **工具**：审核界面、反馈收集
- **接口设计**：
  ```python
  class HumanReviewAgent(BaseAgent):
      role = "人工审核协调员"
      system_prompt = """你是一个人工审核协调员，能够协调人工审核流程。
      你需要收集审核意见，整合反馈，并提供修改建议。"""
      
      async def invoke(self, content: GeneratedContent) -> ReviewResult:
          """协调人工审核"""
          
      async def collect_feedback(self, content: GeneratedContent) -> list[Feedback]:
          """收集审核反馈"""
          
      async def integrate_feedback(self, feedback: list[Feedback]) -> IntegratedFeedback:
          """整合反馈"""
  ```

#### 2.2.3 服务层

**RAG服务（混合方案：普通RAG + Agentic RAG）**

**架构设计**：
```
┌─────────────────────────────────────────────────────────────┐
│                    查询处理层 (Query Processing)             │
├─────────────────────────────────────────────────────────────┤
│  查询分析  │  查询重写  │  查询澄清  │  对话历史摘要          │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    检索策略层 (Retrieval Strategy)            │
├─────────────────────────────────────────────────────────────┤
│  普通RAG检索  │  Agentic RAG检索  │  混合检索策略            │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    知识处理层 (Knowledge Processing)          │
├─────────────────────────────────────────────────────────────┤
│  知识图谱  │  知识点提取  │  知识点问答解释  │  上下文压缩      │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    生成层 (Generation Layer)                  │
├─────────────────────────────────────────────────────────────┤
│  回答生成  │  引用生成  │  质量评估  │  自我纠正              │
└─────────────────────────────────────────────────────────────┘
```

**核心组件**：

1. **查询处理模块**：
   ```python
   class QueryProcessor:
       def __init__(self, llm, conversation_memory):
           self.llm = llm
           self.conversation_memory = conversation_memory
       
       async def analyze_query(self, query: str) -> QueryAnalysis:
           """分析查询：判断是否清晰、是否需要澄清"""
           
       async def rewrite_query(self, query: str, context: str) -> list[str]:
           """重写查询：将模糊查询转换为清晰的检索查询"""
           
       async def clarify_query(self, query: str) -> str:
           """澄清查询：当查询不明确时请求用户澄清"""
   ```

2. **检索策略模块**：
   ```python
   class RetrievalStrategy:
       def __init__(self, vector_store, knowledge_graph):
           self.vector_store = vector_store
           self.knowledge_graph = knowledge_graph
       
       async def普通_rag_retrieval(self, query: str, top_k: int = 5) -> list[Chunk]:
           """普通RAG检索：基于向量相似度"""
           
       async def agentic_rag_retrieval(self, query: str, max_iterations: int = 3) -> AgenticResult:
           """Agentic RAG检索：多轮迭代检索+自我纠正"""
           
       async def hybrid_retrieval(self, query: str, strategy: str = "auto") -> HybridResult:
           """混合检索：根据查询复杂度自动选择策略"""
   ```

3. **知识点问答解释模块**：
   ```python
   class KnowledgeQAExplainer:
       def __init__(self, llm, knowledge_graph):
           self.llm = llm
           self.knowledge_graph = knowledge_graph
       
       async def explain_knowledge_point(self, point: KnowledgePoint, context: str) -> Explanation:
           """解释单个知识点"""
           
       async def explain_with_examples(self, point: KnowledgePoint, examples: list[Example]) -> Explanation:
           """通过示例解释知识点"""
           
       async def explain_prerequisites(self, point: KnowledgePoint) -> PrerequisiteExplanation:
           """解释前置知识"""
           
       async def explain_connections(self, point: KnowledgePoint) -> ConnectionExplanation:
           """解释知识点之间的联系"""
   ```

**检索策略选择逻辑**：
```python
class RetrievalStrategySelector:
    def __init__(self, llm):
        self.llm = llm
    
    async def select_strategy(self, query: str, query_type: str) -> str:
        """根据查询类型选择检索策略"""
        if query_type == "simple_fact":
            return "普通RAG"  # 简单事实查询
        elif query_type == "complex_reasoning":
            return "Agentic RAG"  # 复杂推理查询
        elif query_type == "knowledge_explanation":
            return "混合检索+知识图谱"  # 知识点解释
        else:
            return "自动选择"
```

**Agentic RAG工作流程**：
```
用户查询 → 查询分析 → 查询重写 → 检索策略选择
    ↓
[普通RAG路径] → 向量检索 → 相关性过滤 → 上下文构建 → 回答生成
    ↓
[Agentic RAG路径] → 多轮检索 → 自我纠正 → 上下文压缩 → 回答生成
    ↓
[知识点问答路径] → 知识图谱查询 → 知识点提取 → 解释生成 → 示例关联
    ↓
回答质量评估 → 引用验证 → 最终回答
```

**上下文压缩机制**：
```python
class ContextCompressor:
    def __init__(self, llm, max_tokens: int = 4000):
        self.llm = llm
        self.max_tokens = max_tokens
    
    async def compress_context(self, context: str, query: str) -> str:
        """压缩上下文：保留与查询相关的关键信息"""
        
    async def summarize_findings(self, findings: list[Finding]) -> str:
        """总结发现：将多个检索结果压缩为摘要"""
```

**知识点问答解释功能**：
```python
class KnowledgeQAService:
    def __init__(self, knowledge_graph, llm, rag_service):
        self.knowledge_graph = knowledge_graph
        self.llm = llm
        self.rag_service = rag_service
    
    async def answer_knowledge_question(self, question: str) -> KnowledgeAnswer:
        """回答知识点问题"""
        # 1. 分析问题类型
        question_type = await self.analyze_question_type(question)
        
        # 2. 选择回答策略
        if question_type == "definition":
            return await self.explain_definition(question)
        elif question_type == "example":
            return await self.provide_examples(question)
        elif question_type == "connection":
            return await self.explain_connections(question)
        elif question_type == "prerequisite":
            return await self.explain_prerequisites(question)
        else:
            return await self.general_knowledge_qa(question)
    
    async def explain_definition(self, question: str) -> KnowledgeAnswer:
        """解释定义"""
        
    async def provide_examples(self, question: str) -> KnowledgeAnswer:
        """提供示例"""
        
    async def explain_connections(self, question: str) -> KnowledgeAnswer:
        """解释知识点联系"""
        
    async def explain_prerequisites(self, question: str) -> KnowledgeAnswer:
        """解释前置知识"""
```

**质量评估与自我纠正**：
```python
class QualityEvaluator:
    def __init__(self, llm):
        self.llm = llm
    
    async def evaluate_answer(self, answer: str, context: str, query: str) -> EvaluationResult:
        """评估回答质量"""
        
    async def self_correct(self, answer: str, evaluation: EvaluationResult) -> str:
        """自我纠正：根据评估结果改进回答"""
        
    async def verify_citations(self, answer: str, sources: list[Source]) -> bool:
        """验证引用准确性"""
```

**记忆服务（三层架构）**
- **短期记忆 (STM)**：
  ```python
  class ShortTermMemory:
      def __init__(self, max_tokens: int = 50000):
          self.compressed_prefix: str = ""  # LLM压缩的旧消息摘要
          self.recent_window: list[Message] = []  # 最近N条完整消息
          self.max_tokens = max_tokens
      
      def add_message(self, message: Message) -> None:
          """添加消息，自动检测压缩触发"""
          
      def get_context(self, max_tokens: int = 3000) -> str:
          """获取格式化上下文（压缩前缀 + 最近消息）"""
          
      def force_compress(self) -> None:
          """手动触发压缩"""
  ```
- **长期记忆 (LTM)**：
  ```python
  class LongTermMemory:
      def __init__(self, db_path: str):
          self.db = sqlite3.connect(db_path)
          self._init_fts5()  # 全文搜索索引
      
      def store(self, memory: MemoryEntry) -> None:
          """存储记忆条目（含scope、importance、model_types）"""
          
      def recall(self, query: str, top_k: int = 3) -> list[MemoryEntry]:
          """复合重排序召回：FTS5 rank + 时间衰减 + 访问热度 + 重要性"""
          
      def search_by_scope(self, scope: str, query: str) -> list[MemoryEntry]:
          """按scope前缀搜索"""
  ```
- **工作记忆 (WM)**：
  ```python
  class WorkingMemory:
      def __init__(self):
          self.document_content: dict[str, Any] = {}  # 当前文档结构化内容
          self.knowledge_graph_state: Graph = None  # 知识图谱临时状态
          self.intermediate_results: dict[str, Any] = {}  # 生成过程中间数据
      
      def update_document_content(self, doc_id: str, content: Any) -> None:
          """更新当前文档内容"""
          
      def get_intermediate_result(self, key: str) -> Any:
          """获取中间结果"""
  ```

**进化服务（基于Hermes架构）**
- **核心功能**：基于DSPy + GEPA的反射式进化优化
- **接口设计**：
  ```python
  class EvolutionService:
      def __init__(self, dspy_config, gepa_optimizer):
          self.dspy_config = dspy_config
          self.gepa_optimizer = gepa_optimizer
      
      async def evolve_skill(self, skill_name: str, eval_source: str = "synthetic") -> EvolutionResult:
          """进化技能文件"""
          
      async def evolve_tool_descriptions(self, iterations: int = 5) -> EvolutionResult:
          """进化工具描述"""
          
      async def evolve_prompt_section(self, section: str, iterations: int = 5) -> EvolutionResult:
          """进化系统提示词部分"""
  ```
- **评估数据集构建**：
  ```python
  class EvalDatasetBuilder:
      def __init__(self, session_db, llm_judge):
          self.session_db = session_db
          self.llm_judge = llm_judge
      
      def build_from_synthetic(self, skill_name: str, num_examples: int = 20) -> EvalDataset:
          """合成生成评估数据集"""
          
      def build_from_session_history(self, skill_name: str) -> EvalDataset:
          """从会话历史挖掘评估数据集"""
          
      def split_dataset(self, dataset: EvalDataset) -> tuple[EvalDataset, EvalDataset, EvalDataset]:
          """分割为训练/验证/测试集"""
  ```
- **约束验证**：
  ```python
  class ConstraintValidator:
      def validate_test_suite(self, variant: Variant) -> bool:
          """验证是否通过完整测试套件"""
          
      def validate_size_limits(self, variant: Variant) -> bool:
          """验证字符/令牌限制"""
          
      def validate_semantic_preservation(self, original: str, evolved: str) -> bool:
          """验证语义保留"""
  ```

**评估服务（多维度评估）**
- **核心功能**：内容质量评估、用户满意度评估、学习效果评估
- **接口设计**：
  ```python
  class EvaluationService:
      def __init__(self, llm_judge, metrics_calculator):
          self.llm_judge = llm_judge
          self.metrics_calculator = metrics_calculator
      
      async def evaluate_outline(self, outline: Outline, source_content: str) -> EvaluationResult:
          """评估提纲质量"""
          
      async def evaluate_questions(self, questions: list[Question], source_content: str) -> EvaluationResult:
          """评估例题质量"""
          
      async def evaluate_user_satisfaction(self, feedback: UserFeedback) -> SatisfactionScore:
          """评估用户满意度"""
  ```
- **评估指标**：
  ```python
  class EvaluationMetrics:
      def accuracy_score(self, generated: str, reference: str) -> float:
          """准确性评分"""
          
      def completeness_score(self, outline: Outline, knowledge_points: list[str]) -> float:
          """完整性评分"""
          
      def readability_score(self, text: str) -> float:
          """可读性评分"""
          
      def difficulty_level(self, question: Question) -> DifficultyLevel:
          """难度级别评估"""
  ```

**工具服务（MCP集成）**
- **核心功能**：提供各种工具供智能体调用
- **工具列表**：
  ```python
  class ToolService:
      def __init__(self):
          self.tools = {
              "pdf_parser": PDFParserTool(),
              "ppt_parser": PPTParserTool(),
              "ocr_tool": OCRTool(),
              "knowledge_graph": KnowledgeGraphTool(),
              "template_engine": TemplateEngineTool(),
              "format_converter": FormatConverterTool(),
          }
      
      def get_tool(self, tool_name: str) -> Tool:
          """获取工具实例"""
          
      def list_tools(self) -> list[ToolInfo]:
          """列出所有可用工具"""
  ```
- **工具接口**：
  ```python
  class Tool(ABC):
      @abstractmethod
      def name(self) -> str:
          """工具名称"""
          
      @abstractmethod
      def description(self) -> str:
          """工具描述"""
          
      @abstractmethod
      async def execute(self, **kwargs) -> ToolResult:
          """执行工具"""
  ```

### 2.3 数据流

```
用户上传PPT/PDF
    ↓
文档解析Agent提取内容
    ↓
内容理解Agent构建知识图谱
    ↓
知识提取Agent生成结构化知识点
    ↓
提纲生成Agent生成复习提纲
    ↓
例题生成Agent生成考试例题
    ↓
质量评估Agent评估质量
    ↓
人工审核Agent审核（可选）
    ↓
输出最终结果

查询流程：
用户查询 → 查询分析 → 查询重写 → 检索策略选择
    ↓
[普通RAG路径] → 向量检索 → 相关性过滤 → 上下文构建 → 回答生成
    ↓
[Agentic RAG路径] → 多轮检索 → 自我纠正 → 上下文压缩 → 回答生成
    ↓
[知识点问答路径] → 知识图谱查询 → 知识点提取 → 解释生成 → 示例关联
    ↓
回答质量评估 → 引用验证 → 最终回答
```

## 3. 详细设计

### 3.1 文档解析模块（改进方案）

**问题分析**：
传统PDF/PPT解析工具（如PyMuPDF、python-pptx）在处理带图表的文档时，会得到混乱的结构，因为：
1. 无法正确识别文档的逻辑结构（标题、段落、列表）
2. 图表和文本混合在一起，难以分离
3. 表格结构被破坏，无法保持原有的行列关系
4. 数学公式被拆分成碎片，无法正确识别

**改进方案：基于Marker和Docling的智能解析**

**PDF解析（使用Marker）**：
- **核心优势**：基于深度学习的PDF解析，能够准确识别文档结构
- **功能特点**：
  - 自动识别标题、段落、列表、表格、图表
  - 保持文档的逻辑结构
  - 准确提取数学公式（LaTeX格式）
  - 识别并分离图表和文本
  - 支持OCR识别扫描版PDF
- **接口设计**：
  ```python
  class MarkerPDFParser:
      def __init__(self, model_name: str = "marker"):
          self.model_name = model_name
      
      async def parse(self, pdf_path: str) -> StructuredDocument:
          """使用Marker解析PDF，返回结构化文档"""
          
      async def extract_with_structure(self, pdf_path: str) -> DocumentWithStructure:
          """提取文档结构：标题层级、段落、表格、图表"""
          
      async def extract_formulas(self, pdf_path: str) -> list[Formula]:
          """提取数学公式（LaTeX格式）"""
          
      async def extract_tables(self, pdf_path: str) -> list[Table]:
          """提取表格数据（保持结构）"""
          
      async def extract_figures(self, pdf_path: str) -> list[Figure]:
          """提取图表和图像"""
  ```

**PPT解析（使用python-pptx + 增强处理）**：
- **核心改进**：增强python-pptx，添加结构识别和图表分离
- **功能特点**：
  - 识别幻灯片的逻辑结构（标题、内容、图表）
  - 分离文本和图表
  - 保持幻灯片的顺序和层级关系
  - 提取图表中的数据和描述
- **接口设计**：
  ```python
  class EnhancedPPTParser:
      def __init__(self):
          self.base_parser = python_pptx  # 使用python-pptx作为基础
      
      async def parse(self, ppt_path: str) -> StructuredPresentation:
          """解析PPT，返回结构化演示文稿"""
          
      async def extract_slides_with_structure(self, ppt_path: str) -> list[SlideWithStructure]:
          """提取幻灯片结构：标题、内容、图表"""
          
      async def extract_charts_from_slides(self, ppt_path: str) -> list[Chart]:
          """从幻灯片中提取图表"""
          
      async def extract_images_from_slides(self, ppt_path: str) -> list[Image]:
          """从幻灯片中提取图像"""
  ```

**文档结构化输出**：
```python
class StructuredDocument:
    def __init__(self):
        self.title: str = ""
        self.sections: list[Section] = []
        self.tables: list[Table] = []
        self.figures: list[Figure] = []
        self.formulas: list[Formula] = []
        self.metadata: dict[str, Any] = {}

class Section:
    def __init__(self):
        self.level: int = 1  # 标题层级
        self.title: str = ""
        self.content: str = ""
        self.subsections: list[Section] = []
        self.tables: list[Table] = []
        self.figures: list[Figure] = []
        self.formulas: list[Formula] = []

class Table:
    def __init__(self):
        self.headers: list[str] = []
        self.rows: list[list[str]] = []
        self.caption: str = ""
        self.page_number: int = 0

class Figure:
    def __init__(self):
        self.image_path: str = ""
        self.caption: str = ""
        self.description: str = ""  # 使用多模态LLM生成的描述
        self.page_number: int = 0

class Formula:
    def __init__(self):
        self.latex: str = ""
        self.description: str = ""
        self.page_number: int = 0
  ```

**多模态内容处理**：
```python
class MultimodalContentProcessor:
    def __init__(self, llm_config: LLMConfig):
        self.llm_config = llm_config
    
    async def process_figure(self, figure: Figure) -> ProcessedFigure:
        """处理图表：使用多模态LLM生成描述"""
        model = self.llm_config.get_model_for_task("image_understanding")
        # 使用MiMo V2.5的多模态能力生成图表描述
        
    async def process_table_image(self, image_path: str) -> TableData:
        """处理表格图像，提取结构化数据"""
        
    async def process_formula_image(self, image_path: str) -> LaTeXFormula:
        """处理公式图像，识别LaTeX公式"""
  ```

**解析策略选择**：
```python
class ParserSelector:
    def __init__(self):
        self.parsers = {
            "pdf_marker": MarkerPDFParser(),
            "pdf_pymupdf": PyMuPDFParser(),  # 备用方案
            "ppt_enhanced": EnhancedPPTParser(),
            "ppt_base": python_pptx,  # 备用方案
        }
    
    def select_parser(self, file_path: str, has_figures: bool = True) -> str:
        """根据文件类型和内容选择解析器"""
        if file_path.endswith(".pdf"):
            if has_figures:
                return "pdf_marker"  # 带图表的PDF使用Marker
            else:
                return "pdf_pymupdf"  # 纯文本PDF使用PyMuPDF
        elif file_path.endswith(".pptx"):
            return "ppt_enhanced"  # PPT使用增强解析器
        else:
            raise ValueError(f"Unsupported file type: {file_path}")
  ```

**深度学习模型调用方案**：

**Marker开源确认**：
- **项目地址**：https://github.com/datalab-to/marker
- **许可证**：GNU General Public License v3.0（开源）
- **本地部署**：✅ 支持本地部署
- **星标数**：36,058（非常活跃的开源项目）
- **主要功能**：将PDF转换为Markdown和JSON，准确率高

**方案一：本地部署（推荐用于生产环境）**
```python
class LocalMarkerModel:
    def __init__(self, model_path: str = "marker-model"):
        self.model_path = model_path
        self.model = None
    
    def load_model(self):
        """加载Marker模型"""
        # 安装方式：pip install marker-pdf
        from marker import load_model
        self.model = load_model(self.model_path)
    
    async def parse_pdf(self, pdf_path: str) -> StructuredDocument:
        """使用本地Marker模型解析PDF"""
        if self.model is None:
            self.load_model()
        
        from marker.convert import convert_single_pdf
        rendered = convert_single_pdf(pdf_path, self.model)
        
        return StructuredDocument(
            title=rendered.metadata.get("title", ""),
            sections=self._extract_sections(rendered),
            tables=rendered.tables,
            figures=rendered.images,
            formulas=rendered.equations
        )
```

**方案二：API调用（推荐用于开发测试）**
```python
class MarkerAPIClient:
    def __init__(self, api_key: str, api_url: str = "https://api.marker.com"):
        self.api_key = api_key
        self.api_url = api_url
    
    async def parse_pdf(self, pdf_path: str) -> StructuredDocument:
        """通过API调用Marker解析PDF"""
        import aiohttp
        
        with open(pdf_path, "rb") as f:
            files = {"file": f}
            data = {"api_key": self.api_key}
            
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.api_url}/parse", files=files, data=data) as response:
                    result = await response.json()
                    
        return StructuredDocument(
            title=result.get("title", ""),
            sections=self._parse_sections(result.get("sections", [])),
            tables=result.get("tables", []),
            figures=result.get("figures", []),
            formulas=result.get("formulas", [])
        )
```

**方案三：Docker容器化部署**
```python
class MarkerDockerClient:
    def __init__(self, container_name: str = "marker-service"):
        self.container_name = container_name
    
    async def parse_pdf(self, pdf_path: str) -> StructuredDocument:
        """通过Docker容器调用Marker"""
        import docker
        
        client = docker.from_env()
        
        # 挂载PDF文件到容器
        volumes = {pdf_path: {"bind": "/input/document.pdf", "mode": "ro"}}
        
        # 运行容器
        container = client.containers.run(
            "marker:latest",
            command="/input/document.pdf",
            volumes=volumes,
            detach=True,
            remove=True
        )
        
        # 等待完成并获取结果
        result = container.wait()
        logs = container.logs().decode()
        
        return self._parse_result(logs)
```

**方案四：混合调用策略**
```python
class HybridMarkerClient:
    def __init__(self, local_model_path: str, api_key: str, api_url: str):
        self.local_client = LocalMarkerModel(local_model_path)
        self.api_client = MarkerAPIClient(api_key, api_url)
        self.docker_client = MarkerDockerClient()
    
    async def parse_pdf(self, pdf_path: str, strategy: str = "auto") -> StructuredDocument:
        """混合调用策略：根据情况选择最佳方案"""
        if strategy == "auto":
            # 自动选择：优先本地，失败则API，最后Docker
            try:
                return await self.local_client.parse_pdf(pdf_path)
            except Exception:
                try:
                    return await self.api_client.parse_pdf(pdf_path)
                except Exception:
                    return await self.docker_client.parse_pdf(pdf_path)
        elif strategy == "local":
            return await self.local_client.parse_pdf(pdf_path)
        elif strategy == "api":
            return await self.api_client.parse_pdf(pdf_path)
        elif strategy == "docker":
            return await self.docker_client.parse_pdf(pdf_path)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")
```

**模型加载和管理**：
```python
class ModelManager:
    def __init__(self):
        self.models = {}
        self.model_configs = {
            "marker": {"type": "local", "path": "marker-model", "gpu": True},
            "ocr": {"type": "api", "url": "https://api.ocr.com", "key": ""},
            "multimodal": {"type": "local", "path": "mimo-v2.5", "gpu": True}
        }
    
    def load_model(self, model_name: str):
        """加载模型"""
        config = self.model_configs.get(model_name)
        if config["type"] == "local":
            self._load_local_model(model_name, config)
        elif config["type"] == "api":
            self._init_api_client(model_name, config)
    
    def _load_local_model(self, model_name: str, config: dict):
        """加载本地模型"""
        if model_name == "marker":
            from marker import load_model
            self.models[model_name] = load_model(config["path"])
        elif model_name == "multimodal":
            # 加载MiMo V2.5多模态模型
            self.models[model_name] = self._load_mimo_model(config["path"])
    
    def _load_mimo_model(self, model_path: str):
        """加载MiMo V2.5模型"""
        # 根据模型格式加载（PyTorch、ONNX、TensorRT等）
        pass
```

**性能优化**：
```python
class PerformanceOptimizer:
    def __init__(self):
        self.cache = {}
        self.batch_size = 8
    
    async def parse_with_cache(self, pdf_path: str) -> StructuredDocument:
        """带缓存的解析"""
        cache_key = self._get_cache_key(pdf_path)
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        result = await self.parse_pdf(pdf_path)
        self.cache[cache_key] = result
        return result
    
    async def batch_parse(self, pdf_paths: list[str]) -> list[StructuredDocument]:
        """批量解析多个PDF"""
        results = []
        for i in range(0, len(pdf_paths), self.batch_size):
            batch = pdf_paths[i:i + self.batch_size]
            batch_results = await asyncio.gather(*[self.parse_pdf(p) for p in batch])
            results.extend(batch_results)
        return results
```

**与传统方案的对比**：
| 特性 | 传统方案（PyMuPDF/python-pptx） | 改进方案（Marker+增强PPT） |
|------|--------------------------------|---------------------------|
| 文档结构识别 | ❌ 混乱 | ✅ 准确识别 |
| 图表处理 | ❌ 混合在文本中 | ✅ 分离并描述 |
| 表格提取 | ❌ 结构破坏 | ✅ 保持结构 |
| 公式识别 | ❌ 碎片化 | ✅ LaTeX格式 |
| 多模态支持 | ❌ 无 | ✅ 图表描述 |

### 3.2 内容理解模块

**知识图谱构建**：
- 实体识别：概念、术语、公式
- 关系抽取：包含、依赖、相似
- 图谱存储：Neo4j或内存图结构

**重点难点分析**：
- 基于文档结构识别重点内容
- 基于知识点依赖关系识别难点
- 基于考试频率识别高频考点

### 3.3 提纲生成模块

**提纲结构**：
```
章节标题
├── 知识点1
│   ├── 核心概念
│   ├── 关键公式
│   └── 注意事项
├── 知识点2
│   ├── 核心概念
│   ├── 关键公式
│   └── 注意事项
└── 复习建议
    ├── 重点内容
    ├── 难点解析
    └── 学习方法
```

**格式支持**：
- Markdown格式：通用性强，易于编辑
- LaTeX格式：支持复杂公式，适合理工科
- JSON格式：程序化处理，支持API调用

### 3.4 例题生成模块

**题目类型**：
1. **选择题**：单选、多选
2. **填空题**：单空、多空
3. **解答题**：计算题、证明题、应用题

**题目生成策略**：
- 基于知识点生成基础题目
- 基于公式生成计算题目
- 基于概念生成理解题目
- 基于应用场景生成综合题目

**质量控制**：
- 答案正确性验证
- 难度级别控制
- 题目多样性保证
- 避免重复题目

### 3.5 记忆系统设计

**短期记忆 (STM)**：
- 存储当前会话上下文
- 保存处理中间结果
- 支持上下文压缩

**长期记忆 (LTM)**：
- 用户偏好和学习历史
- 成功的处理策略
- 高质量的生成模板

**工作记忆 (WM)**：
- 当前文档的结构化内容
- 知识图谱的临时状态
- 生成过程中的中间数据

### 3.6 自进化系统设计（基于Hermes Agent Self-Evolution架构）

**核心架构**：基于DSPy + GEPA（Genetic-Pareto Prompt Evolution）的反射式进化优化

**优化循环**：
```
选择优化目标 → 构建评估数据集 → 包装为DSPy模块 → 运行优化器 → 评估比较 → 部署（需人工批准）
```

**三层优化目标**：

#### 第一层：技能文件优化（最高价值，最低风险）
- **目标**：优化SKILL.md文件（程序化指令）
- **方法**：将技能文本包装为DSPy模块，通过batch_runner在测试任务上评估，使用GEPA进化
- **评估数据来源**：
  - 合成生成：使用强模型（如Claude Opus）生成测试用例
  - 会话挖掘：从历史会话中提取真实使用案例
  - 人工策划：高质量技能的手工测试用例
- **约束条件**：
  - 技能文件大小≤15KB
  - 必须通过完整测试套件
  - 保持语义一致性

#### 第二层：工具描述优化（中等价值，低风险）
- **目标**：优化工具schema中的description字段
- **方法**：GEPA进化描述文本，评估工具选择准确性
- **评估数据来源**：
  - 合成工具选择数据集：（任务描述，正确工具，正确参数）三元组
  - 会话挖掘：识别工具误选模式
  - 基准测试：从TBLite等基准测试中提取工具选择失败案例
- **约束条件**：
  - 工具描述≤500字符
  - 参数描述≤200字符
  - 必须保持事实准确性
  - 模式结构（参数名、类型）冻结，只进化文本

#### 第三层：系统提示词优化（高价值，较高风险）
- **目标**：优化系统提示词的各个部分（人格、策略、格式指令）
- **方法**：将提示词部分参数化为DSPy Signature，使用GEPA独立优化
- **可优化部分**：
  - 默认代理身份（人格、行为特征）
  - 记忆指导（何时保存、保存什么）
  - 会话搜索指导（触发条件）
  - 技能指导（触发条件）
- **约束条件**：
  - 每个部分大小增加不超过20%
  - 总系统提示词必须在模型提示词缓存边界内
  - 必须保持核心特征（有帮助、直接、承认不确定性）

**进化引擎**：
| 引擎 | 优化目标 | 许可证 | 集成方式 |
|------|----------|--------|----------|
| DSPy + GEPA | 技能、提示词、工具描述 | MIT | 原生Python，主要引擎 |
| Darwinian Evolver | 代码文件、工具实现 | AGPL v3 | 仅外部CLI |
| DSPy MIPROv2 | 少样本示例、指令文本 | MIT | 原生Python，备用优化器 |

**约束条件和防护栏**：
1. **完整测试套件**：pytest tests/ -q 必须100%通过
2. **字符/令牌限制**：技能≤15KB，工具描述≤500字符
3. **提示词缓存兼容性**：永不热交换到活跃对话中
4. **语义保留**：进化内容不得偏离原始目的
5. **通过PR部署**：永不直接提交，所有变更需人工审查

**评估数据集构建**：
```
会话数据库（真实对话）→ 评估数据集构建器 → DSPy模块包装 → GEPA优化器
```

**基准测试作为适应度信号**：
| 基准测试 | 测试内容 | 速度 | 在自进化中的角色 |
|----------|----------|------|------------------|
| TBLite | 编码/系统管理（100个任务） | ~1-2小时 | 主要回归门控 |
| YC-Bench | 长期战略一致性（100-500轮） | ~3-6小时 | 一致性检查 |

**部署流程**：
```bash
git checkout -b evolve/<target>-<timestamp>
# 应用进化变更
git add <files>
git commit -m "evolve: <target> — score improved X% → Y%"
git push -u origin evolve/<target>-<timestamp>
gh pr create --title "evolve: <target>" --body "<metrics, diff, comparison>"
```

**成本估算**：
- GEPA优化：每次运行~$2-10
- Darwinian Evolver：每次任务~$2-9
- 建议从小规模评估数据集开始（10-20个示例）

### 3.7 Human-in-Loop设计

**混合评估模式**：
1. **自动评估**：系统自动评估内容质量
2. **人工审核**：关键节点插入人工审核
3. **用户反馈**：收集用户使用反馈
4. **专家评审**：邀请领域专家评审

**审核节点**：
- 文档解析后：确认内容提取准确性
- 提纲生成后：确认结构合理性
- 例题生成后：确认题目质量
- 最终输出前：确认整体质量

### 3.8 MCP服务集成

**基础MCP服务**：
- 文件系统服务：读写文件
- 向量数据库服务：存储和检索向量
- 缓存服务：提高性能

**文档处理MCP**：
- PDF解析服务：提取PDF内容
- PPT解析服务：提取PPT内容
- OCR服务：识别扫描文档

**知识图谱MCP**：
- 实体识别服务：识别概念和术语
- 关系抽取服务：提取概念关系
- 图谱查询服务：查询知识图谱

**学术搜索MCP**：
- 论文检索服务：搜索相关论文
- 公式识别服务：识别数学公式
- 参考文献服务：管理参考文献

**评估MCP**：
- 质量评估服务：评估内容质量
- 用户反馈服务：收集用户反馈
- 学习分析服务：分析学习效果

## 4. 实现计划

### 4.1 第一阶段：核心框架（2周）
- 搭建项目结构
- 实现主协调器和基础接口
- 实现文档解析Agent
- 实现基础RAG服务
- 配置MiMo V2.5基座大模型
- 实现多模态处理接口（图像、表格、公式识别）

### 4.2 第二阶段：内容生成（3周）
- 实现内容理解Agent
- 实现提纲生成Agent
- 实现例题生成Agent
- 实现记忆系统

### 4.3 第三阶段：质量控制（2周）
- 实现质量评估Agent
- 实现人工审核Agent
- 实现评估服务
- 集成Human-in-Loop

### 4.4 第四阶段：自进化系统（3周）
**第一周：基础架构**
- 安装DSPy + GEPA，验证环境
- 实现技能-as-DSPy模块包装器
- 实现评估数据集生成器（合成生成为主）
- 实现GEPA优化运行器

**第二周：技能进化**
- 选择2-3个目标技能进行进化（如文档解析、提纲生成、例题生成）
- 为每个技能生成评估数据集（15-30个示例）
- 运行GEPA优化（每个技能5-10次迭代）
- 比较基线与进化版本在保留测试集上的表现

**第三周：验证与部署**
- 运行基准测试（TBLite快速子集）验证无回归
- 人工审查进化后的技能差异
- 创建改进PR，包含完整指标和对比
- 文档化优化流程，使其可重用于其他技能

### 4.5 第五阶段：测试和部署（1周）
- 单元测试
- 集成测试
- 性能测试
- 部署和文档

## 5. 技术选型

### 5.1 核心依赖
- **基座大模型**：MiMo V2.5（多模态能力：图像、表格、公式识别）
- **对话模型**：DeepSeek V4（推理能力：逻辑推理、数学推理、代码生成）
- **Embedding模型**：阿里云百练 text-embedding-v2（向量化，Dim=1536）
- **智能模型路由器**：根据任务特点自动选择最优模型

**模型路由策略**：
| 任务类型 | 推荐模型 | 原因 |
|----------|----------|------|
| 图像/图表理解 | MiMo V2.5 | 多模态能力强 |
| 表格解析 | MiMo V2.5 | 视觉理解能力 |
| 公式识别 | MiMo V2.5 | 数学符号识别 |
| OCR文字识别 | MiMo V2.5 | 图像识别能力 |
| 逻辑推理 | DeepSeek V4 | 推理能力强 |
| 数学计算 | DeepSeek V4 | 数学推理能力 |
| 代码生成 | DeepSeek V4 | 代码能力强 |
| 长文本处理 | DeepSeek V4 | 长上下文支持 |
| 文本摘要 | DeepSeek V4 | 成本低、效果好 |
- **向量数据库**：ChromaDB或FAISS
- **文档处理**：
  - Marker（PDF解析，基于深度学习）
  - python-pptx + 增强处理（PPT解析）
  - PyMuPDF（备用PDF解析）
  - PDFPlumber（表格提取）
- **NLP**：jieba、spaCy
- **知识图谱**：NetworkX或Neo4j
- **自进化框架**：DSPy、GEPA、Darwinian Evolver（可选）
- **基准测试**：TBLite、YC-Bench

**LLM配置设计**：
```python
class LLMConfig:
    def __init__(self):
        self.primary_model = "mimo-v2.5"  # 主要LLM（多模态）
        self.deepseek_model = "deepseek-v4"  # 对话模型（推理）
        self.multimodal_model = "mimo-v2.5"  # 多模态模型（图表、OCR）
        self.api_base = "https://api.mimo.example.com"  # MiMo API地址
        self.deepseek_api_base = "https://api.deepseek.com"  # DeepSeek API地址
        self.api_key = ""  # MiMo API密钥
        self.deepseek_api_key = ""  # DeepSeek API密钥
        self.temperature = 0.3  # 默认温度
        self.max_retries = 3  # 重试次数
    
    def get_model_for_task(self, task_type: str) -> str:
        """根据任务类型获取合适的模型"""
        # MiMo V2.5 擅长：多模态、图像、表格、公式、OCR
        # DeepSeek V4 擅长：推理、代码、数学、长文本、摘要
        ...
```

**多模态任务处理**：
```python
class MultimodalHandler:
    def __init__(self, llm_config: LLMConfig):
        self.llm_config = llm_config
    
    async def process_image(self, image_path: str) -> ImageDescription:
        """处理图像，使用多模态模型"""
        model = self.llm_config.get_model_for_task("image_understanding")
        # 使用MiMo V2.5的多模态能力
        
    async def process_table_image(self, image_path: str) -> TableData:
        """处理表格图像，提取结构化数据"""
        model = self.llm_config.get_model_for_task("multimodal")
        
    async def process_formula_image(self, image_path: str) -> LaTeXFormula:
        """处理公式图像，识别LaTeX公式"""
        model = self.llm_config.get_model_for_task("multimodal")
```

**智能模型路由器（ModelRouter）**：
```python
class ModelRouter:
    """根据任务特点智能选择模型"""
    
    def __init__(self, config: LLMConfig):
        self.config = config
        self._task_keywords = self._build_task_keywords()
    
    def analyze_task(self, task_description: str) -> TaskAnalysis:
        """分析任务并推荐模型"""
        # 1. 检测任务类别（多模态/推理/代码等）
        # 2. 评估复杂度（简单/中等/复杂）
        # 3. 检测是否需要多模态
        # 4. 检测是否需要强推理
        # 5. 选择模型
        
    def get_model_for_task(self, task_description: str) -> str:
        """获取任务对应的模型"""
        # MiMo V2.5: 图像、表格、公式、OCR
        # DeepSeek V4: 推理、代码、数学、长文本、摘要

# 任务类别
class TaskCategory(Enum):
    # MiMo V2.5 擅长
    MULTIMODAL = "multimodal"  # 图像理解
    OCR = "ocr"  # 文字识别
    TABLE_UNDERSTANDING = "table_understanding"  # 表格理解
    FORMULA_RECOGNITION = "formula_recognition"  # 公式识别
    
    # DeepSeek V4 擅长
    REASONING = "reasoning"  # 逻辑推理
    MATH_REASONING = "math_reasoning"  # 数学推理
    CODE_GENERATION = "code_generation"  # 代码生成
    LONG_TEXT = "long_text"  # 长文本处理
    SUMMARIZATION = "summarization"  # 文本摘要
```

### 5.2 开发工具
- **测试**：pytest
- **代码质量**：black、isort、mypy
- **文档**：Sphinx
- **CI/CD**：GitHub Actions

### 5.3 部署环境
- **容器化**：Docker
- **编排**：Docker Compose
- **监控**：Prometheus + Grafana

## 6. 风险评估

### 6.1 技术风险
- **LLM生成质量不稳定**：通过多轮评估和人工审核缓解
- **文档解析准确性**：使用多种解析工具和OCR技术
- **知识图谱构建复杂度**：从简单关系开始，逐步完善

### 6.2 性能风险
- **处理大文档的性能**：分块处理和并行化
- **LLM调用成本**：优化提示词，减少不必要的调用
- **内存使用**：及时释放中间结果

### 6.3 用户体验风险
- **生成内容不符合预期**：提供自定义选项和反馈机制
- **处理时间过长**：提供进度反馈和异步处理
- **格式兼容性问题**：支持多种输出格式

## 7. 成功标准

### 7.1 功能标准
- 能够正确解析PDF和PPT文件
- 生成的提纲结构清晰、内容准确
- 生成的例题难度适当、答案正确
- 支持理工科公式和图表

### 7.2 性能标准
- 文档解析时间：小于30秒/100页
- 提纲生成时间：小于60秒
- 例题生成时间：小于30秒/10题
- 系统响应时间：小于5秒

### 7.3 质量标准
- 内容准确性：大于90%
- 用户满意度：大于85%
- 系统稳定性：大于99%
- 错误恢复率：大于95%

## 8. 扩展性考虑

### 8.1 学科扩展
- 支持更多理工科领域
- 支持文科和社会科学
- 支持艺术和设计类学科

### 8.2 功能扩展
- 支持视频和音频文件
- 支持交互式学习
- 支持个性化学习路径

### 8.3 集成扩展
- 支持更多MCP服务
- 支持第三方题库
- 支持学习管理系统（LMS）

## 9. 实现状态

### 9.1 已完成功能 ✅

| 模块 | 功能 | 文件位置 |
|------|------|----------|
| 配置管理 | LLMConfig, ParserConfig, RAGConfig, MemoryConfig | `src/config.py` |
| 智能模型路由器 | ModelRouter, TaskCategory, TaskAnalysis | `src/services/model_router.py` |
| 基础智能体 | BaseAgent, AgentResult, AgentStatus | `src/agents/base_agent.py` |
| 文档解析Agent | DocumentParsingAgent | `src/agents/document_parsing.py` |
| Marker PDF解析 | MarkerPDFParser, StructuredDocument | `src/parsers/marker_pdf.py` |
| 知识图谱 | KnowledgeGraph, KnowledgePoint, Relationship | `src/knowledge/knowledge_graph.py` |
| RAG服务 | RAGService, QueryType, RetrievalStrategy | `src/services/rag_service.py` |
| 记忆服务 | ShortTermMemory, LongTermMemory, MemoryService | `src/services/memory_service.py` |
| 主协调器 | MainCoordinator, CoordinatorState | `src/coordinator/main_coordinator.py` |
| 应用入口 | CLI交互 | `src/main.py` |
| 测试 | 44个测试用例 | `tests/` |

### 9.2 待实现功能 ❌

| 模块 | 功能 | 优先级 |
|------|------|--------|
| 提纲生成Agent | OutlineGenerationAgent | 高 |
| 例题生成Agent | QuestionGenerationAgent | 高 |
| 内容理解Agent | ContentUnderstandingAgent | 中 |
| 质量评估Agent | QualityEvaluationAgent | 中 |
| 增强PPT解析 | EnhancedPPTParser | 中 |
| 工作记忆 | WorkingMemory | 低 |
| 自进化服务 | EvolutionService (DSPy+GEPA) | 低 |
| 评估服务 | EvaluationService | 低 |

## 10. 总结

本设计文档详细描述了PPT/PDF转复习提纲和考试例题智能系统的架构、组件、数据流和实现计划。系统采用模块化分层架构，通过多智能体协作、Agentic RAG、记忆系统和智能模型路由，能够提供高质量的复习提纲和考试例题生成服务。

**当前进度**：核心框架已完成（约40%），包括配置管理、智能模型路由、文档解析、知识图谱、RAG服务、记忆服务和主协调器。剩余功能将在后续迭代中实现。
