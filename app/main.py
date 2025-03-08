import os
import logging

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.utils.auth import verify_api_key
from app.utils.logger import logger
from app.manager import model_manager


# 获取模型管理器
from app.manager.model_manager import model_manager

# 从配置文件中读取系统设置
system_config = model_manager.config.get("system", {})
allow_origins = system_config.get("allow_origins", ["*"])
log_level = system_config.get("log_level", "INFO")
api_key = system_config.get("api_key")

# 设置日志级别（不重新创建logger）
logger.setLevel(getattr(logging, log_level))

# 静态文件目录
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

# 创建 FastAPI 应用
app = FastAPI(title="DeepClaude API")

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 验证日志级别
logger.debug("当前日志级别为 DEBUG")
logger.info("开始请求")

@app.get("/", dependencies=[Depends(verify_api_key)])
async def root():
    logger.info("访问了根路径")
    return {"message": "Welcome to DeepClaude API"}


@app.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
async def chat_completions(request: Request):
    """处理聊天完成请求，使用 ModelManager 进行处理
    
    请求体格式应与 OpenAI API 保持一致，包含：
    - messages: 消息列表
    - model: 模型名称（必需）
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
        return await model_manager.process_request(body)
    except Exception as e:
        logger.error(f"处理请求时发生错误: {e}")
        return {"error": str(e)}

@app.get("/v1/models", dependencies=[Depends(verify_api_key)])
async def list_models():
    """获取可用模型列表
    
    使用 ModelManager 获取从配置文件中读取的模型列表
    返回格式遵循 OpenAI API 标准
    """
    try:
        models = model_manager.get_model_list()
        return {"object": "list", "data": models}
    except Exception as e:
        logger.error(f"获取模型列表时发生错误: {e}")
        return {"error": str(e)}


@app.get("/config")
async def config_page():
    """配置页面
    
    返回配置页面的 HTML
    """
    try:
        html_path = os.path.join(static_dir, "index.html")
        if not os.path.exists(html_path):
            logger.error(f"HTML 文件不存在: {html_path}")
            return {"error": "配置页面文件不存在"}
        return FileResponse(html_path)
    except Exception as e:
        logger.error(f"返回配置页面时发生错误: {e}")
        return {"error": str(e)}

@app.get("/v1/config", dependencies=[Depends(verify_api_key)])
async def get_config():
    """获取模型配置
    
    返回当前的模型配置数据
    """
    try:
        # 使用 ModelManager 获取配置
        config = model_manager.get_config()
        return config
    except Exception as e:
        logger.error(f"获取配置时发生错误: {e}")
        return {"error": str(e)}

@app.post("/v1/config", dependencies=[Depends(verify_api_key)])
async def update_config(request: Request):
    """更新模型配置
    
    接收并保存新的模型配置数据
    """
    try:
        # 获取请求体
        body = await request.json()
        
        # 使用 ModelManager 更新配置
        model_manager.update_config(body)
        
        return {"message": "配置已更新"}
    except Exception as e:
        logger.error(f"更新配置时发生错误: {e}")
        return {"error": str(e)}
