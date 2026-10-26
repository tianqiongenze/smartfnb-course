"""R3 语义缓存(Milvus) — ADR-0013: 嵌入实现切换
- 默认: 字符3-gram哈希嵌入(256维, L2归一化), <1ms、确定性; 近义改写(怎么/如何、语序)可命中
- 可选: EMBED_IMPL=model 时用 qwen3-embedding(本集群CPU上慢, 仅空闲时段批量任务用)
阈值(基于验证集标定): HIT>=0.93, REF>=0.80
"""
from __future__ import annotations

import json
import math
import os
import urllib.request
from collections import Counter

EMBED_IMPL = os.getenv("EMBED_IMPL", "hash")
DIM = 256
HIT_THRESHOLD = float(os.getenv("SEM_HIT", "0.93"))
REF_THRESHOLD = float(os.getenv("SEM_REF", "0.80"))

EMBED_BASE = os.getenv("EMBED_BASE", "http://fnb-ollama.fnb-prod.svc.cluster.local:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "qwen3-embedding:0.6b")
MILVUS_HOST = os.getenv("MILVUS_HOST", "milvus.infra.svc.cluster.local")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", "19530"))
COLLECTION = "fnb_qa_hash" if EMBED_IMPL == "hash" else "fnb_qa_vec"

_client = None

import zlib

def _hash_embed(text: str) -> list[float]:
    """字符3-gram → 256桶计数 → L2归一化。
    关键: 必须用稳定哈希(zlib.crc32), Python内建hash()每进程随机化会让向量跨进程不一致。"""
    t = text.lower().strip()
    grams = Counter(t[i:i + 3] for i in range(max(len(t) - 2, 1)))
    v = [0.0] * DIM
    for g, c in grams.items():
        v[zlib.crc32(g.encode()) % DIM] += c
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]

def _model_embed(text: str, timeout: float = 60.0) -> list[float] | None:
    try:
        body = json.dumps({"model": EMBED_MODEL, "prompt": text[:500]}).encode()
        req = urllib.request.Request(EMBED_BASE + "/api/embeddings", body,
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()).get("embedding")
    except Exception:
        return None

def embed(text: str, timeout: float = 60.0) -> list[float] | None:
    if EMBED_IMPL == "hash":
        return _hash_embed(text)
    return _model_embed(text, timeout)

def _milvus():
    global _client
    if _client is None:
        from pymilvus import MilvusClient
        _client = MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")
        if not _client.has_collection(COLLECTION):
            _client.create_collection(COLLECTION, dimension=DIM if EMBED_IMPL == "hash" else 1024,
                                      metric_type="COSINE", auto_id=True)
    return _client

def ensure_collection():
    _milvus()

def search_similar(question: str, budget_s: float = 2.0) -> dict | None:
    """返回 {answer, score, mode: hit|ref} 或 None。hash实现恒<50ms。"""
    vec = embed(question, timeout=budget_s)
    if not vec:
        return None
    try:
        res = _milvus().search(COLLECTION, data=[vec], limit=1,
                               output_fields=["q", "a"])
        if not res or not res[0]:
            return None
        hit = res[0][0]
        score = float(hit.get("distance", 0))
        ans = (hit.get("entity") or {}).get("a", "")
        if score >= HIT_THRESHOLD:
            return {"answer": ans, "score": round(score, 3), "mode": "hit"}
        if score >= REF_THRESHOLD:
            return {"answer": ans, "score": round(score, 3), "mode": "ref"}
        return None
    except Exception:
        return None

def add_pair(question: str, answer: str) -> None:
    """回写学习(失败静默)"""
    vec = embed(question)
    if not vec:
        return
    try:
        _milvus().insert(COLLECTION, [{"vector": vec, "q": question[:200], "a": answer[:800]}])
    except Exception:
        pass

def add_pair_async(question: str, answer: str) -> None:
    import threading
    threading.Thread(target=add_pair, args=(question, answer),
                     daemon=True).start()
