"""CrossRef 论文元数据缓存（按 DOI）。

存在的原因：搜索后的「全局 DOI 补全」要为每篇元数据不完整的论文查一次
CrossRef（实测单次搜索可达 150+ 篇、20 秒以上），而**同一篇论文的元数据
在多次搜索间高度重复**。缓存后二次搜索几乎零开销。

这是纯性能优化，**不改变任何检索结果**：
  - 缓存内容与实时查询返回的 message 完全一致；
  - DOI 唯一对应一篇论文，不存在错配可能；
  - 30 天 TTL：CrossRef 的题名/作者/期刊等静态字段极少变动。
"""
import json
import threading
import time
from pathlib import Path

_TTL = 30 * 24 * 3600                      # 30 天
_PATH = Path.home() / ".paperlens" / "crossref_work_cache.json"
_MAX_ENTRIES = 20000                       # 超限后淘汰最旧的

_lock = threading.Lock()                   # 补全是多线程并发调用的
_cache: dict = {}
_loaded = False


def _load():
    global _cache, _loaded
    if _loaded:
        return
    _loaded = True
    if _PATH.exists():
        try:
            data = json.loads(_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _cache = data
        except Exception:
            _cache = {}


def get(doi: str):
    """命中且未过期返回 CrossRef message（不含内部 _ts 字段），否则 None。"""
    if not doi:
        return None
    with _lock:
        _load()
        entry = _cache.get(doi.strip().lower())
        if not entry:
            return None
        if time.time() - entry.get("_ts", 0) > _TTL:
            return None
        return {k: v for k, v in entry.items() if k != "_ts"}


def put(doi: str, message: dict):
    """仅缓存成功响应（message 非空）。"""
    if not doi or not message:
        return
    with _lock:
        _load()
        _cache[doi.strip().lower()] = {**message, "_ts": time.time()}


def flush():
    """由调用方在补全结束后统一落盘，避免多线程频繁写文件。"""
    with _lock:
        _load()
        if not _cache:
            return
        data = _cache
        if len(data) > _MAX_ENTRIES:
            items = sorted(data.items(), key=lambda kv: kv[1].get("_ts", 0))
            data = dict(items[-_MAX_ENTRIES:])
        try:
            _PATH.parent.mkdir(parents=True, exist_ok=True)
            _PATH.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass


def stats():
    with _lock:
        _load()
        return len(_cache)
