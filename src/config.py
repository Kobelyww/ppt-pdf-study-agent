from dataclasses import dataclass, field
from typing import Optional, Dict, List
from enum import Enum
import os
from dotenv import load_dotenv

# 加载.env文件
load_dotenv()

DEV_SECRET_KEY = "dev-secret-change-me"
EXAMPLE_PRODUCTION_SECRET_KEY = "change-me-super-secret-production-key"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _env_csv(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class ProductConfig:
    app_env: str = "development"
    secret_key: str = DEV_SECRET_KEY
    allow_dev_user_header: bool = True
    database_url: str = "sqlite:///./study_agent.db"
    queue_backend: str = "memory"
    redis_url: str = ""
    storage_backend: str = "local"
    local_storage_root: str = "./data/storage"
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_secure: bool = False
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173"])

    def validate_production(self) -> None:
        if self.app_env.strip().lower() != "production":
            return
        if self.allow_dev_user_header:
            raise ValueError("ALLOW_DEV_USER_HEADER must be disabled in production")
        if self.secret_key.strip() in {DEV_SECRET_KEY, EXAMPLE_PRODUCTION_SECRET_KEY}:
            raise ValueError("SECRET_KEY must not use a placeholder in production")
        required = {
            "SECRET_KEY": self.secret_key,
            "DATABASE_URL": self.database_url,
            "REDIS_URL": self.redis_url,
            "S3_ENDPOINT_URL": self.s3_endpoint_url,
            "S3_BUCKET": self.s3_bucket,
            "S3_ACCESS_KEY_ID": self.s3_access_key_id,
            "S3_SECRET_ACCESS_KEY": self.s3_secret_access_key,
            "BOOTSTRAP_ADMIN_EMAIL": self.bootstrap_admin_email,
            "BOOTSTRAP_ADMIN_PASSWORD": self.bootstrap_admin_password,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise ValueError(f"Missing production config: {', '.join(missing)}")
        if self.queue_backend != "redis":
            raise ValueError("QUEUE_BACKEND must be redis in production")
        if self.storage_backend != "s3":
            raise ValueError("STORAGE_BACKEND must be s3 in production")


def load_product_config() -> ProductConfig:
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    config = ProductConfig(
        app_env=app_env,
        secret_key=os.getenv("SECRET_KEY", "" if app_env == "production" else DEV_SECRET_KEY),
        allow_dev_user_header=_env_bool("ALLOW_DEV_USER_HEADER", True),
        database_url=os.getenv(
            "DATABASE_URL",
            "" if app_env == "production" else "sqlite:///./study_agent.db",
        ),
        queue_backend=os.getenv("QUEUE_BACKEND", "memory"),
        redis_url=os.getenv("REDIS_URL", ""),
        storage_backend=os.getenv("STORAGE_BACKEND", "local"),
        local_storage_root=os.getenv("LOCAL_STORAGE_ROOT", "./data/storage"),
        s3_endpoint_url=os.getenv("S3_ENDPOINT_URL", ""),
        s3_bucket=os.getenv("S3_BUCKET", ""),
        s3_region=os.getenv("S3_REGION", "us-east-1"),
        s3_access_key_id=os.getenv("S3_ACCESS_KEY_ID", ""),
        s3_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY", ""),
        s3_secure=_env_bool("S3_SECURE", False),
        bootstrap_admin_email=os.getenv("BOOTSTRAP_ADMIN_EMAIL", ""),
        bootstrap_admin_password=os.getenv("BOOTSTRAP_ADMIN_PASSWORD", ""),
        cors_origins=_env_csv("CORS_ORIGINS", ["http://localhost:5173"]),
    )
    config.validate_production()
    return config

class TaskCategory(Enum):
    """任务类别"""
    # MiMo V2.5 擅长的任务（多模态、视觉理解）
    MULTIMODAL = "multimodal"  # 图像理解、图表识别
    OCR = "ocr"  # 文字识别
    TABLE_UNDERSTANDING = "table_understanding"  # 表格理解
    FORMULA_RECOGNITION = "formula_recognition"  # 公式识别
    IMAGE_DESCRIPTION = "image_description"  # 图像描述
    
    # DeepSeek V4 擅长的任务（推理、代码、长文本）
    REASONING = "reasoning"  # 逻辑推理
    MATH_REASONING = "math_reasoning"  # 数学推理
    CODE_GENERATION = "code_generation"  # 代码生成
    CODE_DEBUG = "code_debug"  # 代码调试
    LONG_TEXT = "long_text"  # 长文本处理
    SUMMARIZATION = "summarization"  # 文本摘要
    ANALYSIS = "analysis"  # 文本分析
    
    # 通用任务
    QA = "qa"  # 问答
    TRANSLATION = "translation"  # 翻译
    CREATIVE = "creative"  # 创意写作
    EXTRACTION = "extraction"  # 信息提取

@dataclass
class ModelProfile:
    """模型配置文件"""
    name: str
    api_base: str
    api_key: str
    temperature: float = 0.3
    max_tokens: int = 4096
    supports_multimodal: bool = False
    strengths: List[str] = field(default_factory=list)

@dataclass
class LLMConfig:
    """LLM配置"""
    primary_model: str = "mimo-v2.5"
    deepseek_model: str = "deepseek-v4"
    multimodal_model: str = "mimo-v2.5"
    embedding_model: str = "mimo-v2.5-embedding"
    api_base: str = "https://api.mimo.example.com"
    deepseek_api_base: str = "https://api.deepseek.com"
    api_key: str = ""
    deepseek_api_key: str = ""
    temperature: float = 0.3
    max_retries: int = 3
    
    # 模型配置文件
    model_profiles: Dict[str, ModelProfile] = field(default_factory=dict)
    
    # 任务到模型的映射
    task_model_mapping: Dict[TaskCategory, str] = field(default_factory=dict)
    
    def __post_init__(self):
        """初始化模型配置"""
        if not self.model_profiles:
            self.model_profiles = {
                "mimo-v2.5": ModelProfile(
                    name="mimo-v2.5",
                    api_base=self.api_base,
                    api_key=self.api_key,
                    supports_multimodal=True,
                    strengths=["multimodal", "ocr", "table", "formula", "image"]
                ),
                "deepseek-v4": ModelProfile(
                    name="deepseek-v4",
                    api_base=self.deepseek_api_base,
                    api_key=self.deepseek_api_key,
                    supports_multimodal=False,
                    strengths=["reasoning", "math", "code", "long_text", "analysis"]
                ),
            }
        
        if not self.task_model_mapping:
            self.task_model_mapping = {
                # MiMo V2.5 擅长的多模态任务
                TaskCategory.MULTIMODAL: "mimo-v2.5",
                TaskCategory.OCR: "mimo-v2.5",
                TaskCategory.TABLE_UNDERSTANDING: "mimo-v2.5",
                TaskCategory.FORMULA_RECOGNITION: "mimo-v2.5",
                TaskCategory.IMAGE_DESCRIPTION: "mimo-v2.5",
                
                # DeepSeek V4 擅长的推理任务
                TaskCategory.REASONING: "deepseek-v4",
                TaskCategory.MATH_REASONING: "deepseek-v4",
                TaskCategory.CODE_GENERATION: "deepseek-v4",
                TaskCategory.CODE_DEBUG: "deepseek-v4",
                TaskCategory.LONG_TEXT: "deepseek-v4",
                TaskCategory.SUMMARIZATION: "deepseek-v4",
                TaskCategory.ANALYSIS: "deepseek-v4",
                
                # 通用任务使用 DeepSeek V4（成本更低）
                TaskCategory.QA: "deepseek-v4",
                TaskCategory.TRANSLATION: "deepseek-v4",
                TaskCategory.CREATIVE: "mimo-v2.5",
                TaskCategory.EXTRACTION: "deepseek-v4",
            }
    
    def get_model_for_task(self, task_type: str) -> str:
        """根据任务类型获取合适的模型"""
        # 尝试匹配任务类别
        try:
            category = TaskCategory(task_type)
            return self.task_model_mapping.get(category, self.primary_model)
        except ValueError:
            pass
        
        # 关键词匹配
        task_lower = task_type.lower()
        
        # 多模态相关任务 -> MiMo V2.5
        multimodal_keywords = ["image", "picture", "photo", "chart", "graph", "table", 
                              "formula", "equation", "ocr", "visual", "diagram"]
        if any(kw in task_lower for kw in multimodal_keywords):
            return self.multimodal_model
        
        # 推理/代码相关任务 -> DeepSeek V4
        reasoning_keywords = ["reason", "logic", "math", "calculate", "code", "program",
                             "debug", "analyze", "analyze", "summarize", "long"]
        if any(kw in task_lower for kw in reasoning_keywords):
            return self.deepseek_model
        
        # 默认使用主模型
        return self.primary_model
    
    def get_model_config(self, model_name: str) -> ModelProfile:
        """获取模型配置"""
        return self.model_profiles.get(model_name, self.model_profiles[self.primary_model])
    
    def get_api_base_for_model(self, model: str) -> str:
        """根据模型获取API地址"""
        profile = self.model_profiles.get(model)
        if profile:
            return profile.api_base
        if model == self.deepseek_model:
            return self.deepseek_api_base
        return self.api_base
    
    def get_api_key_for_model(self, model: str) -> str:
        """根据模型获取API密钥"""
        profile = self.model_profiles.get(model)
        if profile:
            return profile.api_key
        if model == self.deepseek_model:
            return self.deepseek_api_key
        return self.api_key
    
    def should_use_multimodal(self, task_description: str) -> bool:
        """判断是否应该使用多模态模型"""
        multimodal_indicators = [
            "图片", "图像", "图表", "表格", "公式", "照片", "扫描",
            "image", "picture", "chart", "graph", "table", "formula",
            "photo", "scan", "ocr", "visual", "diagram", "figure"
        ]
        task_lower = task_description.lower()
        return any(indicator in task_lower for indicator in multimodal_indicators)

@dataclass
class ParserConfig:
    """解析器配置"""
    marker_model_path: str = "marker-model"
    use_local_marker: bool = True
    enable_ocr: bool = True
    max_file_size_mb: int = 100

@dataclass
class RAGConfig:
    """RAG配置"""
    vector_db_type: str = "chromadb"
    vector_db_path: str = "./data/vector_db"
    embedding_model: str = "mimo-v2.5-embedding"
    embedding_api_base: str = "https://api.mimo.example.com"
    embedding_api_key: str = ""
    embedding_dim: int = 768
    chunk_size: int = 1000
    chunk_overlap: int = 200
    top_k: int = 5
    use_hybrid_retrieval: bool = True
    bm25_weight: float = 0.3
    embedding_weight: float = 0.7

@dataclass
class MemoryConfig:
    """记忆配置"""
    stm_max_tokens: int = 50000
    recent_window_size: int = 5
    compress_trigger: int = 30000
    ltm_db_path: str = "./data/long_term_memory.db"

@dataclass
class AppConfig:
    """应用配置"""
    llm: Optional[LLMConfig] = None
    parser: Optional[ParserConfig] = None
    rag: Optional[RAGConfig] = None
    memory: Optional[MemoryConfig] = None
    
    def __post_init__(self):
        if self.llm is None:
            self.llm = LLMConfig()
        if self.parser is None:
            self.parser = ParserConfig()
        if self.rag is None:
            self.rag = RAGConfig()
        if self.memory is None:
            self.memory = MemoryConfig()

def load_config() -> AppConfig:
    """从环境变量加载配置"""
    return AppConfig(
        llm=LLMConfig(
            primary_model=os.getenv("LLM_PRIMARY_MODEL", "mimo-v2.5"),
            deepseek_model=os.getenv("LLM_DEEPSEEK_MODEL", "deepseek-v4"),
            multimodal_model=os.getenv("LLM_MULTIMODAL_MODEL", "mimo-v2.5"),
            embedding_model=os.getenv("LLM_EMBEDDING_MODEL", "mimo-v2.5-embedding"),
            api_base=os.getenv("MIMO_API_BASE", "https://api.mimo.example.com"),
            deepseek_api_base=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
            api_key=os.getenv("MIMO_API_KEY", ""),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
        ),
        parser=ParserConfig(
            marker_model_path=os.getenv("MARKER_MODEL_PATH", "marker-model"),
            use_local_marker=os.getenv("PARSER_USE_LOCAL_MARKER", "true").lower() == "true",
            enable_ocr=os.getenv("PARSER_ENABLE_OCR", "true").lower() == "true",
            max_file_size_mb=int(os.getenv("PARSER_MAX_FILE_SIZE_MB", "100")),
        ),
        rag=RAGConfig(
            vector_db_type=os.getenv("RAG_VECTOR_DB_TYPE", "chromadb"),
            vector_db_path=os.getenv("VECTOR_DB_PATH", "./data/vector_db"),
            embedding_model=os.getenv("RAG_EMBEDDING_MODEL", "mimo-v2.5-embedding"),
            embedding_api_base=os.getenv("RAG_EMBEDDING_API_BASE", "https://api.mimo.example.com"),
            embedding_api_key=os.getenv("RAG_EMBEDDING_API_KEY", ""),
            embedding_dim=int(os.getenv("RAG_EMBEDDING_DIM", "768")),
            chunk_size=int(os.getenv("RAG_CHUNK_SIZE", "1000")),
            chunk_overlap=int(os.getenv("RAG_CHUNK_OVERLAP", "200")),
            top_k=int(os.getenv("RAG_TOP_K", "5")),
            use_hybrid_retrieval=os.getenv("RAG_USE_HYBRID_RETRIEVAL", "true").lower() == "true",
            bm25_weight=float(os.getenv("RAG_BM25_WEIGHT", "0.3")),
            embedding_weight=float(os.getenv("RAG_EMBEDDING_WEIGHT", "0.7")),
        ),
        memory=MemoryConfig(
            stm_max_tokens=int(os.getenv("MEMORY_STM_MAX_TOKENS", "50000")),
            recent_window_size=int(os.getenv("MEMORY_RECENT_WINDOW_SIZE", "5")),
            compress_trigger=int(os.getenv("MEMORY_COMPRESS_TRIGGER", "30000")),
            ltm_db_path=os.getenv("LTM_DB_PATH", "./data/long_term_memory.db"),
        ),
    )
