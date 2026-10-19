"""期刊指标模块：影响因子（JCR IF）与中科院分区（CAS 分区）查找。

用于论文搜索结果的影响因子筛选和中科院分区筛选。

数据说明：
- 影响因子为 JCR（Journal Citation Reports）参考值（约 2023 年版，每年会更新）。
- 中科院分区采用「中科院文献情报中心期刊分区表 · 升级版 · 大类」，
  取值为 "1区" / "2区" / "3区" / "4区"。
- 内置数据覆盖 PaperLens 内置期刊映射（JOURNAL_ISSN）中的主要期刊，
  并非全量 JCR/CAS 数据库。可通过用户自定义 JSON 文件补充或覆盖。

自定义扩展：
    将用户数据写入 `~/.paperlens/journal_metrics.json`，格式如下：

    {
      "0028-0836": {"impact_factor": 50.5, "cas_partition": "1区"},
      "Nature":    {"impact_factor": 50.5, "cas_partition": "1区"}
    }

    键可以是 ISSN（带或不带连字符）或期刊名（不区分大小写）。
    导入时该文件会合并进内置索引，同键时覆盖内置值。
"""

import json
import os
import re
import threading
from pathlib import Path

# ============================================================
# 内置期刊指标数据
# 每条： (规范期刊名, ISSN, 影响因子, 中科院分区, [别名列表])
# 影响因子为参考值，中科院分区为升级版大类。
# ============================================================
_JOURNAL_METRICS = [
    # ===== Nature 系列 =====
    ("Nature", "0028-0836", 50.5, "1区", ["nature"]),
    ("Nature Methods", "1546-1696", 36.1, "1区", ["nat methods", "nature methods"]),
    ("Nature Photonics", "1749-4885", 32.3, "1区", ["nat photonics", "nature photonics"]),
    ("Nature Cell Biology", "1465-7392", 17.3, "1区", ["nat cell biol", "nature cell biology"]),
    ("Nature Neuroscience", "1097-6256", 21.2, "1区", ["nat neurosci", "nature neuroscience"]),
    ("Nature Biotechnology", "1087-0156", 33.1, "1区", ["nat biotechnol", "nature biotechnology"]),
    ("Nature Communications", "2041-1723", 14.7, "1区", ["nat commun", "nature communications"]),
    ("Nature Chemistry", "1476-1122", 19.2, "1区", ["nat chem", "nature chemistry"]),
    ("Nature Physics", "1745-2473", 17.6, "1区", ["nat phys", "nature physics"]),
    ("Nature Materials", "1476-1121", 37.2, "1区", ["nat mater", "nature materials"]),
    ("Nature Medicine", "1078-8956", 58.7, "1区", ["nat med", "nature medicine"]),
    ("Nature Biomedical Engineering", "2157-846X", 26.8, "1区", ["nat biomed eng", "nature biomedical engineering"]),
    ("Nature Genetics", "1061-4036", 31.7, "1区", ["nat genet", "nature genetics"]),
    ("Nature Immunology", "1529-2908", 27.7, "1区", ["nat immunol", "nature immunology"]),
    ("Nature Structural & Molecular Biology", "1545-9993", 12.5, "1区", ["nat struct mol biol"]),
    ("Nature Reviews Molecular Cell Biology", "1471-0072", 81.3, "1区", ["nat rev mol cell biol"]),
    ("Nature Reviews Neuroscience", "1471-003X", 28.7, "1区", ["nat rev neurosci"]),
    ("Nature Reviews Genetics", "1471-0056", 39.1, "1区", ["nat rev genet"]),
    ("Nature Reviews Immunology", "1474-1733", 67.7, "1区", ["nat rev immunol"]),
    ("Nature Reviews Drug Discovery", "1474-1776", 122.7, "1区", ["nat rev drug discov"]),
    ("Nature Human Behaviour", "2522-5804", 21.4, "1区", ["nat hum behav"]),
    ("Nature Aging", "2662-1355", 17.0, "1区", ["nature aging"]),
    ("Nature Cancer", "2662-1347", 23.5, "1区", ["nature cancer"]),
    ("Nature Metabolism", "2522-5812", 18.9, "1区", ["nat metab", "nature metabolism"]),
    ("Nature Cardiovascular Research", "2522-1094", 9.4, "1区", ["nat cardiovasc res"]),
    ("Nature Chemical Biology", "1552-4450", 12.9, "1区", ["nat chem biol"]),
    ("Nature Ecology & Evolution", "2397-3374", 13.9, "1区", ["nat ecol evol"]),
    ("Nature Electronics", "2520-1131", 33.7, "1区", ["nat electron"]),
    ("Nature Energy", "2058-7546", 49.7, "1区", ["nat energy"]),
    ("Nature Nanotechnology", "1748-3387", 38.1, "1区", ["nat nanotechnol"]),
    ("Nature Protocols", "1754-2189", 13.1, "1区", ["nat protoc"]),
    ("Nature Reviews Clinical Oncology", "1759-4774", 81.1, "1区", ["nat rev clin oncol"]),
    ("Nature Reviews Chemistry", "2397-3358", 38.1, "1区", ["nat rev chem"]),
    ("Nature Reviews Physics", "2524-4914", 44.8, "1区", ["nat rev phys"]),
    ("Nature Reviews Materials", "2058-8437", 79.8, "1区", ["nat rev mater"]),
    ("Nature Reviews Methods Primers", "2662-8449", 50.1, "1区", ["nat rev methods primers"]),
    # ===== Science 系列 =====
    ("Science", "0036-8075", 44.7, "1区", ["science"]),
    ("Science Advances", "2375-2548", 11.7, "1区", ["sci adv", "science advances"]),
    ("Science Translational Medicine", "1946-6234", 15.8, "1区", ["sci transl med"]),
    ("Science Immunology", "2470-2986", 17.6, "1区", ["sci immunol"]),
    ("Science Robotics", "2470-9476", 26.1, "1区", ["sci robot"]),
    ("Science Signaling", "1945-0877", 6.7, "2区", ["sci signal"]),
    # ===== Cell 系列 =====
    ("Cell", "0092-8674", 45.5, "1区", ["cell"]),
    ("Cell Reports", "2211-1247", 7.5, "1区", ["cell rep", "cell reports"]),
    ("Cell Stem Cell", "1934-5909", 19.8, "1区", ["cell stem cell"]),
    ("Cell Metabolism", "1550-4131", 27.7, "1区", ["cell metab", "cell metabolism"]),
    ("Molecular Cell", "1097-2765", 14.5, "1区", ["mol cell", "molecular cell"]),
    ("Cancer Cell", "1535-6108", 48.8, "1区", ["cancer cell"]),
    ("Neuron", "0896-6273", 14.7, "1区", ["neuron"]),
    ("Immunity", "1074-7613", 25.5, "1区", ["immunity"]),
    ("Cell Host & Microbe", "1931-3128", 20.6, "1区", ["cell host microbe", "cell host & microbe"]),
    ("Cell Systems", "2405-4712", 9.0, "1区", ["cell syst", "cell systems"]),
    ("Cell Chemical Biology", "2451-9456", 6.6, "2区", ["cell chem biol", "cell chemical biology"]),
    ("Cell Reports Medicine", "2666-3791", 11.7, "1区", ["cell rep med"]),
    ("Cell Reports Physical Science", "2666-6836", 7.9, "2区", ["cell rep phys sci"]),
    ("Cell Genomics", "2666-979X", 11.1, "1区", ["cell genomics"]),
    ("iScience", "2589-0042", 4.6, "2区", ["iscience"]),
    # ===== 生物医学顶刊 =====
    ("The Lancet", "0140-6736", 98.4, "1区", ["lancet", "the lancet"]),
    ("New England Journal of Medicine", "0028-4793", 96.2, "1区", ["n engl j med", "new engl j med", "the new england journal of medicine"]),
    ("JAMA", "0098-7484", 63.1, "1区", ["jama", "journal of the american medical association"]),
    ("BMJ", "0959-8138", 93.6, "1区", ["bmj", "bmj-british medical journal"]),
    ("Annals of Internal Medicine", "0003-4819", 19.6, "1区", ["ann intern med", "annals of internal medicine"]),
    # ===== 化学 =====
    ("Journal of the American Chemical Society", "0002-7863", 14.4, "1区", ["j am chem soc", "jacs"]),
    ("Angewandte Chemie International Edition", "1433-7851", 16.1, "1区", ["angew chem int edit"]),
    ("Angewandte Chemie", "0044-8249", 16.1, "1区", ["angew chem"]),
    ("Chemical Reviews", "0009-2665", 62.1, "1区", ["chem rev"]),
    ("Chemical Society Reviews", "0306-0012", 40.4, "1区", ["chem soc rev"]),
    ("ACS Nano", "1936-0851", 15.8, "1区", ["acs nano"]),
    ("Nano Letters", "1530-6984", 9.6, "1区", ["nano lett", "nano letters"]),
    ("ACS Central Science", "2374-7943", 12.7, "1区", ["acs cent sci", "acs central science"]),
    ("Advanced Materials", "0935-9648", 27.4, "1区", ["adv mater", "advanced materials"]),
    ("Advanced Functional Materials", "1616-301X", 18.5, "1区", ["adv funct mater", "advanced functional materials"]),
    ("Advanced Energy Materials", "1614-6832", 24.4, "1区", ["adv energy mater", "advanced energy materials"]),
    ("Energy & Environmental Science", "1754-5692", 32.4, "1区", ["energy environ sci", "energy & environmental science"]),
    # ===== 生物学 =====
    ("Genes & Development", "0890-9369", 7.5, "1区", ["genes dev", "genes & development"]),
    ("Genome Research", "1088-9051", 6.2, "1区", ["genome res", "genome research"]),
    ("Genome Biology", "1474-760X", 10.1, "1区", ["genome biol", "genome biology"]),
    ("PLoS Biology", "1544-9173", 7.8, "1区", ["plos biol", "plos biology"]),
    ("eLife", "2050-084X", 6.4, "1区", ["elife"]),
    # ===== 医学 =====
    ("The Lancet Oncology", "1470-2045", 41.6, "1区", ["lancet oncol", "lancet oncology"]),
    ("The Lancet Neurology", "1474-4422", 46.5, "1区", ["lancet neurol", "lancet neurology"]),
    ("The Lancet Psychiatry", "2215-0366", 30.8, "1区", ["lancet psychiatry"]),
    ("Journal of Clinical Oncology", "0732-183X", 42.1, "1区", ["j clin oncol", "journal of clinical oncology"]),
    ("Journal of Clinical Investigation", "0021-9738", 13.3, "1区", ["j clin invest", "journal of clinical investigation"]),
    ("Journal of Experimental Medicine", "0022-1007", 12.6, "1区", ["j exp med", "journal of experimental medicine"]),
    ("Journal of Immunology", "0022-1767", 3.6, "2区", ["j immunol", "journal of immunology"]),
    # ===== 材料科学 =====
    ("Nano Today", "1748-0132", 13.2, "1区", ["nano today"]),
    ("Nanoscale", "2040-3364", 5.8, "2区", ["nanoscale"]),
    ("Small", "1613-6816", 13.0, "1区", ["small"]),
    ("Chemistry of Materials", "0897-4756", 7.2, "1区", ["chem mater", "chemistry of materials"]),
    ("ACS Applied Materials & Interfaces", "1944-8244", 8.3, "2区", ["acs appl mater interf", "acs applied materials & interfaces"]),
    ("Advanced Materials Interfaces", "2196-7350", 4.3, "3区", ["adv mater interfaces"]),
    # ===== 物理学 =====
    ("Physical Review Letters", "0031-9007", 8.1, "1区", ["phys rev lett", "physical review letters"]),
    ("Physical Review X", "2160-3308", 11.6, "1区", ["phys rev x", "physical review x"]),
    ("Reviews of Modern Physics", "0034-6861", 45.9, "1区", ["rev mod phys", "reviews of modern physics"]),
    ("Optica", "2334-2536", 8.4, "1区", ["optica"]),
    ("Optics Express", "1094-4087", 3.2, "2区", ["opt express", "optics express"]),
    ("Light: Science & Applications", "2047-7533", 20.6, "1区", ["light sci appl", "light: science & applications"]),
    # ===== 计算机科学 =====
    ("ACM Computing Surveys", "0360-0300", 16.6, "1区", ["acm comput surv", "acm computing surveys"]),
    ("IEEE Transactions on Pattern Analysis and Machine Intelligence", "0162-8828", 20.8, "1区", ["ieee trans pattern anal", "ieee transactions on pattern analysis and machine intelligence"]),
    ("Journal of Machine Learning Research", "1532-4435", 4.3, "2区", ["j mach learn res", "journal of machine learning research"]),
    # ===== 其他顶刊 =====
    ("Proceedings of the National Academy of Sciences", "0027-8424", 9.4, "1区", ["pnas", "proc natl acad sci usa", "proceedings of the national academy of sciences"]),
]


