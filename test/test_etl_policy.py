"""M4b：政策 ETL 脚本测试（离线 Hash 嵌入）。"""
from pathlib import Path

from sqlmodel import select

from app.models import KnowledgeChunk
from scripts.etl_policy import run_etl


def _chunks(db_session):
    return db_session.exec(
        select(KnowledgeChunk).where(KnowledgeChunk.source == "shipping_policy.md")
    ).all()


def test_etl_inserts_chunks(db_session):
    n = run_etl()
    assert n >= 5
    rows = _chunks(db_session)
    assert len(rows) == n
    assert len({r.chunk_index for r in rows}) == n      # 唯一性
    assert all(r.embedding is not None for r in rows)   # 嵌入已写入
    assert any("退货" in (r.meta or {}).get("heading", "") for r in rows)


def test_etl_idempotent(db_session):
    run_etl()
    first = len(_chunks(db_session))
    run_etl()
    assert len(_chunks(db_session)) == first            # 重跑不重复


def test_chunks_retrievable(db_session):
    from app.graph.nodes import retrieve_node
    from langchain_core.messages import HumanMessage

    run_etl()
    upd = retrieve_node({"messages": [HumanMessage(content="退货政策是什么")]})
    chunks = upd["retrieved_chunks"]
    assert chunks and "退货" in chunks[0]["content"]
