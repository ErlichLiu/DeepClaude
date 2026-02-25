import os
import logging
import json
import aiohttp
import time

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.utils.auth import verify_api_key
from app.utils.logger import logger
from app.manager import model_manager

# 版本信息
VERSION = "v1.0.1"

# 显示当前的版本
logger.info(f"当前版本: {VERSION}")

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
    return {"message": "Welcome to DeepClaude API", "version": VERSION}


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
        # 返回错误信息，保持与上游API一致的格式
        if isinstance(e, aiohttp.ClientError):
            error_message = str(e)
            if "API 请求失败" in error_message:
                # 提取上游API的错误信息
                try:
                    error_json = json.loads(error_message.split("错误信息: ")[-1])
                    # 处理常见的错误信息
                    if "error" in error_json:
                        error_info = error_json["error"]
                        # 处理输入长度超限的错误
                        if "Input length" in error_info.get("message", ""):
                            error_info["message"] = "输入的上下文内容过长，超过了模型的最大处理长度限制。请减少输入内容或分段处理。"
                            error_info["message_zh"] = "输入的上下文内容过长，超过了模型的最大处理长度限制。请减少输入内容或分段处理。"
                            error_info["message_en"] = error_info.get("message", "")
                        # 处理其他常见错误
                        elif "InvalidParameter" in error_info.get("code", ""):
                            error_info["message"] = "请求参数无效，请检查输入内容。"
                            error_info["message_zh"] = "请求参数无效，请检查输入内容。"
                            error_info["message_en"] = error_info.get("message", "")
                        elif "BadRequest" in error_info.get("type", ""):
                            error_info["message"] = "请求格式错误，请检查输入内容。"
                            error_info["message_zh"] = "请求格式错误，请检查输入内容。"
                            error_info["message_en"] = error_info.get("message", "")

                    # 如果是流式请求，返回流式错误响应
                    if body.get("stream", True):
                        async def error_stream(err_msg):
                            error_response = {
                                "id": f"chatcmpl-{hex(int(time.time() * 1000))[2:]}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": body.get("model", "unknown"),
                                "error": error_json.get("error", {
                                    "message": err_msg,
                                    "type": "api_error",
                                    "code": "invalid_request_error"
                                })
                            }
                            yield f"data: {json.dumps(error_response)}\n\n".encode("utf-8")
                            yield b"data: [DONE]\n\n"
                        return StreamingResponse(
                            error_stream(str(e)),
                            media_type="text/event-stream"
                        )
                    else:
                        return JSONResponse(
                            status_code=400,
                            content=error_json
                        )
                except Exception:
                    pass
        # 如果是流式请求，返回流式错误响应
        if body.get("stream", True):
            async def error_stream(err_msg):
                error_response = {
                    "id": f"chatcmpl-{hex(int(time.time() * 1000))[2:]}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": body.get("model", "unknown"),
                    "error": {
                        "message": err_msg,
                        "type": "api_error",
                        "code": "invalid_request_error"
                    }
                }
                yield f"data: {json.dumps(error_response)}\n\n".encode("utf-8")
                yield b"data: [DONE]\n\n"
            return StreamingResponse(
                error_stream(str(e)),
                media_type="text/event-stream"
            )
        else:
            return JSONResponse(
                status_code=500,
                content={"error": str(e)}
            )

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

@app.get("/v1/config/export", dependencies=[Depends(verify_api_key)])
async def export_config():
    """导出模型配置

    返回当前完整的模型配置数据，可用于备份和迁移
    """
    try:
        # 使用 ModelManager 导出配置
        config = model_manager.export_config()

        # 设置响应头，建议浏览器下载文件
        from fastapi.responses import JSONResponse
        from datetime import datetime

        filename = f"deepclaude_config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        headers = {
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Type": "application/json"
        }

        return JSONResponse(content=config, headers=headers)
    except Exception as e:
        logger.error(f"导出配置时发生错误: {e}")
        return {"error": str(e)}

@app.post("/v1/config/import", dependencies=[Depends(verify_api_key)])
async def import_config(request: Request):
    """导入模型配置

    接收并验证配置文件，然后导入到系统中
    """
    try:
        # 获取请求体
        body = await request.json()

        # 使用 ModelManager 导入配置
        model_manager.import_config(body)

        return {"message": "配置导入成功"}
    except ValueError as e:
        logger.error(f"配置验证失败: {e}")
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"导入配置时发生错误: {e}")
        return {"error": str(e)}
