"""M4a：AgentState 状态定义与消息归约器行为。"""
from langchain_core.messages import HumanMessage
from langgraph.graph.message import add_messages

from app.graph.state import AgentState, Intent


class TestAgentState:
    def test_messages_reducer_appends(self):
        msgs = add_messages([], [HumanMessage(content="你好")])
        assert len(msgs) == 1
        msgs = add_messages(msgs, [HumanMessage(content="第二句")])
        assert len(msgs) == 2
        assert [m.content for m in msgs] == ["你好", "第二句"]

    def test_state_is_partial_dict(self):
        # total=False：节点只写自己负责的键，未写的键可省略
        state: AgentState = {"user_id": 2}
        assert state["user_id"] == 2

    def test_intent_enum_is_str(self):
        # str 枚举：state["intent"] 存枚举成员即存字符串，Checkpointer 可直接序列化
        assert Intent.REFUND_REQUEST == "refund_request"
        assert isinstance(Intent.POLICY_QA.value, str)