def _norm_issn(value: str) -> str:
    """规范化 ISSN：去掉连字符/空白并转大写，用于键匹配。"""
    if not value:
        return ""
    return re.sub(r"[^0-9A-Za-z]", "", str(value)).upper()


def _norm_name(value: str) -> str:
    """规范化期刊名：小写并去空白。"""
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _canonical_issn(value: str) -> str:
    """把 ISSN 还原成 OpenAlex 要求的带连字符形式（XXXX-XXXX）。

    注意：OpenAlex 的 issn 过滤**必须**带连字符，传 "21567085" 会返回 0 条
    （实测），因此查询前需要还原；缓存键仍用去连字符的 _norm_issn。
    """
    s = _norm_issn(value)
    return f"{s[:4]}-{s[4:]}" if len(s) == 8 else s


# 指标来源标记
SOURCE_LOCAL = "jcr"       # 内置表 / 用户自定义文件（官方 JCR 值）
SOURCE_OPENALEX = "openalex"  # OpenAlex 2yr_mean_citedness 估计值


# ============================================================
# 构建索引
# ============================================================
JOURNAL_METRICS_BY_ISSN = {}
JOURNAL_METRICS_BY_NAME = {}


def _build_indexes():
    """根据 _JOURNAL_METRICS 构建 ISSN 与名称索引。"""
    for name, issn, impact_factor, cas_partition, aliases in _JOURNAL_METRICS:
        entry = {
            "journal": name,
            "impact_factor": float(impact_factor),
            "cas_partition": cas_partition,
            "source": SOURCE_LOCAL,
        }
        if issn:
            key = _norm_issn(issn)
            if key:
                JOURNAL_METRICS_BY_ISSN[key] = entry
        for n in [name] + list(aliases or []):
            key = _norm_name(n)
            if key:
                JOURNAL_METRICS_BY_NAME[key] = entry


