"""M4b：节点层测试（离线确定性路径）。"""
import pytest
from langchain_core.messages import HumanMessage

from app.core.config import settings
from app.graph.llm import embedding_enabled, llm_enabled
from app.graph.nodes import (
    audit_check_node,
    generate_node,
    intent_router,
    order_query_node,
    refund_handle_node,
    retrieve_node,
)
from app.graph.tools import submit_refund_application
from app.models import Order, OrderStatus


def _state(text: str, **kwargs):
    return {"messages": [HumanMessage(content=text)], **kwargs}


class TestOfflineCanary:
    def test_llm_disabled_in_tests(self):
        # 金丝雀：若失败说明空串没有覆盖 .env（见排错表）
        assert settings.DEEPSEEK_API_KEY == ""
        assert settings.SILICONFLOW_API_KEY == ""
        assert llm_enabled() is False
        assert embedding_enabled() is False


class TestIntentRouter:
    def test_refund_request_with_order_no(self):
        upd = intent_router(_state("帮我退掉 T-SHIP-RECENT，商品质量有问题"))
        assert upd["intent"] == "refund_request"
        assert upd["order_no"] == "T-SHIP-RECENT"

    def test_refund_status_with_refund_no(self):
        upd = intent_router(_state("退款单 RF-20261028120000-ABC123 到账了吗"))
        assert upd["intent"] == "refund_status"
        assert upd["refund_no"] == "RF-20261028120000-ABC123"

    def test_refund_status_by_keywords(self):
        assert intent_router(_state("我的退款进度怎么样了"))["intent"] == "refund_status"

    def test_order_query_intent(self):
        upd = intent_router(_state("ORD-20261025-0001 到哪了"))
        assert upd["intent"] == "order_query"
        assert upd["order_no"] == "ORD-20261025-0001"

    def test_policy_qa_intent(self):
        assert intent_router(_state("退货政策是什么"))["intent"] == "policy_qa"

    def test_general_chat_intent(self):
        assert intent_router(_state("你好呀"))["intent"] == "general_chat"

    def test_entity_preserved_when_not_mentioned(self):
        # 抽不到实体时不得覆盖线程内已有值（多轮连续性的关键）
        upd = intent_router(
            _state("那退款进度怎么样了", order_no="T-SHIP-RECENT")
        )
        assert upd["intent"] == "refund_status"
        assert "order_no" not in upd


class TestOrderQueryNode:
    def test_found(self, db_session, seed_users, seed_orders):
        upd = order_query_node({"user_id": seed_users["zhangsan"].id, "order_no": "T-SHIP-RECENT"})
        info = upd["order_info"]
        assert info["found"] is True
        assert info["product_name"] == "蓝牙键盘"
        assert info["amount"] == "59.00"
        assert info["status"] == "shipped"

    def test_missing_order_no_guidance(self, db_session, seed_users, seed_orders):
        upd = order_query_node({"user_id": seed_users["zhangsan"].id})
        assert upd["order_info"]["found"] is False
        assert "订单号" in upd["order_info"]["message"]

    def test_not_found(self, db_session, seed_users, seed_orders):
        upd = order_query_node({"user_id": seed_users["zhangsan"].id, "order_no": "T-NOPE"})
        assert upd["order_info"]["found"] is False

    def test_other_users_order_hidden(self, db_session, seed_users, seed_orders):
        upd = order_query_node({"user_id": seed_users["zhangsan"].id, "order_no": "T-LISI-OWN"})
        assert upd["order_info"]["found"] is False


