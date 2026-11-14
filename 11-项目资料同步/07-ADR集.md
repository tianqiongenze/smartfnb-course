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

## ADR-0017 GitOps 选型 Flux v2（V4对标新增，2026-11-14）

- **状态**：**已实施**（2026-11-15，GitOps 落地记录见下），常规回滚 = `git revert` → 重推 artifact → Flux 自动收敛。
- **落地记录（2026-11-15，air-gapped 实测）**：
  1. **CLI 与版本**：k8s 1.28 兼容上限 = **Flux v2.3.0**（v2.4.0 起官方兼容表要求 ≥1.29），装于 master `/usr/local/bin/flux`（GitHub release 下载，sha256 与官方 checksums.txt 核对一致）。
  2. **镜像面**：source/kustomize-controller 直连 ghcr.io 拉取，其余 4 控制器经 `ghcr.nju.edu.cn` 镜像源（daocloud `ghcr.m.daocloud.io` 白名单拒收 fluxcd、`docker.m.*` 不代理 ghcr，均实测不可用）；6 镜像全部改写为 `10.167.2.175:30500/flux/*` 推入本地 registry，安装清单为 `flux install --export --registry=10.167.2.175:30500/flux`（控制器 requests 沿用上游默认小值：source=50m/64Mi、其余=100m/64Mi，limits 1cpu/1Gi；显式插块会与上游自带 resources 构成重复 YAML key，已回退），入库 `smartfnb/gitops/flux-system-install.yaml`。
  3. **源模式**：采用 **OCIRepository**（`flux push artifact` 实测可推 plain-HTTP 本地 registry；源 `insecure: true`），artifact=仓库 `smartfnb/deploy` 目录，tag `main` 移动。
  4. **构建口径（smartfnb/deploy/kustomization.yaml）**：15 yaml − 14-otel（ADR-0012）；另按实测剥离 4 类：`otel-collector-config.yaml`（非 k8s 清单）、`secrets.enc.yaml`（SOPS 密文不入 flux）、两个 `<SET_AT_APPLY>` 占位 Secret 文档（防覆盖现网真实值）、**6 个一次性 Job 文档**（Job 带 `ttlSecondsAfterFinished`，TTL 删除后会被 flux 复活重跑；且实测对已完成的旧版 Job 做 SSA dry-run 触发 `spec.template: field is immutable` 拒绝——`daily-demand` 案例）。CronJob 模板可变，正常纳入。
  5. **结果**：Kustomization `fnb-apps`（targetNamespace=fnb-prod，wait+healthChecks，prune=false 首期）READY=True，`flux diff` = **0 漂移**；密钥仍按 deploy/README.md 方式b 手工注入，flux 不触碰 Secret。
  6. **agent-runtime 0.6.7→0.6.8** 经 Git 升 tag + 重推 artifact + reconcile 完成（managedFields 证实由 kustomize-controller Apply，非 kubectl 直改）。
- **背景**：docs/11 §二交付与运维域对标指出"15 yaml 手工 apply"为主要差距，且 docs/10 教训6 证明手工 apply/set image 正是镜像漂移与"一键恢复会回退"的根因。本集群为 air-gapped 两节点（镜像仅来自本地 registry 10.167.2.175:30500）。
- **决策**：采用 **Flux v2**（source-controller + kustomize-controller），Git 仓库为唯一真源，Flux Kustomization 指向 `smartfnb/deploy/`；不选 Argo CD。
- **理由**：① Flux 提供 air-gapped 官方安装路径（`flux install --export` 导出 manifests + `crane copy --all-tags` 搬运 controller 镜像到私有 registry，fluxcd.io/flux/installation/configuration/air-gapped），与本项目零外网约束直接匹配；② 无 UI 组件、controller 资源占用小，适配两节点混部小集群（对照 docs/10 对 BestEffort 饥饿的教训，控制面组件必须显式 requests）；③ Kustomize 原生贴合并清退前平铺清单（deploy/*.yaml），迁移成本低；④ 密钥链路用 SOPS+age（见 deploy/secrets.enc.yaml），与 docs/11 对标的 SOPS/ESO 分层一致。
- **Argo CD 不选理由**：UI/API Server 组件更重、air-gapped 需搬运的镜像面更长，本项目无多租户发布审批 UI 诉求。
- **revert 语义**：常规回滚 = `git revert <commit>` 后 Flux reconcile 自动收敛回上一状态；应急 = `flux suspend` + `kubectl rollout undo`，事后必须把手工状态回写仓库（docs/10 教训6），否则下轮 reconcile 冲突。铁律：**禁止 kubectl 直改集群造成漂移**，现网任何变更先落 Git。
- **revisit条件**：多集群/多环境或需要发布审批 UI 时重评 Argo CD；上游镜像拉取需 Harbor+Flux Mirror 供应链治理（docs/11 §四对标项）时一并纳入。

## ADR-0018 TiDB 备份选型：br 为主 + dumpling 为辅（V4对标新增，2026-11-14）

- **状态**：选型已定，**实施待恢复环境**（docs/11 §五 B 组"O4/O5 实施待环境"）。
- **背景**：fnb 库（1.5 亿行 / 12.2 GB）于 2026-10-30 在**零备份**状态下被 DROP，永久丢失（docs/10:17；docs/11 §一）。备份能力必须先于数据重建落地，杜绝重演。
- **决策**：
  1. **物理备份 = TiDB BR**：每日 02:00 full backup + **log stream 常开**（PITR，RPO≈分钟级），存储后端走 S3 兼容 MinIO（不落集群节点盘，共享 TiDB infra 不可写本地路径）；备份期间按 br 文档确认 `tikv_gc_life_time` 与 GC 冲突规避。
  2. **逻辑导出 = dumpling 为辅**：每周日 + 任意 schema/主数据变更前导出（schema、store/unit_dict/ingredient 等小表），跨版本可移植、可读，作为 br 二进制快照之外的兜底与审计副本（RPO=24h/周级，仅兜底不作为主恢复路径）。
- **调度**：K8S CronJob（fnb-prod 或独立备份命名空间）执行 `tiup br` 容器任务；dumpling 变更前手动 + 周度 CronJob。
- **恢复演练**：数据重建后每月一次 `br restore` 到临时库 `fnb_verify` 验证可用性（不触碰生产路径），演练记录入 docs。
- **对标依据**：TiDB 官方 br log+full PITR / MinIO(S3) 路径（docs.pingcap.com/tidb/stable/br-use-overview，docs/11 §四）。
- **局限声明**：本集群共享 TiDB 的 MinIO 是否在位未核（清退终态无集群侧操作），实施时若缺 MinIO 需先落对象存储再开备份；br/tidb 版本矩阵以恢复时集群 TiDB v8.5.8 为准验证。
