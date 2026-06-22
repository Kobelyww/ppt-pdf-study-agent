# PPT/PDF转复习提纲和考试例题智能系统

基于DeepAgent的智能系统，能够将PPT/PDF文件转化为复习提纲和考试例题。

## 功能特性

- **多智能体协作**：8个专业智能体分工协作
- **Agentic RAG**：混合检索方案，支持知识点问答解释
- **记忆系统**：短期、长期、工作记忆三层架构
- **自进化系统**：基于DSPy + GEPA的反射式进化优化
- **多模态支持**：图表理解、公式识别、表格提取

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

## 项目结构

```
newtest/
├── src/                    # 源代码
│   ├── agents/            # 智能体层
│   ├── coordinator/       # 协调器层
│   ├── knowledge/         # 知识处理
│   ├── parsers/           # 文档解析
│   ├── services/          # 服务层
│   └── utils/             # 工具函数
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
- **前端**：Streamlit

## 开发指南

### 运行测试

```bash
pytest tests/ -v
```

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
