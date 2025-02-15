# 使用 Python 3.11 slim 版本作为基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 安装依赖
RUN pip install --no-cache-dir \
    aiohttp==3.11.11 \
    colorlog==6.9.0 \
    fastapi==0.115.8 \
    python-dotenv==1.0.1 \
    tiktoken==0.8.0 \
    "uvicorn[standard]"

# 复制项目文件
COPY ./app ./app

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
