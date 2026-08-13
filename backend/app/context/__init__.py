"""项目上下文生成器包：与文本 AIProvider、处理 Provider 解耦。"""

from app.context.factory import get_project_context_generator

__all__ = ["get_project_context_generator"]
