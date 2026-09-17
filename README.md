# 🚀 Xianyu AutoAgent Pro 2.0 - 工业级闲鱼多账号智能客服与协同矩阵

[![Python Version](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0%2B-D71F00?logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![PostgreSQL 18](https://img.shields.io/badge/PostgreSQL-18-336791?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis 8](https://img.shields.io/badge/Redis-8-DC382D?logo=redis&logoColor=white)](https://redis.io/)
[![OpenAI Compatible](https://img.shields.io/badge/LLM-OpenAI%20Compatible-412991?logo=openai&logoColor=white)](https://platform.openai.com/)
[![License](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](LICENSE)

专为闲鱼生态打造的**企业级自动化客服矩阵与卖家协同工作台系统**。系统采用现代异步事件驱动架构（FastAPI + AsyncIO + SQLAlchemy 2.0），全面支持 **PostgreSQL 18** 高性能连接池与 **Redis 8** 分布式秒级语义缓存；集成闲鱼官方 WSS 长连接同步协议、多账号独立住宅代理隔离、确定性守价护栏、混合 RAG 电商知识库、一卡一密自动核销履约与全功能 Web Copilot 工作台。

---

## 🏛️ 系统总体架构

```
                     ┌─────────────────────────────────────────────────────────┐
                     │            闲鱼云端网关 (WSS + MTOP HTTP API)            │
                     └────────────────────────────┬────────────────────────────┘
                                                  │ (WSS SyncPushPackage / MTOP)
                                                  ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 Xianyu AutoAgent Pro 2.0 核心引擎                                      │
│                                                                                                        │
│  ┌───────────────────────────┐      ┌───────────────────────────┐      ┌────────────────────────────┐  │
│  │   Multi-Account Hub       │      │   Event Bus & Dispatcher  │      │   Security & Guardrail     │  │
│  │  • 矩阵长连接池           │ ───► │  • 异步发布/订阅 (Pub/Sub)│ ───► │  • 确定性价格护栏 (100%硬控)│  │
│  │  • 独立住宅代理隔离       │      │  • 毫秒级多端广播        │      │  • 反 Prompt 注入 / 敏感词 │  │
│  │  • RGV587 滑块自愈探测    │      │  • 消息防抖聚合 (Debounce)│      │  • 二维码与导流实时拦截    │  │
│  └───────────────────────────┘      └───────────────────────────┘      └────────────────────────────┘  │
│                                                   │                                                    │
│                                                   ▼                                                    │
│  ┌───────────────────────────┐      ┌───────────────────────────┐      ┌────────────────────────────┐  │
│  │  Hybrid RAG Engine        │      │   Multi-Agent Swarm       │      │   Fulfillment & Orders     │  │
│  │  • 闲鱼二手黑话同义词网络 │ ───► │  • 双轨意图路由 (0ms/LLM) │ ───► │  • 一卡一密自动核销出库    │  │
│  │  • BM25 + Cosine TF-IDF   │      │  • 价格/技术/通用/视觉Agent│     │  • 拍下催付与到账即发货    │  │
│  │  • 动态特征置信度加权     │      │  • 情绪画像 (加急/高意向) │      │  • MTOP 协商成交一键改价   │  │
│  └───────────────────────────┘      └───────────────────────────┘      └────────────────────────────┘  │
└───────────────────────────────────────────────────┬────────────────────────────────────────────────────┘
                                                    │
                                                    ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   Web Copilot 人机协同一体化工作台                                     │
│  • 实时 SSE 对话流与 AI 思考决策透明展示                  • 快捷常用话术库抽屉与一键注入 (Canned Replies)│
│  • 人机协作三模切换 (AI托管 auto / 草稿待审 draft / 接管) • 买家情绪雷达画像 (🔥加急 / ⭐高意向 / ⚠️敏感)   │
│  • 全屏图片灯箱验机缩放预览 (Lightbox)                    • 一键改价成交闭环 & 会话审计记录复制导出    │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🌟 核心业务功能矩阵

| 业务域 | 核心模块 | 工业级实现特性 |
| :--- | :--- | :--- |
| **通信与协议** | **多账号矩阵与代理隔离** | 单账号独立住宅代理（HTTP/SOCKS5）网络隔离，彻底规避机房连带风控；无感 Token 刷新、心跳保持与断线自愈。 |
| **风控与挑战** | **RGV587 滑块辅助过盾** | 实时捕获闲鱼官方安全挑战链接，前端脉冲警报提示，支持外部滑动与一键复查恢复长连接。 |
| **议价与交易** | **确定性价格护栏** | 100% 规则约束硬拦截，大模型生成的任何破底价数字均被绝对拦截并强制矫正为底线价；阶梯式多轮降价谈判。 |
| **智能问答** | **工业级混合 RAG 引擎** | 二手交易黑话同义词概念泛化、BM25 词频逆文档加权与 TF-IDF 余弦向量混合召回，杜绝大模型答复幻觉。 |
| **持久存储** | **PostgreSQL 18 驱动** | 原生 `asyncpg` + `SQLAlchemy 2.0` 高并发连接池，支持千万级消息审计流水与多租户隔离。 |
| **极速缓存** | **Redis 8 分布式缓存** | 全新多线程 I/O 与内置模块，高频客服问询 `<2ms` 秒回，大幅削减云端大模型 API Token 开销。 |
| **自动履约** | **一卡一密自动发货池** | 拍下自动催付，买家付款即时原子核销并发放激活码、网盘卡密链接；支持低库存自动多渠道告警。 |
| **改价闭环** | **一键协商价真实改价** | 调用闲鱼 MTOP 原生接口同步下调订单待支付金额与商品挂牌售价，自动下发消息引导买家极速付款。 |
| **多模态验机** | **视觉验机与全屏灯箱** | 规范 3C（爱思报告、屏幕划痕、电池寿命）与二奢鉴定多模态 Prompt；支持原图全屏平移与无级缩放。 |
| **人机协同** | **Web Copilot 工作台** | 原生现代化界面，SSE 零延迟消息流，AI 思考过程透明可溯，常用话术库动态维护，支持一键导出对话流水。 |

---

## 📸 运行效果展示

<div align="center">
  <img src="./images/demo1.png" width="48%" alt="智能值守与人机协同">
  <img src="./images/demo2.png" width="48%" alt="阶梯式议价决策">
</div>
<div align="center">
  <img src="./images/demo3.png" width="48%" alt="多模态与专业问答">
  <img src="./images/log.png" width="48%" alt="服务运行日志流">
</div>

---

## 🚀 快速开始

### 环境依赖
- **Python**: 3.10+ (推荐 3.12 / 3.14)
- **数据库与缓存**:
  - **轻量单机模式**: 内置 SQLite 3 + 内存动态 LRU 缓存 (零外部依赖，开箱即用)
  - **生产高并发模式**: PostgreSQL 18 + Redis 8 (推荐使用 Docker Compose)

### 1. 克隆项目与安装依赖
```bash
git clone https://github.com/toms68pro/XianyuAutoAgent.git
cd autoagent

# 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装高性能生产依赖 (含 asyncpg, redis-py, fastapi, sqlalchemy 等)
pip install -r requirements.txt
```

### 2. 配置环境变量
检查并编辑 `.env` 文件：
```bash
# 复制或直接使用默认生成的 .env
cp .env.example .env
```
核心关键配置项：
```ini
# 大模型配置 (支持 通义千问 / DeepSeek / OpenAI / 本地 Ollama 等兼容接口)
API_KEY=your_llm_api_key
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-max

# 店铺初始凭据 (可选，也可启动后在 Web 界面直接扫码或添加)
COOKIES_STR=unb=xxxx; _m_h5_tk=xxxx; cookie2=xxxx

# 存储架构切换 (默认 SQLite，生产可切换为 PostgreSQL 18)
DATABASE_URL=sqlite+aiosqlite:///data/xianyu_v2.db
# REDIS_URL=redis://localhost:6379/0
```

### 3. 本地启动服务
```bash
python run.py
```
启动后访问 Web 管理工作台：
- **协同工作台地址**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **OpenAPI 交互文档**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **健康检查接口**: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

---

## 🐳 Docker 生产集群部署

项目已完整内置 **PostgreSQL 18** 和 **Redis 8** 的容器化编排支持，包含自动化健康检查与持久化数据卷。

### 1. 使用 Docker Compose 一键启动 (生产推荐)
```bash
# 构建并后台启动全部服务组件
docker-compose up -d --build
```
此时系统将自动拉起三个协作容器：
- `xianyu_postgres_18`: **PostgreSQL 18-Alpine** 生产数据库，挂载 `pgdata` 持久卷。
- `xianyu_redis_8`: **Redis 8-Alpine** 极速分布式缓存引擎，挂载 `redisdata` 持久卷。
- `xianyu_autoagent_pro`: **FastAPI 核心网关与客服工作台**，自愈等待数据库就绪后拉起。

### 2. 查看容器状态与日志
```bash
# 检查运行状态与健康检查 (healthy)
docker-compose ps

# 实时查看核心服务日志流
docker-compose logs -f xianyu-agent
```

### 3. 单独使用原生 Docker 运行 (轻量模式)
```bash
# 构建镜像
docker build -t xianyu-autoagent:2.0 .

# 启动容器
docker run -d \
  --name xianyu_agent \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/.env:/app/.env \
  --restart always \
  xianyu-autoagent:2.0
```

---

## 🛡️ 安全合规与架构准则

1. **绝对守价防线**：任何场景下，即使大模型生成低于底线的降价数字，系统后置数值抽取校验器也会 100% 硬拦截并纠偏，绝不破底成交。
2. **防诱导与反注入**：买家输入经过多重安全过滤与 Prompt 越狱检测，防范黑客套取提示词、泄露系统敏感配置。
3. **敏感词与导流拦截**：实时拦截微信号、手机号、暗语引流，保护店铺评分与账号资产安全。
4. **数据隐私保护**：采用本地 SQLite/PostgreSQL 存储，私有化部署，不向第三方上传任何店铺业务数据。

---

## 📄 开源许可证
本项目遵循 [GPL-3.0 开源许可证](LICENSE)。仅供技术研究与学习交流使用，使用本项目产生的一切交易风险与合规责任由使用者自行承担。
