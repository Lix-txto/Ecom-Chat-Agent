"""知识库 ETL：政策文件切块 → Embedding → 写入 knowledge_chunks。

运行：uv run python -m scripts.etl_policy
特性：按源文件幂等（重跑先删旧块再插入）；无 API Key 时用 Hash 嵌入（离线可跑）。
"""
from pathlib import Path

from sqlalchemy import delete
from sqlmodel import Session

from app.core.database import sync_engine
from app.graph.llm import get_embeddings
from app.models import KnowledgeChunk

DEFAULT_SOURCE = "shipping_policy.md"
POLICY_PATH = Path(__file__).resolve().parents[1] / "data" / DEFAULT_SOURCE
MAX_CHUNK_CHARS = 800


def _split_long(content: str, max_chars: int) -> list[str]:
    """超长小节按空行二次切分，续块补回标题保持语义。"""
    if len(content) <= max_chars:
        return [content]
    heading = content.splitlines()[0]
    chunks: list[str] = []
    buf = ""
    for para in content.split("\n\n"):
        candidate = f"{buf}\n\n{para}" if buf else para
        if len(candidate) > max_chars and buf:
            chunks.append(buf)
            buf = para
        else:
            buf = candidate
    if buf:
        chunks.append(buf)
    return [c if i == 0 or c.startswith("##") else f"{heading}\n{c}" for i, c in enumerate(chunks)]


def load_chunks(md_path: Path) -> list[dict]:
    """按 Markdown 二级标题切块。"""
    text = md_path.read_text(encoding="utf-8")
    # 去掉文档级 H1 标题行（小节标题 ## 保留）
    body = "\n".join(l for l in text.splitlines() if not l.startswith("# "))

    chunks: list[dict] = []
    for part in (p.strip() for p in body.split("\n## ")):
        if not part:
            continue
        section = part if part.startswith("## ") else f"## {part}"
        heading = section.splitlines()[0].lstrip("#").strip() or "政策"
        for piece in _split_long(section, MAX_CHUNK_CHARS):
            chunks.append({"heading": heading, "content": piece})
    return chunks


def run_etl(md_path: Path = POLICY_PATH, source: str = DEFAULT_SOURCE) -> int:
    if not md_path.exists():
        raise FileNotFoundError(f"政策文件不存在：{md_path}")

    chunks = load_chunks(md_path)
    embeddings = get_embeddings()
    vectors = embeddings.embed_documents([c["content"] for c in chunks])

    with Session(sync_engine) as session:
        # 幂等：先清掉该源的旧块
        session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source == source))
        for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
            session.add(
                KnowledgeChunk(
                    source=source,
                    chunk_index=i,
                    content=chunk["content"],
                    embedding=vec,
                    meta={"heading": chunk["heading"]},
                )
            )
        session.commit()
    return len(chunks)


def main() -> None:
    n = run_etl()
    print(f"✅ ETL 完成：{POLICY_PATH.name} → knowledge_chunks，共 {n} 个块")


if __name__ == "__main__":
    main()
