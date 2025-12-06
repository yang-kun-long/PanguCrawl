import logging
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # 数据库配置
    DATABASE_URL: str

    # 盘古/SiliconFlow 配置
    PANGU_API_KEY: str
    PANGU_BASE_URL: str = "https://api.siliconflow.cn/v1"
    PANGU_MODEL_NAME: str = "ascend-tribe/pangu-pro-moe"

    # 【新增】密钥池配置 (默认为空字符串)
    SILICONFLOW_API_KEY_POOL: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

# ==========================================
# 【新增】解析 API Key 池
# ==========================================
# 1. 从 settings 中读取字符串
_pool_str = settings.SILICONFLOW_API_KEY_POOL

# 2. 按逗号切割，并去除首尾空格
if _pool_str:
    API_KEY_POOL = [k.strip() for k in _pool_str.split(",") if k.strip()]
else:
    API_KEY_POOL = []

# 3. (可选) 兼容旧的单个 Key 配置
# 如果池子是空的，但 PANGU_API_KEY 有值，就把它加进去
if not API_KEY_POOL and settings.PANGU_API_KEY:
    API_KEY_POOL.append(settings.PANGU_API_KEY)

# 打印日志确认
print(f"🔑 [Config] 已加载 API Key 池，共 {len(API_KEY_POOL)} 个密钥。")