def _load_custom_metrics():
    """加载用户自定义指标文件 `~/.paperlens/journal_metrics.json`（若存在）。

    格式： { "<ISSN 或 期刊名>": {"impact_factor": float, "cas_partition": "1区"} }
    覆盖内置值（同键时）。
    """
    try:
        path = Path.home() / ".paperlens" / "journal_metrics.json"
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        for raw_key, raw_val in data.items():
            if not isinstance(raw_val, dict):
                continue
            if "impact_factor" not in raw_val and "cas_partition" not in raw_val:
                continue
            entry = {
                "journal": str(raw_val.get("journal", "") or raw_key),
                "impact_factor": float(raw_val.get("impact_factor", 0) or 0),
                "cas_partition": str(raw_val.get("cas_partition", "") or ""),
                "source": SOURCE_LOCAL,
            }
            issn_key = _norm_issn(raw_key)
            name_key = _norm_name(raw_key)
            # 若键形如 ISSN，写入 ISSN 索引；否则按名称写入名称索引
            if re.match(r"^\d{4}-?\d{3}[\dXx]$", str(raw_key).strip()):
                if issn_key:
                    JOURNAL_METRICS_BY_ISSN[issn_key] = entry
            else:
                if name_key:
                    JOURNAL_METRICS_BY_NAME[name_key] = entry
        print(f"[INFO] journal_metrics: 已加载自定义指标文件 ({len(data)} 条)")
    except Exception as e:
        print(f"[WARN] journal_metrics: 加载自定义指标失败: {e}")


