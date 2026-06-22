"""模型路由器测试"""

import pytest
from src.config import LLMConfig, TaskCategory
from src.services.model_router import ModelRouter, TaskAnalysis, TaskComplexity, create_model_router


@pytest.fixture
def config():
    """创建测试配置"""
    return LLMConfig(
        primary_model="mimo-v2.5",
        deepseek_model="deepseek-v4",
        api_key="test-key",
        deepseek_api_key="test-ds-key",
    )


@pytest.fixture
def router(config):
    """创建模型路由器"""
    return create_model_router(config)


def test_router_initialization(router):
    """测试路由器初始化"""
    assert router is not None
    assert router.config is not None
    assert len(router._task_keywords) > 0


def test_multimodal_task_detection(router):
    """测试多模态任务检测"""
    # 图片相关任务 -> MiMo V2.5
    assert router.get_model_for_task("请分析这张图片") == "mimo-v2.5"
    assert router.get_model_for_task("describe this image") == "mimo-v2.5"
    assert router.get_model_for_task("识别图表中的数据") == "mimo-v2.5"
    assert router.get_model_for_task("extract text from this photo") == "mimo-v2.5"


def test_reasoning_task_detection(router):
    """测试推理任务检测"""
    # 推理相关任务 -> DeepSeek V4
    assert router.get_model_for_task("分析这个逻辑问题") == "deepseek-v4"
    assert router.get_model_for_task("why does this happen") == "deepseek-v4"
    assert router.get_model_for_task("证明这个定理") == "deepseek-v4"


def test_code_task_detection(router):
    """测试代码任务检测"""
    # 代码相关任务 -> DeepSeek V4
    assert router.get_model_for_task("写一个Python函数") == "deepseek-v4"
    assert router.get_model_for_task("implement a sorting algorithm") == "deepseek-v4"
    assert router.get_model_for_task("调试这段代码") == "deepseek-v4"


def test_table_task_detection(router):
    """测试表格任务检测"""
    # 表格相关任务 -> MiMo V2.5
    assert router.get_model_for_task("解析这个表格") == "mimo-v2.5"
    assert router.get_model_for_task("extract data from this table") == "mimo-v2.5"


def test_formula_task_detection(router):
    """测试公式任务检测"""
    # 公式相关任务 -> MiMo V2.5
    assert router.get_model_for_task("识别这个数学公式") == "mimo-v2.5"
    assert router.get_model_for_task("extract the formula from the image") == "mimo-v2.5"


def test_summary_task_detection(router):
    """测试摘要任务检测"""
    # 摘要任务 -> DeepSeek V4
    assert router.get_model_for_task("总结这篇文章") == "deepseek-v4"
    assert router.get_model_for_task("summarize this document") == "deepseek-v4"


def test_qa_task_detection(router):
    """测试问答任务检测"""
    # 问答任务 -> DeepSeek V4
    assert router.get_model_for_task("什么是机器学习？") == "deepseek-v4"
    assert router.get_model_for_task("what is machine learning") == "deepseek-v4"


def test_task_analysis(router):
    """测试任务分析"""
    analysis = router.analyze_task("请分析这张图片中的数据趋势")

    assert analysis is not None
    assert analysis.requires_multimodal is True
    assert analysis.recommended_model == "mimo-v2.5"
    assert analysis.confidence > 0.8


def test_complexity_assessment(router):
    """测试复杂度评估"""
    # 简单任务
    simple = router._assess_complexity("简单问题")
    assert simple == TaskComplexity.SIMPLE

    # 复杂任务
    complex_task = router._assess_complexity("请详细分析这个复杂的多步骤问题，并给出全面的解决方案")
    assert complex_task == TaskComplexity.COMPLEX


def test_token_estimation(router):
    """测试token估算"""
    tokens = router._estimate_tokens("这是一个测试任务")
    assert tokens > 0
    assert tokens < 1000


def test_routing_stats(router):
    """测试路由统计"""
    tasks = [
        "分析图片",  # MiMo
        "写代码",  # DeepSeek
        "识别表格",  # MiMo
        "总结文档",  # DeepSeek
        "推理问题",  # DeepSeek
    ]

    stats = router.get_routing_stats(tasks)
    assert stats["mimo-v2.5"] == 2
    assert stats["deepseek-v4"] == 3


def test_model_profiles(config):
    """测试模型配置文件"""
    assert "mimo-v2.5" in config.model_profiles
    assert "deepseek-v4" in config.model_profiles

    mimo_profile = config.model_profiles["mimo-v2.5"]
    assert mimo_profile.supports_multimodal is True

    ds_profile = config.model_profiles["deepseek-v4"]
    assert ds_profile.supports_multimodal is False


def test_task_model_mapping(config):
    """测试任务模型映射"""
    assert config.task_model_mapping[TaskCategory.MULTIMODAL] == "mimo-v2.5"
    assert config.task_model_mapping[TaskCategory.REASONING] == "deepseek-v4"
    assert config.task_model_mapping[TaskCategory.CODE_GENERATION] == "deepseek-v4"
    assert config.task_model_mapping[TaskCategory.TABLE_UNDERSTANDING] == "mimo-v2.5"


def test_should_use_multimodal(config):
    """测试多模态判断"""
    assert config.should_use_multimodal("请分析这张图片") is True
    assert config.should_use_multimodal("图片中的内容是什么") is True
    assert config.should_use_multimodal("这个图表显示了什么") is True
    assert config.should_use_multimodal("写一个函数") is False
    assert config.should_use_multimodal("总结文章") is False
