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