_build_indexes()
_load_custom_metrics()


def lookup_metrics(issn: str = "", name: str = "") -> dict:
    """根据 ISSN 或期刊名查找期刊指标。

    Args:
        issn: 期刊 ISSN（可选）
        name: 期刊名（可选）

    Returns:
        dict: {"journal": str, "impact_factor": float, "cas_partition": str}
        未找到返回 None。
    """
    if issn:
        entry = JOURNAL_METRICS_BY_ISSN.get(_norm_issn(issn))
        if entry:
            return entry
    if name:
        entry = JOURNAL_METRICS_BY_NAME.get(_norm_name(name))
        if entry:
            return entry
    return None


def get_impact_factor(issn: str = "", name: str = "") -> float:
    """便捷方法：返回影响因子，未找到返回 0.0。"""
    entry = lookup_metrics(issn=issn, name=name)
    return entry["impact_factor"] if entry else 0.0


def get_cas_partition(issn: str = "", name: str = "") -> str:
    """便捷方法：返回中科院分区，未找到返回空字符串。"""
    entry = lookup_metrics(issn=issn, name=name)
    return entry["cas_partition"] if entry else ""


# ============================================================
# 在线兜底：OpenAlex 期刊影响力（2yr_mean_citedness）
# ============================================================
# 背景：内置表仅覆盖约 102 种期刊，远不足以支撑「影响因子筛选」。
# 启用 IF 过滤而只认内置表，等价于「只保留这 102 种期刊」，会让绝大多数
# 查询（尤其专业领域）返回空结果。
#
# OpenAlex 为每个期刊提供 summary_stats.2yr_mean_citedness（两年平均被引），
# 与 JIF 度量的是同一物理量，免费、无需 key、覆盖数万期刊。
# 但它**不是 JCR 官方影响因子**（量级通常偏低，例如 Nature 官方 50.5
# 而 OpenAlex 为 19.1），因此仅作为**估计值**兜底，并在结果中标记来源。

