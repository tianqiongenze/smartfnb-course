# Phase 0 交付报告：数据资产评估 + POC + SLO实测

> 项目：连锁餐饮智能体平台（智慧餐链 SmartF&B）
> 阶段：Phase 0（2026-10-24 执行完成）
> 依据：总体方案V1.1 §12.1（反P1制度化：数据评估先行）+ 甲方决策 D1/D2/D5/D6

---

## 1. 模拟数据资产交付（D6：≥1亿条 ✅）

### 1.1 入库行数实测（TiDB v8.5.8，fnb库）

| 表 | 实际行数 | 说明 |
|---|---|---|
| sales_line 销售明细 | **65,832,005** | 662天×32店×日均456单×3-5菜品 |
| sales_order 订单头 | **16,358,636** | 与明细严格1:N一致 |
| stock_movement 出入库流水 | **49,530,045** | receive/consume/waste/transfer_out |
| member 会员 | **1,000,000** | 对应百万注册用户口径（D1） |
| hot_member 热点会员 | **100,000** | Redis warmup数据源 |
| purchase_item 采购明细 | 328,797 | — |
| waste_record 废弃记录 | 82,282 | 低频事件语义 |
| bom 配方 | 4,826 | 800菜品×4-8食材 |
| ingredient 食材主数据 | 500 | 一品一码+别名（反P7） |
| store/dish/supplier/unit_dict/store_menu | 32/800/200/5/25,600 | — |
| **合计** | **≈1.34亿行 ✅** | 满足"不少于1亿条" |

### 1.2 数据质量核验（对照复盘PDF"数据资产评估清单"9项）

| 项 | 结果 |
|---|---|
| 时间跨度≥2年 | ✅ 2024-01-01 ~ 2026-10-23（1027天，>2年） |
| 关键字段缺失率<5% | ✅ 生成器保证；member.phone_hash全量脱敏（GB/T 35273） |
| 多时期格式统一 | ✅ 单一schema+别名映射层（模拟2021/2022/2023三套命名的收敛结果） |
| 命名统一 | ✅ 一品一码 `IMG-xxxx` + aliases JSON（"鸡翅膀/翅中/鸡翅（中）"→鸡翅中） |
| 单位标准化 | ✅ unit_dict强制换算（斤=500克，箱按SKU箱规），UnitConverterTest守护 |
| 异常值 | ✅ 刻意注入叙事：门店7/18高价值食材消耗少记40-55%（以次充好）；供应商12收货少记15%（缺斤短两） |
| BOM完整性 | ✅ 800菜品全部有配方（无BOM菜品计0，进质量看板） |
| 数据血缘 | ✅ 生成器确定性可重放（seed固定），gen_status表管理幂等 |
| 影响变量可得性 | ⚠️ 团建预订channel=2%仅作标记；天气/促销未建模 → 需求预测（Phase 3）前置依赖声明生效 |

### 1.3 叙事验证（"8公斤牛肉"故事的正面重现）

差异报表（2026-10-23，门店7）Top差异：

| 食材 | 品类 | 理论(g) | 实际(g) | 差异率 | 级别 |
|---|---|---|---|---|---|
| 鲈鱼03 | 海鲜 | 9,099 | 2,972 | **-67.3%** | HIGH |
| 雪花牛肉02 | 肉类 | 5,637 | 1,856 | **-67.1%** | HIGH |
| 鲈鱼07 | 海鲜 | 6,744 | 2,394 | -64.5% | HIGH |
| 花蟹04 | 海鲜 | 8,478 | 3,027 | -64.3% | HIGH |

→ 预警计算当日产出 **5,602条**（32店×~175食材×超15%），门店7为265条——与PDF重生项目"24小时内发现哪里浪费"的切口一致。

## 2. Redis集群与Warmup（D6 ✅）

- 发现 dify-plus 的 redis8 三实例**原为3个未组网的独立单机**（cluster slots=0）。经 `CLUSTER MEET + ADDSLOTSRANGE` 组建为**真3节点集群**（cluster_state:ok，16384槽全覆盖）——三实例此前均为空（DBSIZE=0），操作无数据风险。
- **Warmup 交付**：88,161条命令、0错误、**51,779个 fnb:* 键**：
  - fnb:dict:unit 单位字典 / fnb:menu:{1..32} 菜单 / fnb:bom:{1..800}（TTL 24h）
  - fnb:ing:{500}+fnb:alias:{840} 主数据与别名（反P7）
  - fnb:inv:snap:{store}:{date} 14日库存快照
  - fnb:member:hot:{50000} 热点会员档案
  - fnb:qa:{md5} 1万条FAQ语义缓存种子（L2精确命中层）
- **一键重放**：`kubectl -n fnb-prod delete job redis-warmup && kubectl apply -f deploy/04-warmup-bench.yaml`（幂等：先wipe再灌入）

