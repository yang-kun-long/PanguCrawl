您说得对，之前的启动流程确实比较通用，没有结合我们刚刚增加的 `check_keys.py` 以及您实际的文件结构（如 `run.py` 启动方式、Conda 环境等）。

基于您提供的**完整目录结构**和我们刚刚实现的**所有功能**，这是完全对齐现状的 **README.md**。

请直接复制以下内容（已修正启动流程，加入了密钥体检步骤）：

-----

# 🕸️ PanguCrawl (盘古爬虫)

> **基于 LLM 决策委员会与统计学去噪的下一代深网内容爬虫系统**
>
> *Next-Gen Deep Web Crawler powered by Multi-Agent Council & Statistical Denoising*

## 📖 项目简介

**PanguCrawl** 是一个 AI 原生的通用网页爬虫与结构化提取系统。不同于传统的基于规则（Regex/XPath）的爬虫，它利用 **大语言模型（LLM）** 的语义理解能力来驱动爬取路径规划、网页结构分析和数据提取。

本系统旨在解决传统爬虫“**泛化能力差**”和“**抗干扰能力弱**”的痛点，通过引入**多智能体辩论**、**统计学去噪**以及**意图驱动的 Schema 发现**机制，能够精准地从复杂的网页（如包含大量导航干扰的页面）中提取用户真正关心的结构化数据。

-----

## ✨ 核心创新点 (Highlights)

1.  **🧠 AI 决策委员会 (Multi-Agent Council)**

      * 摒弃单一模型的“幻觉”风险，由 **Explorer (激进派)** 发现路径、**Critic (保守派)** 过滤噪音、**Moderator (主持人)** 综合决策。
      * 在保证泛化能力的同时，有效避免“乱爬”和“漏爬”。

2.  **🧹 统计学结构化去噪 (Statistical Denoising)**

      * **物理切除噪音**：利用“文档频率 (Document Frequency)”算法，自动识别并物理切除组内页面共有的导航栏、页脚、侧边栏。
      * **无需 Prompt**：不依赖 AI 猜测，直接让 AI 看到去噪后的纯净正文，极大提升提取准确率。

3.  **🎯 意图驱动的 Schema 发现 (Intent-Driven Discovery)**

      * 将用户的自然语言需求（如“提取教授信息”）注入到结构发现阶段。
      * 结合“负面约束”，强迫 AI 忽略菜单链接，只构建与需求强相关的字段结构。

4.  **🚀 自适应高并发架构 (Adaptive High-Concurrency)**

      * **密钥轮询 (Key Rotation)**：支持 API Key Pool，自动轮询多个账号 Key 以突破 Rate Limit。
      * **模型接力 (Model Fallback)**：当主模型（如 Qwen-7B）拥堵报 503 时，毫秒级自动切换至备用模型（如 DeepSeek-V3），确保任务不卡死。

5.  **🔗 智能分组与去重**

      * 基于 URL 模式聚类，将海量页面压缩为少量“模板簇”。
      * 基于正文指纹（Content Hash）去重，避免重复提取，节省 Token 成本。

-----

## 🛠️ 技术栈

  * **Backend**: Python (FastAPI), SQLAlchemy, Pydantic
  * **Crawler Core**: Crawl4AI (AsyncWebCrawler)
  * **LLM Provider**: SiliconFlow (支持 Qwen-7B/72B, DeepSeek-V3, Pangu-Pro)
  * **Database**: PostgreSQL (JSONB 存储非结构化数据)
  * **Frontend**: Vue 3, Element Plus, Markdown-it
  * **Key Features**: Key Polling, SSE-like Terminal, Docker Support

-----

## 🚀 启动流程 (Quick Start)

### 1\. 环境准备

确保本地已安装：

  * **Python 3.10+** (建议使用 Conda)
  * **Node.js 16+** (用于前端)
  * **PostgreSQL** (推荐使用 Docker 启动)

