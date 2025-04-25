"""
DeepClaude API 主模块

这个模块是DeepClaude应用的入口点，负责初始化FastAPI应用、
配置中间件、设置路由和管理应用生命周期。

主要功能：
- 初始化数据库连接池和模型管理器
- 配置CORS中间件和日志级别
- 提供API端点用于模型调用和配置管理
- 管理应用的启动和关闭过程
"""
import os
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.utils.auth import verify_api_key
from app.utils.logger import logger
from app.manager.model_manager import ModelManager
from app.utils.db_manager_pool import DBManagerPool


# 版本信息
VERSION = "v1.0.1"

# 显示当前的版本
logger.info("当前版本: %s", VERSION)

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """管理FastAPI应用的生命周期

    这个异步上下文管理器负责在应用启动时初始化必要的资源（如数据库连接池和模型管理器），
    并在应用关闭时释放这些资源。

    Args:
        app (FastAPI): FastAPI应用实例

    Yields:
        None: 控制权交还给FastAPI服务器
    """
    # 初始化数据库连接池
    db_manager = DBManagerPool()
    db_manager.open_db_manager()
    logger.info("数据库连接池初始化完成")
    app_instance.state.model_manager = ModelManager(db_manager)

    # 配置 CORS
    app_instance.add_middleware(
        CORSMiddleware,
        allow_origins=app_instance.state.model_manager.config.get("allow_origins", ["*"]),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 设置日志级别（不重新创建logger）
    logger.setLevel(getattr(logging, app_instance.state.model_manager.config.get("log_level", "INFO")))

    yield

    # 关闭数据库连接池
    db_manager.close_db_manager()
    logger.info("数据库连接池已关闭")

# 创建 FastAPI 应用
app = FastAPI(title="DeepClaude API", lifespan=lifespan)

# 静态文件目录
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
# 挂载静态文件目录
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 验证日志级别
logger.debug("当前日志级别为 DEBUG")
logger.info("开始请求")

def get_api_key_dependency():
    """创建API密钥验证依赖"""
    return verify_api_key(app.state.model_manager.config.get("api_key"))

@app.get("/", dependencies=[Depends(get_api_key_dependency())])
async def root():
    """API根路径访问处理

    返回API欢迎信息和版本号
    """
    logger.info("访问了根路径")
    return {"message": "Welcome to DeepClaude API", "version": VERSION}


@app.post("/v1/chat/completions", dependencies=[Depends(get_api_key_dependency())])
async def chat_completions(request: Request):
    """处理聊天完成请求，使用 ModelManager 进行处理

    请求体格式应与 OpenAI API 保持一致，包含：
    - messages: 消息列表
    - model: 模型名称（必需）
    - model_type: 模型类型(可选,为AiPotluck准备)
    - stream: 是否使用流式输出（可选，默认为 True)
    - temperature: 随机性 (可选)
    - top_p: top_p (可选)
    - presence_penalty: 话题新鲜度（可选）
    - frequency_penalty: 频率惩罚度（可选）
    """
    try:
        # 获取请求体
        body = await request.json()
        # 使用 ModelManager 处理请求，ModelManager 将处理不同的模型组合
        return await app.state.model_manager.process_request(body)
    except Exception as e:
        logger.error("处理请求时发生错误: %s", e)
        return {"error": str(e)}

@app.get("/v1/models", dependencies=[Depends(get_api_key_dependency())])
async def list_models():
    """获取可用模型列表

    使用 ModelManager 获取从配置文件中读取的模型列表
    返回格式遵循 OpenAI API 标准
    """
    try:
        models = app.state.model_manager.get_model_list()
        return {"object": "list", "data": models}
    except Exception as e:
        logger.error("获取模型列表时发生错误: %s", e)
        return {"error": str(e)}

@app.get("/config")
async def config_page():
    """配置页面

    返回配置页面的 HTML
    """
    try:
        html_path = os.path.join(static_dir, "index.html")
        if not os.path.exists(html_path):
            logger.error("HTML 文件不存在: %s", html_path)
            return {"error": "配置页面文件不存在"}
        return FileResponse(html_path)
    except Exception as e:
        logger.error("返回配置页面时发生错误: %s", e)
        return {"error": str(e)}

@app.get("/v1/config", dependencies=[Depends(get_api_key_dependency())])
async def get_config():
    """获取模型配置

    返回当前的模型配置数据
"""
    try:
        # 使用 ModelManager 获取配置
        config = app.state.model_manager.get_config()
        return config
    except Exception as e:
        logger.error("获取配置时发生错误: %s", e)
        return {"error": str(e)}

@app.post("/v1/config", dependencies=[Depends(get_api_key_dependency())])
async def update_config(request: Request):
    """更新模型配置

    接收并保存新的模型配置数据
    """
    try:
        # 获取请求体
        body = await request.json()

        # 使用 ModelManager 更新配置
        app.state.model_manager.update_config(body)

        return {"message": "配置已更新"}
    except Exception as e:
        logger.error("更新配置时发生错误: %s", e)
        return {"error": str(e)}