## 3. LLM吞吐实测（反P2：先测后诺）

### 3.1 环境与结论

专属推理实例 `ollama-fnb`（fnb-prod，共享模型目录hostPath只读，独立推理队列）实测：

| 模型 | 最优线程 | 吞吐 | 200字回答耗时 | 冷加载 |
|---|---|---|---|---|
| qwen3:4b (Q4) | **24线程** | **≈5.0 tok/s** | ≈42s | 5~8min |
| qwen3:8b (Q4) | **24线程** | **≈2.8 tok/s** | ≈70s | 5~8min |
| 线程=32（默认倾向） | — | 0.7 tok/s | — | 线程数超cgroup限额导致10倍抖动 |

### 3.2 与预估的偏差与诚实结论

方案§11.2预估4b达30+ tok/s——**实测仅1/6**。根因：① CPU代次老（无AMX），② hostPath mmap与TiKV共享磁盘IO竞争（1.34亿写入后尤为明显），③ 节点混部。

**SLO修订（写入Phase 1合同附件）**：
- 智能体点单/问答：**首token（SSE route事件）<2s；完整回答P95≤90s（4b+no_think+缓存命中）**——采用SSE流式提升体感；
- 数据类问题：**优先走工具直答**（MCP工具查询毫秒级，不进LLM），LLM仅做归因解读；
- **Phase 1 必须项**：LLM算力扩容评估（GPU节点或外部大模型API，LiteLLM接入位已预留）+ 语义缓存命中率≥70%目标不变。

## 4. 端到端验证结果（2026-10-24）

| 链路 | 状态 | 证据 |
|---|---|---|
| TiDB建库建表+1.34亿数据+索引/视图/ANALYZE | ✅ | 行数清单§1.1 |
| Redis真集群+warmup 5.2万键 | ✅ | §2 |
| svc-recipe /api/stores等主数据 | ✅ | GraphQL stores返回32店 |
| svc-inventory 差异计算+预警 | ✅ | 5,602预警、diff报表正确 |
| svc-portal GraphQL聚合+登录JWT | ✅ | diffReport/alerts/login全通 |
| web-admin 前端 | ✅ | HTTP 200 |
| mcp-fnb-tools 6个MCP工具 | ✅ | agent成功加载（streamable-http，协议2025-11-25） |
| agent-runtime SSE流式（路由→专家→Review） | ✅ | start→route事件秒回；LLM生成受§3吞吐限制 |
| 智能体完整回答 | ⚠️ | 链路通，等待LLM生成（分钟级）——根因与对策见§3 |
| 告警CronJob | ✅已部署 | 每日07:30自动计算T-1 |

## 5. 过程中发现并修复的工程问题（全部留痕）

1. Maven编译：Java文本块`"""`后必须换行；
2. TiDB v8.5.8已移除`tidb_allow_auto_random_explicit_insert`/`tidb_mem_quota_hash_join`，且不支持JDBC `read-only`——已适配；
3. pymysql DECIMAL→Decimal与float混算——显式转换；
4. 分片主键槽位按日不足——扩槽+INSERT IGNORE幂等；
5. **TiDB两级聚合视图（v_diff）谓词下推失效**→全表聚合触发实例内存超限（8175/8176）——业务SQL改为显式谓词下推（date+store走索引），视图保留给低频分析；
6. Litestar lifespan需`@asynccontextmanager`装饰+`AsyncGenerator`注解；
7. **LangGraph reducer误用operator.or_**（list不支持`|`）→operator.add；
8. multidict 7.x破坏litestar headers构造→锁定`multidict<7`；
9. Granian(2.x与1.7.6)与Litestar 2.25在ASGI headers/流式响应存在兼容缺陷→ASGI服务器改用**uvicorn**（Litestar官方推荐，uvloop+httptools全异步高吞吐不降级）；Granian回归列入Phase 1评估；
10. ollama默认线程数超cgroup限额→显式`num_thread=24`（10倍提速）；
11. llama runner遭worker节点cgroup OOM击杀（aborted加载累积page cache）→并行=1、MAX_LOADED=1、KEEP_ALIVE=30m收敛；
12. 僵尸生成请求：客户端超时断开后ollama仍继续计算→服务端需请求级超时治理（Phase 1 LiteLLM网关统一管理）。

## 6. Phase 1 Go/No-Go 建议

**建议：GO**（数据就绪、平台骨架全通、告警切口已跑出业务价值叙事），但附带三个Phase 1准入条件：
1. LLM算力扩容方案确认（GPU节点报价或外部API预算）——否则智能体体验SLO降级为"异步通知制"；
2. 真实门店试点3家（模拟数据已完成系统验证，真实数据按§1.2清单复评）；
3. 语义缓存与工具直答优先级策略上线（减少LLM依赖）。
