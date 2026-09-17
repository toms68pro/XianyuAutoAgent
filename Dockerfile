# ==========================================
# 阶段 1: 依赖构建阶段
# ==========================================
FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ==========================================
# 阶段 2: 生产运行阶段
# ==========================================
FROM python:3.12-slim

LABEL maintainer="XianyuAutoAgent Team"
LABEL description="闲鱼全自动客服与多账号矩阵协同系统 Pro 2.0"
LABEL version="2.0.0"

ENV TZ=Asia/Shanghai \
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    curl \
    && ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo Asia/Shanghai > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 从构建阶段继承依赖环境
COPY --from=builder /opt/venv /opt/venv

# 准备工作目录
RUN mkdir -p data app/static

# 复制现代化应用业务代码与启动脚本
COPY app/ app/
COPY run.py ./

EXPOSE 8000

# 默认启动现代化 FastAPI 异步网关服务与 Web Copilot 工作台
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
