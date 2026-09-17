#!/usr/bin/env python3
"""
Xianyu AutoAgent Pro 2.0 - 快速启动脚本
支持启动现代化 FastAPI 异步网关、闲鱼 WSS 长连接池与 Web 协同工作台
"""

import sys
import os
import uvicorn
from loguru import logger
from dotenv import load_dotenv

# 加载环境变量
if os.path.exists(".env"):
    load_dotenv(".env")
elif os.path.exists(".env.example"):
    load_dotenv(".env.example")

from app.config import settings


def main():
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )

    banner = r"""
 __   ___                            _         _                         _   
 \ \ / (_) __ _ _ __  _   _ _   _   / \  _   _| |_ ___   /\  __ _  ___ _ __ | |_ 
  \ V /| |/ _` | '_ \| | | | | | | / _ \| | | | __/ _ \ / /_/ _` |/ _ \ '_ \| __|
   | | | | (_| | | | | |_| | |_| |/ ___ \ |_| | || (_) / __/ (_| |  __/ | | | |_ 
   |_| |_|\__,_|_| |_|\__,_|\__,_/_/   \_\__,_|\__\___/\/   \__,_|\___|_| |_|\__|
                      🚀 Pro 2.0 现代化全栈智能客服系统
    """
    print(banner)
    print(f"👉 协同管理工作台: http://localhost:{settings.SERVER_PORT}")
    print(f"👉 接口文档 (Swagger): http://localhost:{settings.SERVER_PORT}/docs")
    print(f"👉 默认值守模型: {settings.MODEL_NAME}")
    print("=" * 75)

    uvicorn.run(
        "app.main:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=False
    )


if __name__ == "__main__":
    main()
