# DeepSeek-Vision 答卷智能判题系统

> 基于 DeepSeek-Vision v1.5 多模态大模型的轻量化答卷智能判题系统
> 毕业设计项目 · 前后端分离 + Gradio 双模式

## 项目简介

本系统实现"增强后的答卷图片 → 多模态识别 → 解题要素抽取 → 知识图谱评估 → 多维度判题反馈"的完整链路，
可用于批改数学、含图表题、含简易代码作答等场景，自动给出 **总分、扣分点、错误类型、薄弱知识点、教学化建议**。

**说明**：本项目不包含图像增强/退化感知模块，输入的答卷图片**已为预处理完成、增强后的图片**。

---

## 目录结构

```
DeepSeek-AnswerMark/
├── backend/                后端 Python（前后端分离架构）
│   ├── config.py           配置文件（API Key、模型名、路径）
│   ├── config.example.py   配置示例
│   ├── api_client.py       DeepSeek-Vision API 封装（重试/限速）
│   ├── main.py             FastAPI 入口（REST API + 静态文件）
│   ├── main_cli.py         命令行批量入口
│   ├── app_gradio.py       Gradio 兼容入口
│   ├── modules/
│   │   ├── m1_feature_extract.py    模块1：多模态特征提取
│   │   ├── m2_semantic_align.py     模块2：跨模态语义对齐+要素抽取
│   │   ├── m3_kg_evaluate.py        模块3：知识图谱+多维评估
│   │   └── pipeline.py              全流程流水线
│   ├── knowledge/
│   │   ├── kg_builder.py            networkx 知识图谱构建
│   │   └── knowledge_data.json      知识点/关系/同义词数据
│   ├── prompts/
│   │   └── prompt_templates.py      提示词模板（集中管理）
│   ├── utils/
│   │   ├── io_helper.py             图片/JSON/CSV IO
│   │   ├── cache.py                 结果缓存（图片MD5）
│   │   └── logger.py                日志
│   ├── tests/
│   │   ├── demo.py                  单文件Demo
│   │   ├── accuracy_test.py         准确率测试
│   │   └── ground_truth.json        测试标准答案
│   └── data/                        运行期产物（自动创建）
├── frontend/               前端 HTML/CSS/JS（纯静态，零构建）
│   ├── index.html
│   ├── style.css
│   └── app.js
├── output/                 CSV汇总等导出
├── 需求文档.md             项目需求文档
├── README.md
├── requirements.txt
├── .gitignore
├── start_backend.ps1       一键启动后端（推荐）
├── start_gradio.ps1        一键启动 Gradio 版
└── start_frontend.ps1      一键启动前端静态服务
```

---

## 快速开始（Windows / PowerShell）

### 1. 准备 API Key

复制 `backend/config.example.py` 为 `backend/config.py`，填入你的 DeepSeek API Key：
```powershell
cp backend\config.example.py backend\config.py
# 用编辑器把 DEEPSEEK_API_KEY 改为你的真实 Key
```

### 2. 一键安装与启动

```powershell
# 双击或在终端执行
.\start_backend.ps1
```
脚本会自动：
- 检测本机已安装的 Python 3.10~3.12（跳过 Microsoft Store 占位符）
- 安装 `requirements.txt` 中所有依赖
- 启动 FastAPI 服务在 http://localhost:8000

### 3. 打开前端

任选一种方式：

- **方式A：FastAPI 静态托管** —— 直接访问 http://localhost:8000/web/ （推荐，无需另起服务）
- **方式B：VSCode Live Server** —— 右键 `frontend/index.html` → Open with Live Server
- **方式C：自带静态服务**
  ```powershell
  .\start_frontend.ps1    # http://localhost:5500
  ```

### 4. 不想用前后端分离？

直接用 Gradio 一键启动：
```powershell
.\start_gradio.ps1
# 访问 http://localhost:7860
```

---

## 命令行批量判题

不启 Web 服务，命令行批量跑：

```powershell
# 在项目根目录
python backend\main_cli.py --images img1.jpg img2.jpg --context "解方程 x+1=3" --full 10
```
结果会保存到 `output/批量结果.json` 和 `output/判题结果汇总.csv`。

---

## Demo 与准确率测试

```powershell
# 单张示例答卷全流程跑通
python -m tests.demo --image backend\data\sample_images\sample.jpg --save

# 批量准确率测试（需要 ground_truth.json 中有真实样本）
python backend\tests\accuracy_test.py --csv backend\output\accuracy_report.csv
```