_OA_CACHE = {}          # norm_issn -> {"impact_factor": float}
_OA_MISSING = set()     # 查过但无结果的 ISSN，避免重复请求
_OA_LOCK = threading.Lock()
_OA_CACHE_PATH = Path.home() / ".paperlens" / "openalex_journal_cache.json"
_OA_ENDPOINT = "https://api.openalex.org/sources"
_OA_BATCH = 50          # 单次请求的 ISSN 数量上限
_OA_TIMEOUT = 4         # 秒；失败即跳过，不阻塞搜索


def _load_oa_cache():
    """加载持久化的 OpenAlex 期刊缓存。"""
    global _OA_CACHE
    try:
        if not _OA_CACHE_PATH.exists():
            return
        with open(_OA_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _OA_CACHE = {
                k: {"impact_factor": float(v.get("impact_factor", 0) or 0)}
                for k, v in data.items()
                if isinstance(v, dict)
            }
            print(f"[INFO] journal_metrics: 已加载 OpenAlex 期刊缓存 ({len(_OA_CACHE)} 条)")
    except Exception as e:
        print(f"[WARN] journal_metrics: 加载 OpenAlex 缓存失败: {e}")


def _save_oa_cache():
    """持久化 OpenAlex 期刊缓存（失败不影响主流程）。"""
    try:
        _OA_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_OA_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_OA_CACHE, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"[WARN] journal_metrics: 保存 OpenAlex 缓存失败: {e}")


