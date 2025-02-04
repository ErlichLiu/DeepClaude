import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

from fastapi import FastAPI, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from app.utils.logger import logger
from app.utils.auth import verify_api_key
from app.deepclaude.deepclaude import DeepClaude
import os

app = FastAPI(title="DeepClaude API")

# 从环境变量获取 CORS配置, API 密钥、地址以及模型名称
ALLOW_ORIGINS = os.getenv("ALLOW_ORIGINS", "*")

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL")
CLAUDE_PROVIDER = os.getenv("CLAUDE_PROVIDER", "anthropic") # Claude模型提供商, 默认为anthropic
CLAUDE_API_URL = os.getenv("CLAUDE_API_URL", "https://api.anthropic.com/v1/messages")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL")
DEEPSEEK_PROVIDER = os.getenv("DEEPSEEK_PROVIDER", "deepseek") # R1模型提供商, 默认为deepseek
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL")

# CORS设置
allow_origins_list = ALLOW_ORIGINS.split(",") if ALLOW_ORIGINS else [] # 将逗号分隔的字符串转换为列表

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 验证日志级别
logger.debug("当前日志级别为 DEBUG")
logger.info("开始请求")

@app.get("/", dependencies=[Depends(verify_api_key)])
async def root():
    logger.info("访问了根路径")
    return {"message": "Welcome to DeepClaude API"}

@app.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
async def chat_completions(request: Request):
    """处理聊天完成请求，返回流式响应
    
    请求体格式应与 OpenAI API 保持一致，包含：
    - messages: 消息列表
    - model: 模型名称（可选）
    - stream: 是否使用流式输出（必须为 True）
    """

    try:
        # 1. 获取并验证请求数据
        body = await request.json()
        messages = body.get("messages")
        if not messages:
            return {"error": "messages 不能为空"}
        
        if not body.get("stream", False):
            return {"error": "目前仅支持流式输出，stream 必须为 True"}
        
        # 3. 创建 DeepClaude 实例
        if not DEEPSEEK_API_KEY or not CLAUDE_API_KEY:
            return {"error": "未设置 API 密钥"}
            
        deep_claude = DeepClaude(
            DEEPSEEK_API_KEY, 
            CLAUDE_API_KEY, 
            DEEPSEEK_API_URL,
            CLAUDE_API_URL,
            DEEPSEEK_PROVIDER,
            CLAUDE_PROVIDER
        )
        
        # 4. 返回流式响应
        return StreamingResponse(
            deep_claude.chat_completions_with_stream(
                messages=messages,
                deepseek_model=DEEPSEEK_MODEL,
                claude_model=CLAUDE_MODEL
            ),
            media_type="text/event-stream"
        )
        
    except Exception as e:
        logger.error(f"处理请求时发生错误: {e}")
        return {"error": str(e)}