`ground_truth.json` 示例：
```json
[{
  "image_path": "backend/data/sample_images/p1.jpg",
  "context": "解方程 x + 1 = 3",
  "full_score": 10,
  "expected_final_verdict": "incorrect",
  "expected_error_types": ["calculation_error"],
  "expected_weak_points": ["MATH-LIN-1V"]
}]
```

---

## REST API 速览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/judge` | 单张答卷判题 |
| POST | `/api/judge/batch` | 多张答卷批量判题 |
| GET | `/api/knowledge` | 获取知识图谱全部节点/边 |
| GET | `/api/results` | 获取判题历史摘要列表 |
| GET | `/api/results/{image_id}` | 获取单次判题完整结果 |
| GET | `/api/analytics/*` | 学情统计（得分分布/错题排行/知识点掌握度等） |

> 说明：本项目为单机本地演示版，**未启用登录鉴权**，打开页面即可使用。

完整 OpenAPI 文档：访问 http://localhost:8000/docs

---

## 三大核心模块对照表

| 模块 | 文件 | 输入 | 输出 |
|------|------|------|------|
| 模块1 多模态特征提取 | `m1_feature_extract.py` | 增强后答卷图片 | modality_recognition / raw_text |
| 模块2 语义对齐+要素抽取 | `m2_semantic_align.py` | M1结果 + 可选题目信息 | known_conditions / steps / final_answer / error_summary |
| 模块3 知识图谱评估 | `m3_kg_evaluate.py` | M2结果 + 知识图谱 | total_score / weak_points / feedback |

---

## 轻量化策略

1. **提示词优化**：所有 prompt 集中在 `prompts/prompt_templates.py`，按 `PROMPT_VERSION` 管理版本，便于论文对比实验。
2. **结果缓存**：以"图片 MD5 + 提示词版本"为键的 JSON 缓存，避免重复 API 调用（`data/cache/`）。
3. **批量处理**：支持多文件上传与命令行批量，汇总 CSV 输出。

---

## 项目依赖（仅 6 个第三方库）

```
requests, networkx, gradio, Pillow, numpy, pandas
+ 前后端分离所需的 fastapi, uvicorn, python-multipart
```

**禁止引入**：PyTorch / TensorFlow 等重型深度学习框架（毕设轻量化要求）。

---

## 常见问题

**Q1：DeepSeek-Vision v1.5 接口地址怎么填？**
默认 `https://api.deepseek.com/v1`，模型 `deepseek-vision-v1.5`，可在 `backend/config.py` 调整。

**Q2：API 返回 401 / 402？**
检查 `DEEPSEEK_API_KEY` 是否正确、账户余额。

**Q3：识别结果乱码？**
图片请用清晰、未压缩过度的 jpg/png，过大图片会自动缩放。

**Q4：缓存想清空？**
删除 `backend/data/cache/` 目录，或调用 `python -c "from utils.cache import clear_all; clear_all()"`。

**Q5：API Key 怎么配置？**
推荐用环境变量（不落盘、不进代码）：
```powershell
$env:DEEPSEEK_API_KEY = "sk-你的Key"
.\start_backend.ps1
```
也可直接编辑 `backend/config.py` 填入（该文件已被 `.gitignore` 屏蔽，不会进版本库）。
Key 未配置时服务仍可启动（健康检查/历史记录正常），仅判题接口会返回明确的配置提示。

---

## 答辩演示技巧（重要）

deepseek-flash 是推理模型，单张复杂答卷判题耗时可达 60~180 秒，现场干等会尴尬。建议：

1. **提前预热缓存**：答辩前把要演示的图各跑一遍，结果会缓存到 `backend/data/cache/`，现场二次判题秒出：
   ```powershell
   python backend\main_cli.py --images backend\data\sample_images\test1.jpg --context "题目内容" --full 10
   ```
2. **选小图**：演示用题量少、字迹清晰的答卷（1~2 道小题最佳）。
3. **提前 10 分钟启动服务**，浏览器确认 `http://localhost:8000/api/health` 返回 ok。

---

## 论文相关

- 需求文档：`需求文档.md`
- 提示词版本：在 `prompts/prompt_templates.py` 顶部 `PROMPT_VERSION` 维护
- 准确率测试数据：`backend/data/results/` + `output/判题结果汇总.csv`
- API 原始返回：`backend/data/raw_responses/` 用于论文误差分析

---

## License

仅用于毕设学习与论文研究。