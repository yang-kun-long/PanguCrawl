import logging
import httpx
from typing import List, Dict, Any
from app.config import settings

logger = logging.getLogger(__name__)


class PanguClient:
    def __init__(self):
        self.api_key = settings.PANGU_API_KEY
        self.base_url = settings.PANGU_BASE_URL
        self.model_name = settings.PANGU_MODEL_NAME

    async def chat_completion(
            self,
            messages: List[Dict[str, str]],
            temperature: float = 0.7,
            model: str = None,  # 👈 支持动态指定模型
            api_key: str = None  # 👈 支持动态传入 Key
    ) -> str:
        """
        调用 LLM 进行对话生成
        """
        # 1. 确定使用哪个 Key (优先使用传入的轮询 Key)
        active_key = api_key if api_key else self.api_key

        # 2. 确定使用哪个模型 (优先使用传入的快模型)
        target_model = model if model else self.model_name

        headers = {
            "Authorization": f"Bearer {active_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": target_model,
            "messages": messages,
            "stream": False,
            "max_tokens": 4096,
            "temperature": temperature,
            "top_p": 0.7,
            "top_k": 50,
            "frequency_penalty": 0.5,
            "n": 1
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers
                )
                resp.raise_for_status()
                data = resp.json()

                # 兼容 OpenAI 格式返回
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"]
                else:
                    return str(data)

            except httpx.HTTPStatusError as e:
                # 打印更详细的错误信息，方便调试
                error_msg = f"HTTP Error {e.response.status_code}: {e.response.text}"
                logger.error(f"LLM Call Failed: {error_msg}")
                raise Exception(error_msg)
            except Exception as e:
                logger.error(f"LLM Call Failed: {str(e)}")
                raise e


pangu_client = PanguClient()