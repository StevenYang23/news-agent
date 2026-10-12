# Daily Buy-side Insights

每日抓取公开的买方研报、播客与视频，用 **DeepSeek** 生成中英双语的美股 insight 汇总，并部署为**公网静态网站**（GitHub Pages），随时随地可看、每日自动更新。

## 核心规则

- **只保留近 30 天**的内容（滚动窗口，每次刷新自动清理更早的条目）
- **只考虑美股相关**内容（LLM 判定，非美股自动过滤）
- **新 → 旧**排序
- **中英双语**输出

## 架构

```
News_Agent/
├── config/sources.json          # 来源配置（type/kind/feed/active）
├── src/
│   ├── config.py                # 环境变量 + 来源加载
│   ├── state.py                 # JSON 状态（site/insights.json 即数据+去重状态）
│   ├── ingest/                  # 抓取：RSS / 网页 / 播客 / YouTube
│   ├── llm/deepseek.py          # DeepSeek 双语摘要
│   └── pipeline/daily.py        # 每日流水线编排
├── site/                        # 可部署的静态站点
│   ├── index.html / style.css / app.js
│   └── insights.json            # 生成的数据（提交到 git，同时是去重状态）
├── scripts/
│   ├── run_daily.py             # 跑一次刷新 → 更新 site/insights.json
│   ├── serve.py                 # 本地预览（纯 stdlib，无依赖）
│   └── register_task.ps1        # 本地 Windows 定时任务（可选）
├── .github/workflows/daily.yml  # GitHub Actions：每日定时刷新 + 部署 Pages
└── requirements.txt
```

**无服务器、无数据库**：数据就是 `site/insights.json` 一个文件，提交到 git 即持久化；前端直接读它渲染。本地和 GitHub Actions 用同一套代码。

## 本地使用

```powershell
# 1. 环境 + 依赖
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. 配置 key
Copy-Item .env.example .env   # 填入 DEEPSEEK_API_KEY=sk-...

# 3. 跑一次刷新（抓取 → 摘要 → 写 site/insights.json）
python scripts\run_daily.py

# 4. 本地预览
python scripts\serve.py        # http://127.0.0.1:8000
```

## 部署到 GitHub Pages（公网）

### 1. 推代码到 GitHub

```powershell
git init
git add .
git commit -m "initial"
gh auth login                  # 浏览器登录一次
gh repo create news-agent --public --source=. --push
```

### 2. 配置密钥与 Pages

```powershell
# 把 DeepSeek key 存为 Actions secret
gh secret set DEEPSEEK_API_KEY --body "sk-你的key"

# 启用 Pages（Actions 方式部署）
gh api --method POST repos/:owner/:repo/pages -f build_type=workflow
```

> 把 `:owner`/`:repo` 换成你的 GitHub 用户名 / 仓库名。

### 3. 触发第一次部署

```powershell
gh workflow run daily.yml
```

之后每天 **22:30 UTC**（美股收盘后）自动刷新并部署；也可在 Actions 页面手动 `Run workflow`。

网站地址：`https://<你的用户名>.github.io/news-agent/`

## 每日刷新原理

`daily.yml` 每次运行：拉取代码 → 装依赖 → `run_daily.py`（抓取近 30 天 → 过滤已处理的 → LLM 双语摘要 → 判定美股相关性 → 滚动删除旧数据 → 写回 `insights.json`）→ 提交数据变更 → 部署 Pages。

## 转录（可选，用于纯音频播客）

播客音频转录用 `faster-whisper`（`ctranslate2` 已有 cp314 wheel，可直接装）：

```powershell
pip install faster-whisper
```

代码默认 `small` 模型 + CPU + int8，可在 `src/ingest/transcribe.py` 调整。

> 提示：很多播客官方会发文字稿（如 Wall Street Breakfast），优先抓文字稿，比转录更快更准。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | — | 必填 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容接口 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名 |
| `DATA_DIR` | `data` | 音频缓存目录 |

## 免责声明

内容来自公开渠道，仅供研究参考，不构成投资建议。
