# config.example.py —— config.py 的示例模板，复制此文件为 config.py 后填入真实 API Key
import os

DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"
# 可选模型：deepseek-flash（支持图片输入，实测可用）
# 注意：deepseek-v4-pro 不支持视觉输入，请勿用于本项目
DEEPSEEK_MODEL = "deepseek-flash"
# 填入你的真实 Key（也可通过环境变量 DEEPSEEK_API_KEY 设置，优先级更高）
DEEPSEEK_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # ← 替换为你的 Key

TEMPERATURE = 0.1
# deepseek-flash 是推理模型，会先消耗 token 思考再输出正文，必须留足额度
MAX_TOKENS = 8192
# 推理模型复杂题"思考+输出"可达 60~180 秒，超时不能设太短
REQUEST_TIMEOUT = 180
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw_responses")
RESULT_DIR = os.path.join(DATA_DIR, "results")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
LOG_DIR = os.path.join(DATA_DIR, "logs")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
SAMPLE_DIR = os.path.join(DATA_DIR, "sample_images")
OUTPUT_DIR = os.path.join(os.path.dirname(PROJECT_ROOT), "output")
KG_DATA_FILE = os.path.join(PROJECT_ROOT, "knowledge", "knowledge_data.json")

CACHE_ENABLED = True
LOG_LEVEL = "INFO"
LOG_FILE = os.path.join(LOG_DIR, "answer_mark.log")

# ---------- SQLite 数据库（学情统计页面数据源，与 config.py 保持一致） ----------
# 判题记录数据库文件（首次运行自动创建）
DB_FILE = os.path.join(DATA_DIR, "answer_mark.db")
# 及格线比例（得分率 >= 该值视为及格，用于统计及格率）
PASS_RATE = 0.6

HOST = "0.0.0.0"
PORT = 8000
CORS_ORIGINS = ["*"]
DEFAULT_FULL_SCORE = 10