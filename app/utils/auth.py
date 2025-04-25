"""认证模块，用于验证 API 密钥"""

from typing import Optional

from fastapi import HTTPException, Header

from app.utils.logger import logger

async def verify_api_key(current_api_key: str, authorization: Optional[str] = Header(None)) -> None:
    """验证API密钥

    Args:
        authorization (Optional[str], optional): Authorization header中的API密钥. Defaults to Header(None).

    Raises:
        HTTPException: 当Authorization header缺失或API密钥无效时抛出401错误
    """
    if authorization is None:
        logger.warning("请求缺少Authorization header")
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header"
        )

    api_key = authorization.replace("Bearer ", "").strip()
    if api_key != current_api_key:
        logger.warning("无效的API密钥: %s", api_key)
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )

    logger.info("API密钥验证通过")
