"""LLM 与 Embedding 工厂（宪法 v2，随 config 修订同步）。

供应商宪章：Chat 走 DeepSeek，Embedding 走硅基流动 bge-m3。
两家均提供 OpenAI 兼容协议 → 复用 langchain-openai 客户端，无需额外 SDK。

双通道设计保持不变：
- 有 API Key → ChatOpenAI(base_url=DeepSeek) / OpenAIEmbeddings(base_url=SiliconFlow)
- 无 Key   → get_chat_model 返回 None（节点走确定性关键词/模板兜底），
             get_embeddings 返回 HashEmbeddings（离线 RAG 测试）。

与旧版（OpenAI/Qwen + LLM_PROVIDER 开关）的差异：两个通道各自独立、
各绑定一家供应商，可用性只取决于对应 Key 是否配置，无切换开关。
"""
import hashlib
import math
import re
from typing import Optional

from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.core.config import settings

# ---------- 离线嵌入 ----------

_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """中文按字符二元组、英文/数字按词切分（无分词依赖的轻量方案）。"""
    tokens: list[str] = []
    for m in _CJK_RUN_RE.finditer(text):
        run = m.group()
        if len(run) >= 2:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
        else:
            tokens.append(run)
    tokens.extend(_ASCII_WORD_RE.findall(text.lower()))
    return tokens


class HashEmbeddings(Embeddings):
    """确定性本地嵌入：token 哈希到固定维度并归一化。

    余弦相似度 ≈ token 重叠度，仅供离线开发/测试；
    维度跟随 settings.EMBEDDING_DIM（当前 = 1024，与 bge-m3 一致），
    离线/在线数据写入同一 vector 列。
    """

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _tokenize(text):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            vec[h % self.dim] += 1.0 if (h >> 63) & 1 == 0 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


# ---------- 工厂 ----------


def llm_enabled() -> bool:
    """Chat 通道（DeepSeek）是否可用。"""
    return bool(settings.DEEPSEEK_API_KEY)


def embedding_enabled() -> bool:
    """Embedding 通道（硅基流动）是否可用。"""
    return bool(settings.SILICONFLOW_API_KEY)


def get_chat_model() -> Optional[ChatOpenAI]:
    if not llm_enabled():
        return None
    return ChatOpenAI(
        model=settings.DEEPSEEK_MODEL,
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        temperature=settings.LLM_TEMPERATURE,
        timeout=settings.LLM_TIMEOUT_SECONDS,
    )


def get_embeddings() -> Embeddings:
    if not embedding_enabled():
        return HashEmbeddings(dim=settings.EMBEDDING_DIM)
    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=settings.SILICONFLOW_API_KEY,
        base_url=settings.SILICONFLOW_BASE_URL,
        check_embedding_ctx_length=False,  # 非 OpenAI 模型：禁用 tiktoken 预切分
    )