class TestRefundHandleNode:
    def test_auto_approved_small(self, db_session, seed_users, seed_orders):
        state = {
            "user_id": seed_users["zhangsan"].id, "order_no": "T-SHIP-RECENT",
            "intent": "refund_request",
            "messages": [HumanMessage(content="质量有问题想退掉")],
        }
        upd = refund_handle_node(state)
        assert upd["eligibility_result"]["eligible"] is True
        assert upd["refund_application"]["auto_approved"] is True

    def test_ineligible_beyond_window(self, db_session, seed_users, seed_orders):
        state = {
            "user_id": seed_users["zhangsan"].id, "order_no": "T-SHIP-OLD",
            "intent": "refund_request",
            "messages": [HumanMessage(content="想退")],
        }
        upd = refund_handle_node(state)
        assert upd["eligibility_result"]["eligible"] is False
        assert "refund_application" not in upd

    def test_manual_review_large(self, db_session, seed_users, seed_orders):
        state = {
            "user_id": seed_users["zhangsan"].id, "order_no": "T-PAID",
            "intent": "refund_request",
            "messages": [HumanMessage(content="不想要了")],
        }
        upd = refund_handle_node(state)
        assert upd["refund_application"]["needs_manual_review"] is True

    def test_status_by_refund_no(self, db_session, seed_users, seed_orders):
        uid = seed_users["zhangsan"].id
        created = submit_refund_application.invoke(
            {"order_no": "T-SHIP-RECENT", "user_id": uid, "reason": "质量问题"}
        )
        upd = refund_handle_node(
            {"user_id": uid, "intent": "refund_status", "refund_no": created["refund_no"]}
        )
        assert upd["refund_status_result"]["found"] is True

    def test_status_by_order_no(self, db_session, seed_users, seed_orders):
        upd = refund_handle_node(
            {"user_id": seed_users["zhangsan"].id, "intent": "refund_status",
             "order_no": "T-SHIP-RECENT"}
        )
        assert upd["refund_status_result"]["found"] is False  # 尚无退款记录

    def test_status_missing_identifiers_guidance(self, db_session, seed_users, seed_orders):
        upd = refund_handle_node({"user_id": seed_users["zhangsan"].id, "intent": "refund_status"})
        assert "退款单号" in upd["refund_status_result"]["message"]

    def test_request_missing_order_no_guidance(self, db_session, seed_users, seed_orders):
        upd = refund_handle_node(
            {"user_id": seed_users["zhangsan"].id, "intent": "refund_request",
             "messages": [HumanMessage(content="我要退款")]}
        )
        assert "订单号" in upd["refund_application"]["message"]


class TestAuditCheckNode:
    def test_needs_audit_true(self):
        upd = audit_check_node({"refund_application": {"needs_manual_review": True}})
        assert upd["needs_audit"] is True

    def test_needs_audit_false(self):
        assert audit_check_node({"refund_application": {"needs_manual_review": False}})["needs_audit"] is False
        assert audit_check_node({})["needs_audit"] is False


class TestRetrieveNode:
    def test_retrieves_relevant_chunk(self, db_session, seed_users, seed_knowledge):
        upd = retrieve_node(_state("7天内可以退货吗"))
        chunks = upd["retrieved_chunks"]
        assert len(chunks) == 3
        assert chunks[0]["meta"]["heading"] == "退货政策"
        assert chunks[0]["score"] > 0

    def test_empty_text_returns_empty(self):
        assert retrieve_node({"messages": []})["retrieved_chunks"] == []


class TestGenerateNode:
    def test_order_found_template(self):
        state = {"intent": "order_query", "order_info": {
            "found": True, "order_no": "T-SHIP-RECENT", "product_name": "蓝牙键盘",
            "quantity": 1, "amount": "59.00", "status": "shipped",
            "created_at": "2026-10-25T12:00:00+00:00",
        }}
        out = generate_node(state)
        text = out["final_response"]
        assert "蓝牙键盘" in text and "已发货" in text and "¥59.00" in text
        assert out["messages"][0].content == text  # 回复进消息历史

    def test_order_missing_template(self):
        state = {"intent": "order_query", "order_info": {"found": False, "message": "请提供订单号"}}
        assert "订单号" in generate_node(state)["final_response"]

    def test_refund_success_template(self):
        state = {"intent": "refund_request", "refund_application": {
            "success": True, "message": "退款申请已自动通过",
            "refund_no": "RF-20261028120000-ABC123", "status": "auto_approved",
        }}
        assert "RF-20261028120000-ABC123" in generate_node(state)["final_response"]

    def test_refund_ineligible_template(self):
        state = {"intent": "refund_request",
                 "eligibility_result": {"eligible": False, "reason": "已超过 7 天退货期，无法退款"}}
        assert "退货期" in generate_node(state)["final_response"]

    def test_refund_status_template(self):
        state = {"intent": "refund_status", "refund_status_result": {
            "found": True, "refund_no": "RF-20261028120000-ABC123", "order_no": "T-SHIP-RECENT",
            "product_name": "蓝牙键盘", "status": "auto_approved", "amount": "59.00",
            "requested_at": "2026-10-28T12:00:00+00:00",
        }}
        assert "已通过" in generate_node(state)["final_response"]

    def test_policy_template(self):
        state = {"intent": "policy_qa", "retrieved_chunks": [
            {"source": "t", "content": "## 退货政策\n7 天内可退", "meta": {"heading": "退货政策"}, "score": 0.9},
        ]}
        assert "退货政策" in generate_node(state)["final_response"]

    def test_general_template(self):
        assert "智能客服" in generate_node({"intent": "general_chat"})["final_response"]
