"""M4b：工作流端到端测试（MemorySaver + 离线路径）。"""
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlmodel import select

from app.graph.workflow import build_workflow, invoke_agent
from app.models import Order, OrderStatus


@pytest.fixture()
def graph():
    return build_workflow(InMemorySaver())


def test_e2e_refund_request(graph, db_session, seed_users, seed_orders):
    uid = seed_users["zhangsan"].id
    result = invoke_agent(uid, "s1", "帮我退掉 T-SHIP-RECENT，商品质量有问题", graph=graph)

    assert "退款单号" in result["final_response"]
    assert result["refund_application"]["auto_approved"] is True
    assert result["needs_audit"] is False

    db_session.expire_all()
    order = db_session.exec(select(Order).where(Order.order_no == "T-SHIP-RECENT")).one()
    assert order.status == OrderStatus.REFUND_REQUESTED


def test_e2e_thread_continuity(graph, db_session, seed_users, seed_orders):
    uid = seed_users["zhangsan"].id
    invoke_agent(uid, "s2", "帮我退掉 T-SHIP-RECENT，质量有问题", graph=graph)

    # 第二轮不提订单号 —— 依赖线程态保留的 order_no
    second = invoke_agent(uid, "s2", "那我的退款进度怎么样了", graph=graph)
    assert "T-SHIP-RECENT" in second["final_response"]
    assert second["refund_status_result"]["found"] is True
    # 消息历史跨轮累积
    assert len(second["messages"]) >= 4


def test_e2e_policy_qa(graph, db_session, seed_users, seed_knowledge):
    result = invoke_agent(seed_users["zhangsan"].id, "s3", "退货政策是什么", graph=graph)
    assert "退货政策" in result["final_response"]


def test_e2e_general_chat(graph, db_session, seed_users):
    result = invoke_agent(seed_users["zhangsan"].id, "s4", "你好", graph=graph)
    assert "智能客服" in result["final_response"]