def prefetch_openalex(issns, enabled: bool = True) -> int:
    """批量从 OpenAlex 拉取期刊 2yr_mean_citedness 并写入缓存。

    - 只请求「未缓存且未标记缺失」的 ISSN，按 ≤50 一批
    - 任何失败都静默跳过（网络问题不应影响搜索主流程）
    - 返回本次新增条数
    """
    if not enabled:
        return 0

    with _OA_LOCK:
        todo = [
            k
            for k in (_norm_issn(x) for x in (issns or []))
            if k and k not in _OA_CACHE and k not in _OA_MISSING
        ]
    todo = list(dict.fromkeys(todo))
    if not todo:
        return 0

    try:
        import requests  # 延迟导入：避免模块级强依赖
    except Exception:
        return 0

    added = 0
    for i in range(0, len(todo), _OA_BATCH):
        batch = todo[i : i + _OA_BATCH]
        try:
            r = requests.get(
                _OA_ENDPOINT,
                params={
                    "filter": "issn:"
                    + "|".join(_canonical_issn(k) for k in batch),
                    "per-page": len(batch),
                    "select": "issn,display_name,summary_stats",
                },
                timeout=_OA_TIMEOUT,
            )
            if r.status_code != 200:
                continue
            results = (r.json() or {}).get("results", []) or []
            hit = set()
            for item in results:
                val = (item.get("summary_stats") or {}).get("2yr_mean_citedness")
                if val is None:
                    continue
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    continue
                for issn_raw in item.get("issn") or []:
                    k = _norm_issn(issn_raw)
                    if k in batch:
                        hit.add(k)
                        with _OA_LOCK:
                            _OA_CACHE[k] = {"impact_factor": round(val, 3)}
                        added += 1
            with _OA_LOCK:
                for k in batch:
                    if k not in hit:
                        _OA_MISSING.add(k)
        except Exception as e:
            print(f"[WARN] journal_metrics: OpenAlex 查询失败（已跳过）: {e}")
            continue

    if added:
        _save_oa_cache()
        print(f"[INFO] journal_metrics: OpenAlex 新增期刊指标 {added} 条")
    return added


def get_openalex_metrics(issn: str = "") -> dict:
    """从缓存取 OpenAlex 估计指标；未命中返回 None。"""
    k = _norm_issn(issn)
    if not k:
        return None
    with _OA_LOCK:
        entry = _OA_CACHE.get(k)
    return dict(entry) if entry else None


def lookup_metrics_with_fallback(issn: str = "", name: str = "") -> dict:
    """先查内置/自定义表（官方 JCR 值），未命中用 OpenAlex 估计值兜底。

    Returns:
        dict: {"journal", "impact_factor", "cas_partition", "source"}
              source 为 SOURCE_LOCAL（官方值）或 SOURCE_OPENALEX（估计值）。
        两处都未命中返回 None。
    """
    entry = lookup_metrics(issn=issn, name=name)
    if entry:
        return {**entry, "source": entry.get("source", SOURCE_LOCAL)}

    oa = get_openalex_metrics(issn)
    if oa:
        return {
            "journal": name or "",
            "impact_factor": oa["impact_factor"],
            "cas_partition": "",  # 中科院分区无免费来源，仅内置表有
            "source": SOURCE_OPENALEX,
        }
    return None


_load_oa_cache()
