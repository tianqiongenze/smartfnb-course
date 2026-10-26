# ADR集（Architecture Decision Records）· R6清偿

> 状态：2026-10-25　|　本文件清偿审查报告§3矩阵中4项"勘察未用/悬空"决策，并记录R1-R5重构中的2项新决策。

---

## ADR-0009 Apollo Router vs Spring GraphQL BFF（D3清偿）

- **决策**：Phase 0-2 采用 svc-portal（Spring for GraphQL）作为组合BFF，**不引入Apollo Router**。
- **理由**：①子图数量4个，BFF编译期组合已满足"一次请求取全"；②Router为Rust二进制，本集群CPU代次<x86-64-v2存在无法exec的风险（见ADR-0012实证）；③省一个独立网关组件的运维面。
- **revisit条件**：子图>8个 或 需要跨域联邦join 时重评；届时优先评估Hive Router（同Rust风险）与自研组合层。

## ADR-0010 NebulaGraph 暂不启用

- **决策**：食材替代关系/BOM图谱检索暂不接入NebulaGraph；别名解析用 ingredient.aliases JSON + Redis缓存满足。
- **理由**：当前查询模式（单跳别名/BOM）用关系型+JSON即可，图谱多跳需求（如"替代品联动调拨"）属Phase 4+场景。
- **revisit条件**：出现3跳以上推荐/溯源查询时启用（集群已有Nebula v3.8.3，接入成本低）。

## ADR-0011 Istio 暂不启用

- **决策**：服务间东西向用K8S Service + 客户端负载均衡；金丝雀用双Deployment切流。
- **理由**：20 Pod规模下sidecar网格的运维/资源开销大于收益；压测显示Service路径P95<10ms非瓶颈。
- **revisit条件**：服务数>15 或需要mTLS合规（等保三级测评项）时启用Istio ambient模式。

## ADR-0012 OTel采集器形态（新增，R7）

- **决策**：OTel SDK（GenAI语义约定span）→ **Console导出器 → Pod stdout → Loki聚合**；OTLP端点可选叠加。
- **理由**：官方collector镜像（0.116.0及contrib）二进制要求x86-64-v2，本集群CPU（Xeon E5代）不支持exec——**三次实证**（otelcol、otelcol-contrib、mysql8同因失败）。
- **影响**：span以日志形式落Loki（`gen_ai.*`关键字可检索），牺牲结构化查询效率换取零新增基建；GPU/新硬件到位后切换OTLP→Tempo。
- **已落地证据**：agent-runtime日志可见`gen_ai.agent/tool/completion` span。

## ADR-0013 语义缓存嵌入实现（新增，R3）

- **决策**：语义缓存嵌入默认用**字符3-gram稳定哈希（crc32, 256维, COSINE）**；qwen3-embedding模型实现保留为可选（EMBED_IMPL=model）。
- **理由**：①qwen3-embedding:0.6b在本集群实测冷加载60-100s/请求40s+（worker负载19/64+线程抖动），**无法满足在线命中检查≤2s预算**；②哈希嵌入<1ms、确定性、跨进程一致（发现并修复了Python内建hash()进程随机化缺陷）；③近义改写（怎么/如何/语序变化）验证可命中，阈值HIT≥0.93/REF≥0.80。
- **影响**：哈希嵌入对深层语义改写（同义不同字）召回弱于模型嵌入——该类流量落入LLM路径并由add_pair_async自动学习回写，命中率随运行时间上升。
- **revisit条件**：GPU节点或低载窗口批量重嵌入时切回model实现（数据结构兼容，仅向量维度不同需双collection）。

## ADR-0014 Pulsar生产网关形态（新增，R2）

- **决策**：Java端发布走 **event-consumer的HTTP网关(:8081/publish)** → Pulsar python客户端生产；不引入Java Pulsar客户端。
- **理由**：TiDB/Pulsar shared集群的admin REST在该版本未开放HTTP生产(404)；Java客户端引入SDK版本矩阵成本>一个48行网关服务。
- **revisit条件**：Pulsar升级至开放REST生产的版本，或Java侧需要exactly-once语义时引入原生客户端。

## ADR-0015 主推理模型维持 qwen3:8b（Hermes实验结论，R10）

- **决策**：线上LLM_MAIN维持qwen3:8b；hermes3:8b作为GPU环境首选备选（模型已入hostPath库）。
- **实验数据**（tools/llm-bench/hermes_vs_qwen.py，n=6）：
  | 模型 | 结构化工具遵循 | 平均延迟 |
  |---|---|---|
  | hermes3:8b | **4/6 (66.7%)** | **11.6s** |
  | qwen3:8b | 1/6 (16.7%) | 70.9s |
  hermes单请求工具调用53s冷启动后稳定，且get_diff参数100%正确。
- **不立即切换原因**：fnb-ollama驻留3模型（8b+4b+embedding）下hermes加载引发反复驱逐（实测单次60-120s）——2节点CPU混部环境不可承载4模型驻留。
- **revisit条件**：GPU节点到位或LLM流量显著上升时，hermes3:8b为主、qwen3:4b为快路径。

## ADR-0016 portal→agent WebClient 显式 JDK HttpClient HTTP/1.1（V3回归新增，2026-10-26）

- **状态**：已采纳（svc-portal 0.1.3）
- **背景**：无头浏览器回归发现 /api/agent/chat 全链路 500。排查：pom 排除 reactor-netty 后，Spring WebClient 回落到 JDK HttpClient，其对 `text/event-stream` 目标自动附加 `Connection: Upgrade` + `Upgrade: h2c`（HTTP/2  prior-knowledge 协商）；Litestar/uvicorn 将带 Upgrade 头的 POST 按升级语义处理，返回 400 `Validation failed: 'data'`。
- **决策**：`Clients.agentWebClient` 显式构造 `JdkClientHttpConnector(HttpClient.Version.HTTP_1_1)`，禁用协议升级协商。
- **后果**：SSE 桥接恢复（端到端 0 失败）；代价是放弃 h2c 多路复用（内网单跳场景无实际收益）。
- **关联**：D-06；配套前端 D-05（graphql 改 POST）、D-07（SSE `data:` 帧兼容 + Vue 响应式整体替换）于 web-admin 0.1.5 修复。
