import requests
from app.core.config import settings


def test_deepseek():
    headers = {
        "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": settings.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个简短助手"},
            {"role": "user", "content": "用一句话介绍电商智能Agent"}
        ],
        "temperature": 0.3
    }
    resp = requests.post(f"{settings.DEEPSEEK_BASE_URL}/v1/chat/completions", headers=headers, json=payload)
    if resp.status_code != 200:
        print(f"请求失败 code={resp.status_code}, {resp.text}")
        return False
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    print("✅ LLM 调用成功！")
    print("模型回复：", content)
    return True


if __name__ == "__main__":
    test_deepseek()