### 2\. 数据库与配置

1.  **启动数据库**：
    确保 PostgreSQL 已在运行。推荐使用项目自带的 Docker 配置：

    ```bash
    docker-compose up -d
    ```

    *注意：默认端口配置为 **5435** (见 `docker-compose.yml`)。*

2.  **配置环境变量**：
    复制 `.env.example` 为 `.env`，并填入以下关键信息：

    ```properties
    # 数据库连接 (注意端口号需与 docker-compose 一致)
    DATABASE_URL=postgresql://postgres:password@localhost:5435/pangu_crawl

    # 硅基流动 API 配置
    PANGU_BASE_URL=https://api.siliconflow.cn/v1
    PANGU_MODEL_NAME=deepseek-ai/DeepSeek-V3

    # 【核心】API Key 密钥池 (用于高并发轮询)
    # 多个 Key 用英文逗号分隔，不要加空格
    SILICONFLOW_API_KEY_POOL=sk-key1,sk-key2,sk-key3,sk-key4,sk-key5
    ```

### 3\. 后端部署

1.  **安装依赖**：

    ```bash
    pip install -r requirements.txt
    ```

2.  **API Key 健康体检** (新增功能)：
    运行此脚本检查你的 Key 是否有效以及响应延迟：

    ```bash
    python check_keys.py
    ```

    *确保至少有一个 Key 显示 `✅ 正常`。*

3.  **初始化数据库表结构**：

    ```bash
    python init_db.py
    ```

4.  **启动后端服务**：

    ```bash
    python run.py
    ```

    *服务将运行在 `http://0.0.0.0:8001`*

### 4\. 前端部署

1.  **进入前端目录**：

    ```bash
    cd web-ui
    ```

2.  **安装依赖**：

    ```bash
    npm install
    ```

3.  **启动开发服务器**：

    ```bash
    npm run dev
    ```

    *访问地址通常为 `http://localhost:5173`*

-----

## 🖥️ 使用指南

1.  打开浏览器访问前端地址。
2.  **输入目标**：在搜索框输入目标网址（如某学院官网）和具体需求（如“提取教授的姓名、职称和邮箱”）。
3.  **启动任务**：点击“启动”，系统将自动进行：
      * **AI 辩论**：规划爬取路径（可在“指挥中心”Tab 查看直播）。
      * **爬取与聚类**：抓取页面并按模板分组。
      * **去噪与提取**：自动切除导航栏，提取结构化数据。
4.  **查看结果**：
      * **📊 结构化数据**：查看生成的 Excel 风格表格，支持导出 JSON。
      * **📄 网页透视**：打开“AI 视角(去噪)”开关，对比查看去噪前后的网页内容。
5.  **历史记录**：点击左上角的时钟图标，可回溯查看之前的任务结果。

-----

## 📂 项目结构

```text
📂 PanguCrawl
├── app
│   ├── services
│   │   ├── analyzer.py          # 结果汇总与分析
│   │   ├── crawler.py           # 网页抓取引擎
│   │   ├── extractor.py         # [核心] 去噪/去重/高并发提取
│   │   ├── llm.py               # LLM 客户端
│   │   ├── planner.py           # 多智能体规划器
│   │   ├── schema_discovery.py  # [核心] 意图驱动 Schema 发现
│   │   └── structure_scorer.py  # 结构化评分与聚类
│   ├── config.py                # 配置管理 (Key Pool)
│   ├── main.py                  # API 入口与路由
│   ├── models.py                # 数据库模型
│   └── utils.py                 # 工具函数
├── web-ui                       # Vue 3 前端
├── check_keys.py                # [工具] API Key 健康检查
├── init_db.py                   # [工具] 数据库表初始化
├── run.py                       # [启动] 后端启动脚本
└── ...
```

## 🤝 贡献与支持

欢迎提交 Issue 和 Pull Request！

-----

**License**: MIT
**Author**: PanguCrawl Team