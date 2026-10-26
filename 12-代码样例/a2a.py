"""R5 A2A最小落地: AgentCard发现 + message/send任务委派(JSON-RPC over HTTP)
A2A = Agent2Agent协议(Linux Foundation)。本平台: 差异分析Agent以A2A标准形态
对外暴露能力, 外部Agent(或event-consumer/其他系统)可按协议委派采购建议任务。
"""
from __future__ import annotations

AGENT_CARD = {
    "name": "fnb-diff-analysis-agent",
    "description": "连锁餐饮用量差异分析Agent: 差异查询/归因/采购建议(人在环)/需求预测",
    "url": "http://agent-runtime:8000/a2a",
    "version": "0.5.0",
    "capabilities": {"streaming": False, "pushNotifications": False},
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "skills": [
        {"id": "diff_query", "name": "用量差异查询",
         "description": "查询门店指定日期的理论vs实际用量差异(工具直答, 秒级)"},
        {"id": "procurement_suggest", "name": "采购建议(人在环)",
         "description": "生成DRAFT采购建议单, 等待人工审批"},
        {"id": "forecast", "name": "需求预测",
         "description": "未来7天需求预测, 含回测MAPE置信度与数据依赖声明"},
    ],
}
