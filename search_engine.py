"""检索引擎 - PubMed + OpenAlex 聚合检索（增强版）

支持 PubMed 字段标签语法：
  keyword[ti]   - 标题搜索
  keyword[tiab] - 标题+摘要搜索
  keyword[au]   - 作者搜索
  keyword[ta]   - 期刊名搜索
  keyword[mh]   - MeSH 主题词
  keyword[tw]   - 自由词（Title/Abstract/Keywords）

布尔运算：AND / OR / NOT
年份过滤：2020:2025[pdat]

示例：
  super-resolution microscopy[ti]
  Nature Methods[ta] AND single-molecule[tiab]
  (expansion microscopy[ti] OR light-sheet[ti]) AND 2023:2025[pdat]
"""

import re
import sys
import math
import time
import json
import hashlib
import threading
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
    TimeoutError as FuturesTimeoutError,
)
import requests
from access_proxy import EZproxyRewriter
from dedup import deduplicate_papers


def _contains_chinese(text: str) -> bool:
    """检测文本是否包含中文字符"""
    if not text:
        return False
    # CJK Unified Ideographs 范围
    return bool(re.search(r"[一-鿿]", text))


def _extract_chinese_keywords(text: str) -> set:
    """从中文文本中提取关键词（简单空格分词）"""
    if not text:
        return set()
    # 中文按空格分词，过滤短词
    words = set()
    for w in re.split(r"\s+", text.strip()):
        w = w.strip()
        if len(w) >= 2:  # 中文词至少2个字
            words.add(w)
    return words


# 常用中文学术术语翻译字典（离线翻译，无需API）
# 覆盖：材料科学、化学、生物医学、物理天文、工程技术、环境地球科学、社会科学
_ZH_EN_DICT = {
    # ========== 材料科学 ==========
    "二维": "2D",
    "富勒烯": "fullerene",
    "电催化": "electrocatalysis",
    "石墨烯": "graphene",
    "纳米": "nano",
    "纳米材料": "nanomaterials",
    "催化剂": "catalyst",
    "催化": "catalysis",
    "光催化": "photocatalysis",
    "电化学": "electrochemistry",
    "电池": "battery",
    "锂离子": "lithium-ion",
    "太阳能电池": "solar cell",
    "钙钛矿": "perovskite",
    "纳米粒子": "nanoparticles",
    "纳米线": "nanowire",
    "纳米管": "nanotube",
    "碳纳米管": "carbon nanotube",
    "量子点": "quantum dot",
    "薄膜": "thin film",
    "涂层": "coating",
    "合金": "alloy",
    "复合材料": "composite",
    "陶瓷": "ceramic",
    "聚合物": "polymer",
    "水凝胶": "hydrogel",
    "生物材料": "biomaterial",
    # 材料科学补充
    "纳米片": "nanosheet",
    "纳米棒": "nanorod",
    "纳米花": "nanoflower",
    "纳米球": "nanosphere",
    "纳米晶": "nanocrystal",
    "纳米纤维": "nanofiber",
    "量子阱": "quantum well",
    "量子线": "quantum wire",
    "MXene": "MXene",
    "黑磷": "black phosphorus",
    "过渡金属硫化物": "transition metal dichalcogenide",
    "二硫化钼": "molybdenum disulfide",
    "二硫化钨": "tungsten disulfide",
    "氮化硼": "boron nitride",
    "氮化镓": "gallium nitride",
    "碳化硅": "silicon carbide",
    "碳化硼": "boron carbide",
    "氧化锌": "zinc oxide",
    "氧化钛": "titanium dioxide",
    "氧化铁": "iron oxide",
    "氧化铝": "alumina",
    "氧化铈": "ceria",
    "氮化硅": "silicon nitride",
    "氮化铝": "aluminum nitride",
    "钛合金": "titanium alloy",
    "铝合金": "aluminum alloy",
    "镁合金": "magnesium alloy",
    "镍基合金": "nickel-based alloy",
    "高温合金": "superalloy",
    "形状记忆合金": "shape memory alloy",
    "非晶合金": "amorphous alloy",
    "高熵合金": "high-entropy alloy",
    "碳纤维": "carbon fiber",
    "玻璃纤维": "glass fiber",
    "芳纶": "aramid fiber",
    "碳化硅纤维": "silicon carbide fiber",
    "纤维增强": "fiber reinforced",
    "层板": "laminate",
    "压电材料": "piezoelectric material",
    "热电材料": "thermoelectric material",
    "铁电材料": "ferroelectric material",
    "磁性材料": "magnetic material",
    "超导材料": "superconducting material",
    "发光材料": "luminescent material",
    "光电材料": "optoelectronic material",
    "储能材料": "energy storage material",
    "阳极氧化": "anodizing",
    "电镀": "electroplating",
    "化学气相沉积": "chemical vapor deposition",
    "物理气相沉积": "physical vapor deposition",
    "原子层沉积": "atomic layer deposition",
    "溅射": "sputtering",
    "分子束外延": "molecular beam epitaxy",
    "溶胶凝胶": "sol-gel",
    "水热合成": "hydrothermal synthesis",
    "溶剂热": "solvothermal",
    "共沉淀": "co-precipitation",
    "静电纺丝": "electrospinning",
    "3D打印": "3D printing",
    "X射线衍射": "X-ray diffraction",
    "扫描电镜": "scanning electron microscope",
    "透射电镜": "transmission electron microscope",
    "原子力显微镜": "atomic force microscope",
    "X射线光电子能谱": "X-ray photoelectron spectroscopy",
    "拉曼光谱": "Raman spectroscopy",
    "红外光谱": "infrared spectroscopy",
    "热重分析": "thermogravimetric analysis",
    "差示扫描量热法": "differential scanning calorimetry",
    "比表面积": "specific surface area",
    "孔隙率": "porosity",
    "吸附": "adsorption",
    "脱附": "desorption",
    "接触角": "contact angle",
    "表面能": "surface energy",
    "硬度": "hardness",
    "韧性": "toughness",
    "强度": "strength",
    "延展性": "ductility",
    "弹性模量": "elastic modulus",
    "疲劳": "fatigue",
    "断裂": "fracture",
    "蠕变": "creep",
    "腐蚀": "corrosion",
    "抗氧化": "antioxidant",
    "润滑": "lubrication",
    "摩擦": "friction",
    "磨损": "wear",
    # ========== 化学 ==========
    "有机": "organic",
    "无机": "inorganic",
    "分析化学": "analytical chemistry",
    "合成": "synthesis",
    "反应": "reaction",
    "分子": "molecule",
    "配位": "coordination",
    "金属有机框架": "metal-organic framework",
    "MOF": "MOF",
    "共价有机框架": "covalent organic framework",
    "COF": "COF",
    # 有机化学
    "官能团": "functional group",
    "反应机理": "reaction mechanism",
    "加成反应": "addition reaction",
    "取代反应": "substitution reaction",
    "消除反应": "elimination reaction",
    "重排反应": "rearrangement reaction",
    "缩合反应": "condensation reaction",
    "氧化反应": "oxidation reaction",
    "还原反应": "reduction reaction",
    "偶联反应": "coupling reaction",
    "手性": "chirality",
    "立体化学": "stereochemistry",
    "对映体": "enantiomer",
    "非对映体": "diastereomer",
    "共轭": "conjugation",
    "芳香性": "aromaticity",
    "杂环": "heterocycle",
    "酰胺": "amide",
    "酯": "ester",
    "醚": "ether",
    "醛": "aldehyde",
    "酮": "ketone",
    "羧酸": "carboxylic acid",
    "胺": "amine",
    "醇": "alcohol",
    "腈": "nitrile",
    "硝基": "nitro group",
    "磺酸基": "sulfonic acid group",
    # 无机化学
    "配位化合物": "coordination compound",
    "配体": "ligand",
    "中心原子": "central atom",
    "配位数": "coordination number",
    "八面体": "octahedral",
    "四面体": "tetrahedral",
    "金属有机化学": "organometallic chemistry",
    "簇合物": "cluster compound",
    "氧化态": "oxidation state",
    "晶体场理论": "crystal field theory",
    "配位场理论": "ligand field theory",
    # 分析化学
    "色谱": "chromatography",
    "高效液相色谱": "high-performance liquid chromatography",
    "气相色谱": "gas chromatography",
    "核磁共振": "nuclear magnetic resonance",
    "紫外可见光谱": "ultraviolet-visible spectroscopy",
    "荧光光谱": "fluorescence spectroscopy",
    "伏安法": "voltammetry",
    "循环伏安法": "cyclic voltammetry",
    # 物理化学
    "化学平衡": "chemical equilibrium",
    "反应速率": "reaction rate",
    "活化能": "activation energy",
    "过渡态": "transition state",
    "反应坐标": "reaction coordinate",
    "表面化学": "surface chemistry",
    "多相催化": "heterogeneous catalysis",
    "均相催化": "homogeneous catalysis",
    "吉布斯自由能": "Gibbs free energy",
    "化学势": "chemical potential",
    "相变": "phase transition",
    "胶体": "colloid",
    "界面": "interface",
    "表面张力": "surface tension",
    # 高分子化学
    "聚合反应": "polymerization",
    "加聚反应": "addition polymerization",
    "缩聚反应": "condensation polymerization",
    "共聚物": "copolymer",
    "嵌段共聚物": "block copolymer",
    "交联": "crosslinking",
    "引发剂": "initiator",
    "单体": "monomer",
    "低聚物": "oligomer",
    "玻璃化转变温度": "glass transition temperature",
    "结晶度": "crystallinity",
    "热塑性": "thermoplastic",
    "热固性": "thermosetting",
    "弹性体": "elastomer",
    # 药物化学
    "药效团": "pharmacophore",
    "构效关系": "structure-activity relationship",
    "药代动力学": "pharmacokinetics",
    "药效学": "pharmacodynamics",
    "生物利用度": "bioavailability",
    "半衰期": "half-life",
    "血脑屏障": "blood-brain barrier",
    "受体": "receptor",
    "酶抑制剂": "enzyme inhibitor",
    "药物设计": "drug design",
    "先导化合物": "lead compound",
    "药物筛选": "drug screening",
    "细胞毒性": "cytotoxicity",
    "抗菌活性": "antimicrobial activity",
    "抗肿瘤活性": "antitumor activity",
    # 环境化学
    "环境污染物": "environmental pollutant",
    "持久性有机污染物": "persistent organic pollutant",
    "多环芳烃": "polycyclic aromatic hydrocarbons",
    "多氯联苯": "polychlorinated biphenyls",
    "内分泌干扰物": "endocrine disruptor",
    "环境修复": "environmental remediation",
    "生物降解": "biodegradation",
    "光降解": "photodegradation",
    "污水处理": "wastewater treatment",
    "微塑料": "microplastic",
    # 生物化学
    "氨基酸": "amino acid",
    "核苷酸": "nucleotide",
    "蛋白质折叠": "protein folding",
    "酶催化": "enzymatic catalysis",
    "辅酶": "coenzyme",
    "底物": "substrate",
    "代谢途径": "metabolic pathway",
    "信号转导": "signal transduction",
    "转录因子": "transcription factor",
    "表观遗传": "epigenetics",
    "基因表达": "gene expression",
    "细胞凋亡": "apoptosis",
    "细胞自噬": "autophagy",
    # 计算化学
    "密度泛函理论": "density functional theory",
    "分子动力学": "molecular dynamics",
    "蒙特卡洛模拟": "Monte Carlo simulation",
    "从头算": "ab initio",
    "基组": "basis set",
    "几何优化": "geometry optimization",
    "势能面": "potential energy surface",
    "分子轨道": "molecular orbital",
    "前线轨道理论": "frontier molecular orbital theory",
    "偶极矩": "dipole moment",
    "极化率": "polarizability",
    "溶剂化模型": "solvation model",
    "构象": "conformation",
    "活性位点": "active site",
    # ========== 生物医学 ==========
    "基因": "gene",
    "蛋白质": "protein",
    "细胞": "cell",
    "肿瘤": "tumor",
    "癌症": "cancer",
    "免疫": "immunity",
    "疫苗": "vaccine",
    "抗体": "antibody",
    "基因编辑": "gene editing",
    "CRISPR": "CRISPR",
    "干细胞": "stem cell",
    "基因组": "genome",
    "蛋白质组": "proteomics",
    "代谢组": "metabolomics",
    "生物信息学": "bioinformatics",
    # 分子生物学
    "转录": "transcription",
    "翻译": "translation",
    "信使RNA": "messenger RNA",
    "核糖体RNA": "ribosomal RNA",
    "转运RNA": "transfer RNA",
    "DNA甲基化": "DNA methylation",
    "组蛋白": "histone",
    "染色质": "chromatin",
    "启动子": "promoter",
    "增强子": "enhancer",
    "外显子": "exon",
    "内含子": "intron",
    "剪接": "splicing",
    "翻译后修饰": "post-translational modification",
    "DNA复制": "DNA replication",
    "RNA干扰": "RNA interference",
    "小干扰RNA": "small interfering RNA",
    "微小RNA": "microRNA",
    "长链非编码RNA": "long non-coding RNA",
    "核酸酶": "nuclease",
    "聚合酶": "polymerase",
    "连接酶": "ligase",
    "限制性内切酶": "restriction endonuclease",
    # 细胞生物学
    "线粒体": "mitochondria",
    "内质网": "endoplasmic reticulum",
    "高尔基体": "Golgi apparatus",
    "溶酶体": "lysosome",
    "核糖体": "ribosome",
    "细胞膜": "cell membrane",
    "细胞核": "nucleus",
    "细胞周期": "cell cycle",
    "细胞分裂": "cell division",
    "有丝分裂": "mitosis",
    "减数分裂": "meiosis",
    "细胞迁移": "cell migration",
    "细胞分化": "cell differentiation",
    "细胞增殖": "cell proliferation",
    "细胞粘附": "cell adhesion",
    "细胞骨架": "cytoskeleton",
    "微管": "microtubule",
    "微丝": "microfilament",
    "中间丝": "intermediate filament",
    "中心体": "centrosome",
    "内吞": "endocytosis",
    "外排": "exocytosis",
    "细胞外基质": "extracellular matrix",
    # 免疫学
    "T细胞": "T cell",
    "B细胞": "B cell",
    "自然杀伤细胞": "natural killer cell",
    "巨噬细胞": "macrophage",
    "树突状细胞": "dendritic cell",
    "中性粒细胞": "neutrophil",
    "淋巴细胞": "lymphocyte",
    "细胞因子": "cytokine",
    "干扰素": "interferon",
    "白细胞介素": "interleukin",
    "肿瘤坏死因子": "tumor necrosis factor",
    "主要组织相容性复合体": "major histocompatibility complex",
    "免疫检查点": "immune checkpoint",
    "炎症": "inflammation",
    "补体系统": "complement system",
    "自身免疫": "autoimmunity",
    "免疫缺陷": "immunodeficiency",
    "过敏反应": "hypersensitivity",
    "抗原": "antigen",
    "细胞毒性": "cytotoxicity",
    "吞噬作用": "phagocytosis",
    "适应性免疫": "adaptive immunity",
    "先天性免疫": "innate immunity",
    # 神经科学
    "神经元": "neuron",
    "突触": "synapse",
    "神经递质": "neurotransmitter",
    "多巴胺": "dopamine",
    "血清素": "serotonin",
    "乙酰胆碱": "acetylcholine",
    "谷氨酸": "glutamate",
    "神经胶质细胞": "glial cell",
    "星形胶质细胞": "astrocyte",
    "少突胶质细胞": "oligodendrocyte",
    "小胶质细胞": "microglia",
    "髓鞘": "myelin",
    "轴突": "axon",
    "树突": "dendrite",
    "神经可塑性": "neuroplasticity",
    "海马体": "hippocampus",
    "大脑皮层": "cerebral cortex",
    "下丘脑": "hypothalamus",
    "垂体": "pituitary gland",
    "脑干": "brainstem",
    "神经退行性疾病": "neurodegenerative disease",
    "帕金森病": "Parkinson's disease",
    "阿尔茨海默病": "Alzheimer's disease",
    "突触可塑性": "synaptic plasticity",
    "神经发生": "neurogenesis",
    # 肿瘤学
    "转移": "metastasis",
    "原发性肿瘤": "primary tumor",
    "良性肿瘤": "benign tumor",
    "恶性肿瘤": "malignant tumor",
    "腺癌": "adenocarcinoma",
    "鳞状细胞癌": "squamous cell carcinoma",
    "淋巴瘤": "lymphoma",
    "白血病": "leukemia",
    "黑色素瘤": "melanoma",
    "胶质瘤": "glioma",
    "乳腺癌": "breast cancer",
    "肺癌": "lung cancer",
    "肝癌": "liver cancer",
    "胃癌": "gastric cancer",
    "结直肠癌": "colorectal cancer",
    "前列腺癌": "prostate cancer",
    "卵巢癌": "ovarian cancer",
    "胰腺癌": "pancreatic cancer",
    "化疗": "chemotherapy",
    "放疗": "radiation therapy",
    "靶向治疗": "targeted therapy",
    "免疫治疗": "immunotherapy",
    "激素治疗": "hormonal therapy",
    "生物标志物": "biomarker",
    "肿瘤微环境": "tumor microenvironment",
    "细胞周期阻滞": "cell cycle arrest",
    "耐药性": "drug resistance",
    "血管生成": "angiogenesis",
    "上皮间质转化": "epithelial-mesenchymal transition",
    # 心血管医学
    "动脉粥样硬化": "atherosclerosis",
    "心肌梗死": "myocardial infarction",
    "心力衰竭": "heart failure",
    "高血压": "hypertension",
    "心律失常": "arrhythmia",
    "冠心病": "coronary artery disease",
    "血栓": "thrombosis",
    "栓塞": "embolism",
    "心肌病": "cardiomyopathy",
    # 微生物学
    "细菌": "bacteria",
    "病毒": "virus",
    "真菌": "fungus",
    "微生物组": "microbiome",
    "抗生素": "antibiotic",
    "抗病毒": "antiviral",
    "感染": "infection",
    "脓毒症": "sepsis",
    "肺炎": "pneumonia",
    "结核病": "tuberculosis",
    "疟疾": "malaria",
    "流感": "influenza",
    "冠状病毒": "coronavirus",
    "肠道菌群": "gut flora",
    "抗微生物耐药": "antimicrobial resistance",
    # 药理学
    "药效动力学": "pharmacodynamics",
    "药物靶点": "drug target",
    "受体激动剂": "receptor agonist",
    "受体拮抗剂": "receptor antagonist",
    "抑制剂": "inhibitor",
    "激动剂": "agonist",
    "拮抗剂": "antagonist",
    "不良反应": "adverse reaction",
    "药物相互作用": "drug interaction",
    "剂量": "dosage",
    "药物代谢": "drug metabolism",
    "药物递送": "drug delivery",
    "纳米药物": "nanomedicine",
    "缓释": "sustained release",
    "靶向递送": "targeted delivery",
    # 中医药学
    "中药": "traditional Chinese medicine",
    "中医": "traditional Chinese medicine",
    "中草药": "Chinese herbal medicine",
    "草药": "herbal medicine",
    "本草": "materia medica",
    "方剂": "formula",
    "复方": "compound formula",
    "单味药": "single herb",
    "针灸": "acupuncture",
    "艾灸": "moxibustion",
    "推拿": "tuina",
    "拔罐": "cupping",
    "刮痧": "guasha",
    "气功": "qigong",
    "中药方剂": "Chinese medicine formula",
    "经方": "classical formula",
    "验方": "empirical formula",
    "单体": "compound",
    "有效成分": "active ingredient",
    "活性成分": "bioactive compound",
    "提取物": "extract",
    "总黄酮": "total flavonoids",
    "总皂苷": "total saponins",
    "总生物碱": "total alkaloids",
    "多糖": "polysaccharide",
    "挥发油": "essential oil",
    "萜类": "terpenoid",
    "黄酮": "flavonoid",
    "皂苷": "saponin",
    "生物碱": "alkaloid",
    "中药药理": "Chinese medicine pharmacology",
    "药性": "drug property",
    "四气五味": "four properties and five tastes",
    "归经": "meridian tropism",
    "升降浮沉": "ascending descending floating sinking",
    "配伍": "compatibility",
    "君臣佐使": "monarch minister assistant guide",
    "十八反": "eighteen incompatibilities",
    "十九畏": "nineteen mutual fears",
    "炮制": "processing",
    "中药炮制": "Chinese medicine processing",
    "辨证论治": "syndrome differentiation and treatment",
    "证候": "syndrome",
    "治法": "treatment method",
    "清热解毒": "clearing heat and detoxifying",
    "活血化瘀": "activating blood and resolving stasis",
    "补气": "supplementing qi",
    "补血": "nourishing blood",
    "滋阴": "nourishing yin",
    "温阳": "warming yang",
    "健脾": "strengthening spleen",
    "疏肝": "soothing liver",
    "益肾": "benefiting kidney",
    "祛风": "dispersing wind",
    "除湿": "eliminating dampness",
    "化痰": "resolving phlegm",
    "六经辨证": "six meridian syndrome differentiation",
    "卫气营血": "wei qi ying blood",
    "三焦辨证": "triple burner syndrome differentiation",
    "藏象": "organ manifestation",
    "经络": "meridian",
    "穴位": "acupoint",
    "经穴": "meridian point",
    "中药现代化": "Chinese medicine modernization",
    "网络药理学": "network pharmacology",
    "中药代谢组学": "Chinese medicine metabolomics",
    "中药质量控制": "Chinese medicine quality control",
    "中药指纹图谱": "Chinese medicine fingerprint",
    "中药血清药物化学": "Chinese medicine serum pharmacochemistry",
    # 临床医学
    "诊断": "diagnosis",
    "预后": "prognosis",
    "临床试验": "clinical trial",
    "随机对照试验": "randomized controlled trial",
    "队列研究": "cohort study",
    "病例对照研究": "case-control study",
    "横断面研究": "cross-sectional study",
    "荟萃分析": "meta-analysis",
    "系统评价": "systematic review",
    "循证医学": "evidence-based medicine",
    "个体化医疗": "precision medicine",
    "基因检测": "genetic testing",
    "核磁共振成像": "magnetic resonance imaging",
    "计算机断层扫描": "computed tomography",
    "超声": "ultrasound",
    "病理": "pathology",
    "活检": "biopsy",
    "手术": "surgery",
    "康复": "rehabilitation",
    # 生物信息学
    "基因组学": "genomics",
    "转录组学": "transcriptomics",
    "单细胞测序": "single-cell sequencing",
    "高通量测序": "high-throughput sequencing",
    "下一代测序": "next-generation sequencing",
    "RNA测序": "RNA sequencing",
    "基因本体": "gene ontology",
    "通路分析": "pathway analysis",
    "分子对接": "molecular docking",
    "结构预测": "structure prediction",
    "同源建模": "homology modeling",
    "序列比对": "sequence alignment",
    "系统发育": "phylogenetics",
    "进化树": "phylogenetic tree",
    # ========== 物理学与天文学 ==========
    "超导": "superconductivity",
    "量子": "quantum",
    "光学": "optics",
    "激光": "laser",
    "光谱": "spectroscopy",
    "磁性": "magnetism",
    "半导体": "semiconductor",
    "拓扑": "topological",
    # 凝聚态物理
    "拓扑绝缘体": "topological insulator",
    "量子霍尔效应": "quantum Hall effect",
    "自旋电子学": "spintronics",
    "超流体": "superfluid",
    "玻色-爱因斯坦凝聚": "Bose-Einstein condensate",
    "磁共振": "magnetic resonance",
    "铁电体": "ferroelectric",
    "反铁磁": "antiferromagnetic",
    "莫特绝缘体": "Mott insulator",
    "外尔半金属": "Weyl semimetal",
    "凝聚态": "condensed matter",
    # 光学
    "非线性光学": "nonlinear optics",
    "超快光学": "ultrafast optics",
    "光子学": "photonics",
    "等离激元": "plasmonics",
    "光子晶体": "photonic crystal",
    "超构材料": "metamaterial",
    "受激拉曼散射": "stimulated Raman scattering",
    # [新增] 光镊和光学操纵
    "光镊": "optical tweezers",
    "光阱": "optical trap",
    "光捕获": "optical trapping",
    "光学操纵": "optical manipulation",
    "光扭矩": "optical torque",
    "光力": "optical force",
    "梯度力": "gradient force",
    "散射力": "scattering force",
    # [新增] 激光相关
    "飞秒激光": "femtosecond laser",
    "皮秒激光": "picosecond laser",
    "纳秒激光": "nanosecond laser",
    "连续激光": "continuous wave laser",
    "脉冲激光": "pulsed laser",
    "超快激光": "ultrafast laser",
    # [新增] 等离激元和表面增强
    "表面等离激元": "surface plasmon",
    "等离激元共振": "plasmon resonance",
    "表面增强拉曼散射": "surface-enhanced Raman scattering",
    "局域表面等离激元": "localized surface plasmon",
    # [新增] 近场光学和太赫兹
    "近场光学": "near-field optics",
    "远场光学": "far-field optics",
    "太赫兹": "terahertz",
    "太赫兹辐射": "terahertz radiation",
    "二次谐波": "second harmonic generation",
    "光学参量振荡": "optical parametric oscillation",
    # 粒子物理
    "夸克": "quark",
    "轻子": "lepton",
    "玻色子": "boson",
    "费米子": "fermion",
    "标准模型": "standard model",
    "希格斯玻色子": "Higgs boson",
    "中微子": "neutrino",
    "正电子": "positron",
    "反物质": "antimatter",
    # 核物理
    "核裂变": "nuclear fission",
    "核聚变": "nuclear fusion",
    "放射性衰变": "radioactive decay",
    "α衰变": "alpha decay",
    "β衰变": "beta decay",
    "γ射线": "gamma ray",
    # 天体物理
    "黑洞": "black hole",
    "中子星": "neutron star",
    "白矮星": "white dwarf",
    "脉冲星": "pulsar",
    "类星体": "quasar",
    "星系": "galaxy",
    "暗物质": "dark matter",
    "暗能量": "dark energy",
    "引力波": "gravitational wave",
    "宇宙微波背景辐射": "cosmic microwave background",
    "恒星演化": "stellar evolution",
    "超新星": "supernova",
    "吸积盘": "accretion disk",
    "红移": "redshift",
    "视界": "event horizon",
    "霍金辐射": "Hawking radiation",
    # 量子物理
    "量子纠缠": "quantum entanglement",
    "量子计算": "quantum computing",
    "量子通信": "quantum communication",
    "量子比特": "qubit",
    "量子退相干": "quantum decoherence",
    "贝尔不等式": "Bell inequality",
    "量子隐形传态": "quantum teleportation",
    "薛定谔方程": "Schrödinger equation",
    "波函数": "wave function",
    "海森堡不确定性原理": "Heisenberg uncertainty principle",
    "路径积分": "path integral",
    "量子场论": "quantum field theory",
    # 等离子体物理
    "等离子体": "plasma",
    "托卡马克": "tokamak",
    "惯性约束聚变": "inertial confinement fusion",
    "德拜长度": "Debye length",
    # 声学
    "声子": "phonon",
    "声学超材料": "acoustic metamaterial",
    "声发射": "acoustic emission",
    "声悬浮": "acoustic levitation",
    # 热力学
    "熵": "entropy",
    "焓": "enthalpy",
    "临界点": "critical point",
    "玻尔兹曼分布": "Boltzmann distribution",
    "伊辛模型": "Ising model",
    "自由能": "free energy",
    "比热容": "specific heat capacity",
    "热导率": "thermal conductivity",
    "热辐射": "thermal radiation",
    "黑体辐射": "blackbody radiation",
    # 流体力学
    "湍流": "turbulence",
    "纳维-斯托克斯方程": "Navier-Stokes equation",
    "边界层": "boundary layer",
    "涡旋": "vortex",
    # ========== 工程技术 ==========
    "人工智能": "artificial intelligence",
    "机器学习": "machine learning",
    "深度学习": "deep learning",
    "神经网络": "neural network",
    "自然语言处理": "natural language processing",
    "计算机视觉": "computer vision",
    # 机械工程
    "有限元分析": "finite element analysis",
    "流体力学": "fluid mechanics",
    "热传导": "heat transfer",
    "材料力学": "mechanics of materials",
    "焊接": "welding",
    "切削加工": "machining",
    "增材制造": "additive manufacturing",
    "数控加工": "CNC machining",
    "铸造": "casting",
    # 电气工程
    "电机": "electric motor",
    "电力系统": "power system",
    "电磁场": "electromagnetic field",
    "变压器": "transformer",
    "电力电子": "power electronics",
    "变频器": "inverter",
    "绝缘": "insulation",
    "谐波": "harmonics",
    # 电子工程
    "集成电路": "integrated circuit",
    "场效应晶体管": "field-effect transistor",
    "MOSFET": "MOSFET",
    "印制电路板": "printed circuit board",
    "可编程逻辑器件": "programmable logic device",
    "射频": "radio frequency",
    "天线": "antenna",
    "信号处理": "signal processing",
    # 计算机科学
    "算法": "algorithm",
    "数据结构": "data structure",
    "操作系统": "operating system",
    "分布式系统": "distributed system",
    "软件工程": "software engineering",
    # 人工智能
    "卷积神经网络": "convolutional neural network",
    "循环神经网络": "recurrent neural network",
    "生成对抗网络": "generative adversarial network",
    "强化学习": "reinforcement learning",
    "迁移学习": "transfer learning",
    "注意力机制": "attention mechanism",
    "语义分割": "semantic segmentation",
    "目标检测": "object detection",
    "语义分析": "semantic analysis",
    "大语言模型": "large language model",
    "变换器": "transformer",
    "预训练": "pre-training",
    "微调": "fine-tuning",
    "提示工程": "prompt engineering",
    "检索增强生成": "retrieval-augmented generation",
    # 机器人学
    "运动学": "kinematics",
    "控制器": "controller",
    "传感器": "sensor",
    "执行器": "actuator",
    "路径规划": "path planning",
    "同时定位与建图": "simultaneous localization and mapping",
    # 土木工程
    "岩土工程": "geotechnical engineering",
    "混凝土": "concrete",
    "结构工程": "structural engineering",
    # 化学工程
    "蒸馏": "distillation",
    "传质": "mass transfer",
    "反应工程": "reaction engineering",
    "分离工程": "separation engineering",
    # 航空航天
    "空气动力学": "aerodynamics",
    "推进系统": "propulsion system",
    "飞行控制": "flight control",
    "涡轮": "turbine",
    "无人机": "unmanned aerial vehicle",
    # 生物医学工程
    "生物力学": "biomechanics",
    "医学影像": "medical imaging",
    "康复工程": "rehabilitation engineering",
    "组织工程": "tissue engineering",
    # 能源
    "燃料电池": "fuel cell",
    "风力发电": "wind power",
    "生物质能": "bioenergy",
    "储能": "energy storage",
    "超级电容器": "supercapacitor",
    "锂硫电池": "lithium-sulfur battery",
    "钠离子电池": "sodium-ion battery",
    "锌空气电池": "zinc-air battery",
    # ========== 环境科学与地球科学 ==========
    "环境": "environment",
    "污染": "pollution",
    "气候": "climate",
    "碳排放": "carbon emission",
    "可持续": "sustainable",
    "可再生能源": "renewable energy",
    "氢能": "hydrogen energy",
    # 大气污染
    "大气污染": "air pollution",
    "颗粒物": "particulate matter",
    "PM2.5": "PM2.5",
    "臭氧": "ozone",
    "二氧化硫": "sulfur dioxide",
    "氮氧化物": "nitrogen oxides",
    "挥发性有机物": "volatile organic compounds",
    "酸雨": "acid rain",
    "光化学烟雾": "photochemical smog",
    # 水污染
    "水污染": "water pollution",
    "废水处理": "wastewater treatment",
    "富营养化": "eutrophication",
    "化学需氧量": "chemical oxygen demand",
    "生化需氧量": "biochemical oxygen demand",
    "重金属": "heavy metals",
    "地下水": "groundwater",
    "地表水": "surface water",
    "膜分离": "membrane separation",
    # 土壤污染
    "土壤污染": "soil pollution",
    "土壤修复": "soil remediation",
    "有机污染物": "organic pollutants",
    "农药残留": "pesticide residue",
    "生物修复": "bioremediation",
    "植物修复": "phytoremediation",
    # 固废处理
    "固体废物": "solid waste",
    "垃圾填埋": "landfill",
    "焚烧": "incineration",
    "回收利用": "recycling",
    "危险废物": "hazardous waste",
    "电子废弃物": "e-waste",
    "塑料污染": "plastic pollution",
    "微塑料": "microplastics",
    # 气候变化
    "温室效应": "greenhouse effect",
    "温室气体": "greenhouse gas",
    "全球变暖": "global warming",
    "碳循环": "carbon cycle",
    "碳足迹": "carbon footprint",
    "碳中和": "carbon neutrality",
    "碳达峰": "carbon peak",
    "净零排放": "net zero emissions",
    "极端天气": "extreme weather",
    "气候变化": "climate change",
    "全球气候模型": "global climate model",
    "海平面上升": "sea level rise",
    "冰川消融": "glacier retreat",
    "冻土融化": "permafrost thawing",
    "厄尔尼诺": "El Nino",
    "干旱": "drought",
    "洪涝": "flooding",
    # 生态学
    "生态系统": "ecosystem",
    "生物多样性": "biodiversity",
    "种群": "population",
    "群落": "community",
    "食物链": "food chain",
    "食物网": "food web",
    "生态修复": "ecological restoration",
    "物种灭绝": "species extinction",
    "入侵物种": "invasive species",
    "生物富集": "bioaccumulation",
    "保护生物学": "conservation biology",
    # 地质学
    "岩石": "rock",
    "矿物": "mineral",
    "地震": "earthquake",
    "火山": "volcano",
    "板块构造": "plate tectonics",
    "沉积物": "sediment",
    "岩浆": "magma",
    "地壳": "crust",
    "地幔": "mantle",
    "断层": "fault",
    "褶皱": "fold",
    "侵蚀": "erosion",
    "风化": "weathering",
    "变质作用": "metamorphism",
    "古生物学": "paleontology",
    "地层学": "stratigraphy",
    # 海洋学
    "海洋": "ocean",
    "洋流": "ocean current",
    "海洋酸化": "ocean acidification",
    "深海": "deep sea",
    "珊瑚礁": "coral reef",
    "潮汐": "tide",
    "海啸": "tsunami",
    "海水淡化": "desalination",
    # 水文学
    "径流": "runoff",
    "水循环": "water cycle",
    "流域": "watershed",
    "水文模型": "hydrological model",
    "蒸散发": "evapotranspiration",
    "降水": "precipitation",
    "地下水位": "water table",
    "含水层": "aquifer",
    "水土流失": "soil erosion",
    # 大气科学
    "气象": "meteorology",
    "大气化学": "atmospheric chemistry",
    "大气层": "atmosphere",
    "对流层": "troposphere",
    "平流层": "stratosphere",
    "气溶胶": "aerosol",
    "太阳辐射": "solar radiation",
    "大气环流": "atmospheric circulation",
    "季风": "monsoon",
    # 遥感
    "遥感": "remote sensing",
    "卫星遥感": "satellite remote sensing",
    "激光雷达": "LiDAR",
    "合成孔径雷达": "synthetic aperture radar",
    "植被指数": "vegetation index",
    "多光谱": "multispectral",
    "高光谱": "hyperspectral",
    "空间分辨率": "spatial resolution",
    "反演": "inversion",
    # 地理信息系统
    "地理信息系统": "geographic information system",
    "空间分析": "spatial analysis",
    "地理数据": "geospatial data",
    "空间插值": "spatial interpolation",
    "数字高程模型": "digital elevation model",
    "空间自相关": "spatial autocorrelation",
    "克里金插值": "kriging",
    # 可持续发展
    "碳交易": "carbon trading",
    "碳市场": "carbon market",
    "清洁能源": "clean energy",
    "循环经济": "circular economy",
    "绿色建筑": "green building",
    "可持续发展": "sustainable development",
    "生命周期评估": "life cycle assessment",
    "环境影响评价": "environmental impact assessment",
    # 其他环境
    "荒漠化": "desertification",
    "水土保持": "soil and water conservation",
    "地质灾害": "geological hazard",
    "滑坡": "landslide",
    "泥石流": "debris flow",
    "地面沉降": "land subsidence",
    "城市热岛": "urban heat island",
    "城市化": "urbanization",
    "土地利用": "land use",
    "土地覆盖": "land cover",
    # ========== 社会科学 ==========
    # 经济学
    "微观经济学": "microeconomics",
    "宏观经济学": "macroeconomics",
    "计量经济学": "econometrics",
    "博弈论": "game theory",
    "供需": "supply and demand",
    "边际效用": "marginal utility",
    "货币政策": "monetary policy",
    "财政政策": "fiscal policy",
    "通货膨胀": "inflation",
    "经济周期": "business cycle",
    "市场失灵": "market failure",
    "外部性": "externality",
    "机会成本": "opportunity cost",
    "人力资本": "human capital",
    # 管理学
    "组织行为": "organizational behavior",
    "战略管理": "strategic management",
    "人力资源": "human resource",
    "领导力": "leadership",
    "决策理论": "decision theory",
    "公司治理": "corporate governance",
    "运营管理": "operations management",
    "创新管理": "innovation management",
    "利益相关者": "stakeholder",
    "资源配置": "resource allocation",
    # 心理学
    "认知心理学": "cognitive psychology",
    "发展心理学": "developmental psychology",
    "社会心理学": "social psychology",
    "行为主义": "behaviorism",
    "人格": "personality",
    "情绪调节": "emotion regulation",
    "自我效能": "self-efficacy",
    "心理弹性": "resilience",
    "创伤后应激": "post-traumatic stress",
    "认知偏差": "cognitive bias",
    # 教育学
    "教学法": "pedagogy",
    "学习理论": "learning theory",
    "课程设计": "curriculum design",
    "教育公平": "educational equity",
    "批判性思维": "critical thinking",
    "形成性评估": "formative assessment",
    "混合式学习": "blended learning",
    "教育技术": "educational technology",
    "元认知": "metacognition",
    "建构主义": "constructivism",
    # 社会学
    "社会结构": "social structure",
    "社会分层": "social stratification",
    "社会资本": "social capital",
    "社会网络": "social network",
    "社会不平等": "social inequality",
    "文化资本": "cultural capital",
    "移民": "migration",
    "人口老龄化": "population aging",
    "社会流动性": "social mobility",
    "社会认同": "social identity",
    "社会规范": "social norm",
    # 政治学
    "政治理论": "political theory",
    "国际关系": "international relations",
    "公共政策": "public policy",
    "治理": "governance",
    "民主": "democracy",
    "地缘政治": "geopolitics",
    "政治参与": "political participation",
    "选举": "election",
    "主权": "sovereignty",
    "多边主义": "multilateralism",
    "国际安全": "international security",
    # 法学
    "法理学": "jurisprudence",
    "比较法": "comparative law",
    "国际法": "international law",
    "知识产权": "intellectual property",
    "人权": "human rights",
    "合同法": "contract law",
    "宪法": "constitutional law",
    "合规": "compliance",
    "仲裁": "arbitration",
    "侵权": "tort",
    # 新闻传播学
    "媒介理论": "media theory",
    "舆论": "public opinion",
    "数字传播": "digital communication",
    "框架理论": "framing theory",
    "议程设置": "agenda setting",
    "媒介素养": "media literacy",
    "跨文化传播": "intercultural communication",
    "信息茧房": "filter bubble",
    # 语言学
    "语义学": "semantics",
    "语用学": "pragmatics",
    "句法学": "syntax",
    "二语习得": "second language acquisition",
    "社会语言学": "sociolinguistics",
    "语料库语言学": "corpus linguistics",
    "话语分析": "discourse analysis",
    "认知语言学": "cognitive linguistics",
    "应用语言学": "applied linguistics",
    # 历史学
    "史料": "historical sources",
    "史学方法": "historiography",
    "口述历史": "oral history",
    "历史唯物主义": "historical materialism",
    "文化史": "cultural history",
    "社会史": "social history",
    "经济史": "economic history",
    "全球史": "global history",
    # ========== 通用学术术语 ==========
    "综述": "review",
    "进展": "progress",
    "研究": "research",
    "应用": "application",
    "性能": "performance",
    "结构": "structure",
    "制备": "preparation",
    "表征": "characterization",
    "机理": "mechanism",
    "动力学": "kinetics",
    "热力学": "thermodynamics",
    "创新": "innovation",
    "优化": "optimization",
    "策略": "strategy",
    "挑战": "challenge",
    "前景": "perspective",
    "趋势": "trend",
    "比较": "comparison",
    "影响": "influence",
    "因素": "factor",
    "模型": "model",
    "框架": "framework",
    "方法": "method",
    "技术": "technology",
    "系统": "system",
    "分析": "analysis",
    "设计": "design",
    "开发": "development",
    "评价": "evaluation",
}


# ============================================================
# 学术同义词扩展映射表
# key: 英文核心词（翻译后），value: OR连接的同义词表达式
# 用于在翻译后扩展查询，提升英文数据库的召回率
# ============================================================
_SYNONYM_MAP = {
    # ---- 材料科学 ----
    "nanomaterials": "(nanomaterials OR nanostructured materials OR nanoscale materials)",
    "nanoparticles": "(nanoparticles OR nanoscale particles OR nanostructures)",
    "thin films": "(thin films OR thin film coatings OR surface coatings)",
    "composite materials": "(composite materials OR composites OR hybrid materials)",
    "mechanical properties": "(mechanical properties OR mechanical behavior OR tensile strength)",
    "microstructure": "(microstructure OR microstructural morphology OR grain structure)",
    "surface modification": "(surface modification OR surface functionalization OR surface treatment)",
    "thermal stability": "(thermal stability OR thermal resistance OR heat resistance)",
    "corrosion resistance": "(corrosion resistance OR anti-corrosion OR corrosion protection)",
    "wear resistance": "(wear resistance OR tribological properties OR anti-wear)",
    # ---- 化学 ----
    "catalyst": "(catalysts OR catalytic materials OR catalysis)",
    "electrode materials": "(electrode materials OR electrode composites OR working electrode)",
    "polymer": "(polymers OR polymeric materials OR macromolecules)",
    "organic synthesis": "(organic synthesis OR synthetic methodology OR chemical synthesis)",
    "electrochemistry": "(electrochemistry OR electrochemical methods OR voltammetry)",
    "chromatography": "(chromatography OR HPLC OR high-performance liquid chromatography)",
    "spectroscopy": "(spectroscopy OR spectral analysis OR spectral characterization)",
    "nanocomposite": "(nanocomposites OR nanocomposite materials OR nanohybrids)",
    "photocatalysis": "(photocatalysis OR photocatalytic degradation OR photochemical catalysis)",
    # ---- 生物医学 ----
    "biomarker": "(biomarkers OR biological markers OR diagnostic markers)",
    "gene expression": "(gene expression OR transcriptional regulation OR mRNA expression)",
    "immune response": "(immune response OR immune system OR immunological response)",
    "drug delivery": "(drug delivery OR drug transport OR pharmaceutical delivery)",
    "cell proliferation": "(cell proliferation OR cell growth OR cellular proliferation)",
    "apoptosis": "(apoptosis OR programmed cell death OR cell death)",
    "signal pathway": "(signaling pathway OR signal transduction OR molecular pathway)",
    "gene therapy": "(gene therapy OR genetic therapy OR gene editing)",
    "protein structure": "(protein structure OR protein folding OR 3D structure)",
    "clinical trial": "(clinical trial OR clinical study OR randomized controlled trial)",
    "tumor": "(tumor OR neoplasm OR cancer OR malignancy)",
    "stem cell": "(stem cells OR progenitor cells OR pluripotent cells)",
    "inflammation": "(inflammation OR inflammatory response OR inflammatory process)",
    "antibiotic resistance": "(antibiotic resistance OR antimicrobial resistance OR drug resistance)",
    "microbiome": "(microbiome OR microbial community OR gut flora)",
    # ---- 环境科学 ----
    "pollution": "(pollution OR environmental contamination OR environmental pollution)",
    "water treatment": "(water treatment OR wastewater treatment OR water purification)",
    "air quality": "(air quality OR atmospheric pollution OR ambient air)",
    "climate change": "(climate change OR global warming OR climate variability)",
    "biodiversity": "(biodiversity OR biological diversity OR species diversity)",
    "sustainable development": "(sustainable development OR sustainability OR green development)",
    "renewable energy": "(renewable energy OR clean energy OR sustainable energy)",
    "carbon emission": "(carbon emission OR CO2 emission OR greenhouse gas emission)",
    "waste management": "(waste management OR solid waste OR waste disposal)",
    # ---- 物理/电子 ----
    "semiconductor": "(semiconductors OR semiconductor materials OR semiconductor devices)",
    "superconductor": "(superconductors OR superconducting materials OR high-temperature superconductor)",
    "magnetic properties": "(magnetic properties OR magnetic behavior OR magnetism)",
    "optical properties": "(optical properties OR optical behavior OR photonic properties)",
    "energy storage": "(energy storage OR energy density OR power density)",
    "battery": "(batteries OR battery materials OR electrochemical energy storage)",
    "solar cell": "(solar cells OR photovoltaic cells OR solar energy)",
    "transistor": "(transistors OR field-effect transistor OR MOSFET)",
    "sensor": "(sensors OR sensing devices OR detection devices)",
    # ---- 计算机/信息 ----
    "machine learning": "(machine learning OR ML OR artificial intelligence)",
    "deep learning": "(deep learning OR neural network OR deep neural network)",
    "natural language processing": "(natural language processing OR NLP OR computational linguistics)",
    "computer vision": "(computer vision OR image recognition OR visual recognition)",
    "data mining": "(data mining OR knowledge discovery OR pattern recognition)",
    "algorithm": "(algorithms OR computational method OR optimization algorithm)",
    # ---- 工程 ----
    "manufacturing": "(manufacturing OR fabrication OR production process)",
    "3D printing": "(3D printing OR additive manufacturing OR rapid prototyping)",
    "automation": "(automation OR automatic control OR robotic automation)",
    "structural analysis": "(structural analysis OR stress analysis OR finite element analysis)",
    "fatigue": "(fatigue OR fatigue life OR cyclic loading)",
    # ---- 通用学术术语 ----
    "review": "(review OR overview OR systematic review OR literature review)",
    "meta-analysis": "(meta-analysis OR pooled analysis OR systematic review)",
    "case study": "(case study OR case report OR case series)",
    "longitudinal study": "(longitudinal study OR cohort study OR prospective study)",
    "cross-sectional": "(cross-sectional OR cross-sectional study OR prevalence study)",
    "randomized controlled trial": "(randomized controlled trial OR RCT OR random allocation)",
    "systematic review": "(systematic review OR evidence synthesis OR systematic literature review)",
    "state of the art": "(state of the art OR current advances OR recent progress)",
}


def _expand_synonyms(text: str) -> str:
    """对英文查询进行同义词扩展，提升召回率

    将匹配到的核心词替换为 OR 连接的同义词表达式。
    例如: "nanomaterials synthesis" -> "(nanomaterials OR nanostructured materials OR nanoscale materials) synthesis"

    Args:
        text: 英文查询文本

    Returns:
        str: 扩展后的查询文本
    """
    if not text:
        return text

    result = text
    # 按 key 长度降序排序，优先匹配长词，避免短词误匹配
    sorted_synonyms = sorted(
        _SYNONYM_MAP.items(), key=lambda x: len(x[0]), reverse=True
    )

    for term, expansion in sorted_synonyms:
        # 使用单词边界匹配，避免子串误匹配
        pattern = r"\b" + re.escape(term.strip()) + r"\b"
        # 只替换首次匹配（防止扩展文本被重复处理）
        result = re.sub(pattern, expansion, result, count=1, flags=re.IGNORECASE)

    return result


def _translate_zh_to_en(text: str) -> str:
    """将中文科技术语翻译为英文（使用离线字典）

    对于字典中没有的术语，保留原文。
    这是一个简单的词典翻译，不依赖外部API。
    """
    if not text or not _contains_chinese(text):
        return text

    result = text
    # 按词长度降序排序，优先匹配长词
    sorted_dict = sorted(_ZH_EN_DICT.items(), key=lambda x: len(x[0]), reverse=True)
    for zh, en in sorted_dict:
        result = result.replace(zh, f" {en} ")

    # 清理多余空格
    result = re.sub(r"\s+", " ", result).strip()
    return result


class TranslationCache:
    """翻译缓存管理器

    功能：
    1. 缓存AI翻译结果到本地文件
    2. 提供快速查询缓存的翻译
    3. 支持增量更新缓存
    """

    def __init__(self, cache_file: str = None):
        self._cache = {}
        self._cache_file = cache_file
        self._lock = threading.Lock()
        self._load_cache()

    def _load_cache(self):
        """从文件加载缓存"""
        if not self._cache_file:
            return
        try:
            import json
            import os

            if os.path.exists(self._cache_file):
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                print(f"[INFO] 翻译缓存已加载: {len(self._cache)} 条")
        except Exception as e:
            print(f"[WARN] 加载翻译缓存失败: {e}")

    def _save_cache(self):
        """保存缓存到文件"""
        if not self._cache_file:
            return
        try:
            import json
            import os

            os.makedirs(os.path.dirname(self._cache_file), exist_ok=True)
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WARN] 保存翻译缓存失败: {e}")

    def get(self, text: str) -> str:
        """从缓存获取翻译"""
        with self._lock:
            return self._cache.get(text)

    def put(self, zh_text: str, en_text: str):
        """添加翻译到缓存"""
        with self._lock:
            if zh_text not in self._cache:
                self._cache[zh_text] = en_text
                self._save_cache()

    def size(self) -> int:
        """获取缓存大小"""
        return len(self._cache)


class HybridTranslator:
    """混合翻译器

    架构：
    1. 第一层：字典匹配（0ms，离线可用）
    2. 第二层：缓存查询（0ms，离线可用）
    3. 第三层：AI翻译（需联网，可选）
    """

    def __init__(self, ai_provider=None, cache_file: str = None):
        """
        Args:
            ai_provider: AI提供商实例（可选）
            cache_file: 缓存文件路径（可选）
        """
        self._ai_provider = ai_provider
        self._cache = TranslationCache(cache_file)
        self._sorted_dict = sorted(
            _ZH_EN_DICT.items(), key=lambda x: len(x[0]), reverse=True
        )

    def translate(self, text: str) -> str:
        """翻译中文到英文

        Args:
            text: 中文文本

        Returns:
            str: 英文翻译结果
        """
        if not text or not _contains_chinese(text):
            return text

        # 第一层：字典翻译
        result = self._dict_translate(text)

        # 检查是否仍有中文
        if not _contains_chinese(result):
            return result

        # 第二层：缓存查询
        cached = self._cache.get(text)
        if cached:
            return cached

        # 第三层：AI翻译（如果可用）
        if self._ai_provider:
            try:
                ai_result = self._ai_translate(text)
                if ai_result and not _contains_chinese(ai_result):
                    # 缓存AI翻译结果
                    self._cache.put(text, ai_result)
                    return ai_result
            except Exception as e:
                print(f"[WARN] AI翻译失败: {e}")

        # 降级：返回字典翻译结果（可能含中文）
        return result

    def _dict_translate(self, text: str) -> str:
        """字典翻译"""
        result = text
        for zh, en in self._sorted_dict:
            result = result.replace(zh, f" {en} ")
        return re.sub(r"\s+", " ", result).strip()

    def _ai_translate(self, text: str) -> str:
        """AI翻译"""
        if not self._ai_provider:
            return None

        prompt = f"""将以下中文学术查询翻译为英文，用于搜索国际学术数据库（PubMed、OpenAlex等）。

要求：
1. 只返回英文翻译，不要解释
2. 保持学术术语的准确性
3. 使用简洁的关键词形式，适合数据库搜索
4. 如果是多个概念，用空格分隔

中文查询：{text}

英文翻译："""

        try:
            # 调用AI进行翻译
            result = self._ai_provider.chat(prompt, max_tokens=100)
            if result:
                # 清理AI返回的结果
                result = result.strip()
                # 移除可能的引号
                if result.startswith('"') and result.endswith('"'):
                    result = result[1:-1]
                if result.startswith("'") and result.endswith("'"):
                    result = result[1:-1]
                return result
        except Exception as e:
            print(f"[WARN] AI翻译调用失败: {e}")
            return None

    def get_cache_size(self) -> int:
        """获取缓存大小"""
        return self._cache.size()


# 全局翻译器实例（由SearchEngine初始化时设置）
_translator = None


def _get_translator() -> HybridTranslator:
    """获取全局翻译器实例"""
    global _translator
    if _translator is None:
        # 默认使用字典翻译（无AI回退）
        _translator = HybridTranslator()
    return _translator


def _set_translator(translator: HybridTranslator):
    """设置全局翻译器实例"""
    global _translator
    _translator = translator


@dataclass
class Paper:
    title: str = ""
    authors: List[str] = field(default_factory=list)
    journal: str = ""
    year: int = 0
    doi: str = ""
    pmid: str = ""
    abstract: str = ""
    citation_count: int = 0
    oa_url: str = ""
    keywords: List[str] = field(default_factory=list)
    source: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    issn: str = ""
    # Phase 5a: 学术元数据（从 OpenAlex/PubMed/S2 解析）
    orcid: str = ""  # 通讯作者 ORCID
    article_type: str = ""  # 文章类型：journal-article, review, book-chapter, etc.
    conference: str = ""  # 会议名称（会议论文场景）
    funding: List[str] = field(default_factory=list)  # 资助信息列表
    affiliations: List[str] = field(default_factory=list)  # 作者机构列表
    # Phase 5a: 来源追踪（多源去重用）
    sources: List[str] = field(default_factory=list)  # 论文来自哪些数据源
    # Phase 5a: 阅读管理（用户自定义状态，仅收藏夹使用）
    reading_status: str = ""  # "unread" | "reading" | "read" | ""
    tags: List[str] = field(default_factory=list)  # 用户标签
    notes: str = ""  # 用户笔记（纯文本）
    # Phase 5b: 版本关系（预印本/正式版关联）
    related_versions: List[str] = field(default_factory=list)  # 关联版本 DOI 列表
    # 专利标识
    doc_type: str = ""  # "paper" | "patent"，区分论文和专利
    # 元数据完整性评分 (0-100)
    completeness_score: int = 0


def _paper_to_dict(paper: Paper) -> dict:
    """将 Paper 对象序列化为 dict（用于 JSON 缓存）"""
    return {
        "title": paper.title or "",
        "authors": list(paper.authors or []),
        "journal": paper.journal or "",
        "year": paper.year or 0,
        "doi": paper.doi or "",
        "pmid": paper.pmid or "",
        "abstract": paper.abstract or "",
        "citation_count": paper.citation_count or 0,
        "oa_url": paper.oa_url or "",
        "keywords": list(paper.keywords or []),
        "source": paper.source or "",
        "volume": paper.volume or "",
        "issue": paper.issue or "",
        "pages": paper.pages or "",
        "issn": paper.issn or "",
        "orcid": paper.orcid or "",
        "article_type": paper.article_type or "",
        "conference": paper.conference or "",
        "funding": list(paper.funding or []),
        "sources": list(paper.sources or []),
        "reading_status": paper.reading_status or "",
        "tags": list(paper.tags or []),
        "notes": paper.notes or "",
        "related_versions": list(paper.related_versions or []),
        "doc_type": paper.doc_type or "",
        "completeness_score": paper.completeness_score or 0,
    }


def _dict_to_paper(d: dict) -> Paper:
    """将 dict 反序列化为 Paper 对象（用于 JSON 缓存读取）"""
    if not isinstance(d, dict):
        return None
    try:
        return Paper(
            title=d.get("title", ""),
            authors=d.get("authors", []) if isinstance(d.get("authors"), list) else [],
            journal=d.get("journal", ""),
            year=d.get("year", 0) or 0,
            doi=d.get("doi", ""),
            pmid=d.get("pmid", ""),
            abstract=d.get("abstract", ""),
            citation_count=d.get("citation_count", 0) or 0,
            oa_url=d.get("oa_url", ""),
            keywords=d.get("keywords", [])
            if isinstance(d.get("keywords"), list)
            else [],
            source=d.get("source", ""),
            volume=d.get("volume", ""),
            issue=d.get("issue", ""),
            pages=d.get("pages", ""),
            issn=d.get("issn", ""),
            orcid=d.get("orcid", ""),
            article_type=d.get("article_type", ""),
            conference=d.get("conference", ""),
            funding=d.get("funding", []) if isinstance(d.get("funding"), list) else [],
            sources=d.get("sources", []) if isinstance(d.get("sources"), list) else [],
            reading_status=d.get("reading_status", ""),
            tags=d.get("tags", []) if isinstance(d.get("tags"), list) else [],
            notes=d.get("notes", ""),
            related_versions=d.get("related_versions", [])
            if isinstance(d.get("related_versions"), list)
            else [],
            doc_type=d.get("doc_type", ""),
            completeness_score=d.get("completeness_score", 0),
        )
    except Exception:
        return None


# ============================================================
# 数据源插件架构
# ============================================================

from abc import ABC, abstractmethod


class BaseSearchSource(ABC):
    """数据源插件基类。所有数据源适配器继承此类并实现 search() 接口。

    子类必须定义类属性：
        SOURCE_NAME: str     -- 唯一标识（如 "pubmed"）
        DISPLAY_NAME: str    -- 显示名称（如 "PubMed"）
        DEFAULT_ENABLED: bool -- 默认是否启用

    可选类属性：
        IS_CHINESE: bool     -- 是否使用中文查询（默认 False）
        REQUIRES_COOKIES: bool -- 是否需要 CARSI cookies（默认 False）
        MAX_RESULTS: int     -- 默认最大结果数（默认 50）
    """

    SOURCE_NAME: str = ""
    DISPLAY_NAME: str = ""
    DEFAULT_ENABLED: bool = True
    IS_CHINESE: bool = False
    REQUIRES_COOKIES: bool = False
    MAX_RESULTS: int = 50

    def __init__(self, **config):
        self.proxy = config.get("proxy")
        self.access_proxy = config.get("access_proxy")
        self.carsi_cookies = config.get("carsi_cookies")

    @abstractmethod
    def search(
        self, query: str, year_from: int, year_to: int, max_results: int = 50, **kwargs
    ) -> list:
        """执行搜索，返回 Paper 列表。

        Args:
            query: 检索词（英文或中文，取决于 IS_CHINESE）
            year_from: 起始年份
            year_to: 结束年份
            max_results: 最大结果数
            **kwargs: 额外参数（sort, journal, field 等）
        """
        ...

    def is_available(self) -> bool:
        """检查数据源是否可用（子类可覆盖）"""
        return True


# --- 全局注册表 ---
_SOURCE_REGISTRY: dict = {}  # source_name -> BaseSearchSource subclass


def register_source(cls):
    """装饰器：注册数据源类到全局注册表。

    用法::

        @register_source
        class MySource(BaseSearchSource):
            SOURCE_NAME = "my_source"
            DISPLAY_NAME = "My Source"
            ...
    """
    name = getattr(cls, "SOURCE_NAME", "")
    if not name:
        raise ValueError(f"{cls.__name__} must define SOURCE_NAME")
    _SOURCE_REGISTRY[name] = cls
    return cls


def get_source_registry() -> dict:
    """获取所有已注册的数据源（只读副本）"""
    return dict(_SOURCE_REGISTRY)


def get_source_names() -> list:
    """获取所有已注册数据源的名称列表"""
    return sorted(_SOURCE_REGISTRY.keys())


# 常用期刊缩写映射（用于智能查询构建）
JOURNAL_ALIASES = {
    "nature": "Nature",
    "science": "Science",
    "cell": "Cell",
    "nature methods": "Nat Methods",
    "nat methods": "Nat Methods",
    "nature photonics": "Nat Photonics",
    "nat photonics": "Nat Photonics",
    "nature cell biology": "Nat Cell Biol",
    "nat cell biol": "Nat Cell Biol",
    "nature neuroscience": "Nat Neurosci",
    "nat neurosci": "Nat Neurosci",
    "nature biotechnology": "Nat Biotechnol",
    "nat biotechnol": "Nat Biotechnol",
    "nature communications": "Nat Commun",
    "nat commun": "Nat Commun",
    "nature chemistry": "Nat Chem",
    "nat chem": "Nat Chem",
    "nature physics": "Nat Phys",
    "nat phys": "Nat Phys",
    "nature materials": "Nat Mater",
    "nat mater": "Nat Mater",
    "nature medicine": "Nat Med",
    "nat med": "Nat Med",
    "nature biomedical engineering": "Nat Biomed Eng",
    "cell reports": "Cell Rep",
    "cell rep": "Cell Rep",
    "cell stem cell": "Cell Stem Cell",
    "cell metabolism": "Cell Metab",
    "cell met": "Cell Metab",
    "molecular cell": "Mol Cell",
    "mol cell": "Mol Cell",
    "cancer cell": "Cancer Cell",
    "neuron": "Neuron",
    "immunity": "Immunity",
    "science advances": "Sci Adv",
    "sci adv": "Sci Adv",
    "acs nano": "ACS Nano",
    "light:science": "Light Sci Appl",
    "light science": "Light Sci Appl",
    "optica": "Optica",
    "optics express": "Opt Express",
    "opt express": "Opt Express",
    "biomedical optics": "J Biomed Opt",
    "j biomed opt": "J Biomed Opt",
    "journal of biomedical optics": "J Biomed Opt",
    # --- Nature 系列（补全） ---
    "nature genetics": "Nat Genet",
    "nat genet": "Nat Genet",
    "nature immunology": "Nat Immunol",
    "nat immunol": "Nat Immunol",
    "nature structural & molecular biology": "Nat Struct Mol Biol",
    "nat struct mol biol": "Nat Struct Mol Biol",
    "nature reviews molecular cell biology": "Nat Rev Mol Cell Biol",
    "nat rev mol cell biol": "Nat Rev Mol Cell Biol",
    "nature reviews neuroscience": "Nat Rev Neurosci",
    "nat rev neurosci": "Nat Rev Neurosci",
    "nature reviews genetics": "Nat Rev Genet",
    "nat rev genet": "Nat Rev Genet",
    "nature reviews immunology": "Nat Rev Immunol",
    "nat rev immunol": "Nat Rev Immunol",
    "nature reviews drug discovery": "Nat Rev Drug Discov",
    "nat rev drug discov": "Nat Rev Drug Discov",
    "nature human behaviour": "Nat Hum Behav",
    "nat hum behav": "Nat Hum Behav",
    "nature aging": "Nature Aging",
    "nature cancer": "Nature Cancer",
    "nature metabolism": "Nat Metab",
    "nat metab": "Nat Metab",
    "nature cardiovascular research": "Nat Cardiovasc Res",
    "nat cardiovasc res": "Nat Cardiovasc Res",
    "nature chemical biology": "Nat Chem Biol",
    "nat chem biol": "Nat Chem Biol",
    "nature ecology & evolution": "Nat Ecol Evol",
    "nat ecol evol": "Nat Ecol Evol",
    "nature electronics": "Nat Electron",
    "nat electron": "Nat Electron",
    "nature energy": "Nat Energy",
    "nat energy": "Nat Energy",
    "nature food": "Nat Food",
    "nat food": "Nat Food",
    "nature nanotechnology": "Nat Nanotechnol",
    "nat nanotechnol": "Nat Nanotechnol",
    "nature protocols": "Nat Protoc",
    "nat protoc": "Nat Protoc",
    "nature reviews clinical oncology": "Nat Rev Clin Oncol",
    "nat rev clin oncol": "Nat Rev Clin Oncol",
    "nature reviews chemistry": "Nat Rev Chem",
    "nat rev chem": "Nat Rev Chem",
    "nature reviews physics": "Nat Rev Phys",
    "nat rev phys": "Nat Rev Phys",
    "nature reviews materials": "Nat Rev Mater",
    "nat rev mater": "Nat Rev Mater",
    "nature reviews methods primers": "Nat Rev Methods Primers",
    # --- Cell 系列（补全） ---
    "cell host & microbe": "Cell Host Microbe",
    "cell host microbe": "Cell Host Microbe",
    "cell systems": "Cell Syst",
    "cell syst": "Cell Syst",
    "cell chemical biology": "Cell Chem Biol",
    "cell chem biol": "Cell Chem Biol",
    "cell reports medicine": "Cell Rep Med",
    "cell rep med": "Cell Rep Med",
    "cell reports physical science": "Cell Rep Phys Sci",
    "cell rep phys sci": "Cell Rep Phys Sci",
    "cell genomics": "Cell Genomics",
    "iscience": "iScience",
    # --- Science 系列（补全） ---
    "science translational medicine": "Sci Transl Med",
    "sci transl med": "Sci Transl Med",
    "science immunology": "Sci Immunol",
    "sci immunol": "Sci Immunol",
    "science robotics": "Sci Robot",
    "sci robot": "Sci Robot",
    "science signaling": "Sci Signal",
    "sci signal": "Sci Signal",
}

# ISSN 映射表：期刊名（全称/缩写）→ ISSN
# ISSN 是期刊唯一标识，比名称匹配更可靠
# 格式：{期刊名(小写): "ISSN"}
JOURNAL_ISSN = {
    # ========== 综合顶刊 ==========
    "nature": "0028-0836",
    "nat methods": "1546-1696",
    "nature methods": "1546-1696",
    "nat photonics": "1749-4885",
    "nature photonics": "1749-4885",
    "nat cell biol": "1465-7392",
    "nature cell biology": "1465-7392",
    "nat neurosci": "1097-6256",
    "nature neuroscience": "1097-6256",
    "nat biotechnol": "1087-0156",
    "nature biotechnology": "1087-0156",
    "nat commun": "2041-1723",
    "nature communications": "2041-1723",
    "nat chem": "1476-1122",
    "nature chemistry": "1476-1122",
    "nat phys": "1745-2473",
    "nature physics": "1745-2473",
    "nat mater": "1476-1121",
    "nature materials": "1476-1121",
    "nat med": "1078-8956",
    "nature medicine": "1078-8956",
    "nat biomed eng": "2157-846X",
    "nature biomedical engineering": "2157-846X",
    "nat genet": "1061-4036",
    "nature genetics": "1061-4036",
    "nat immunol": "1529-2908",
    "nature immunology": "1529-2908",
    "nat struct mol biol": "1545-9993",
    "nature structural & molecular biology": "1545-9993",
    "nat rev mol cell biol": "1465-7392",
    "nature reviews molecular cell biology": "1465-7392",
    "nat rev neurosci": "1471-003X",
    "nature reviews neuroscience": "1471-003X",
    "nat rev genet": "1471-0056",
    "nature reviews genetics": "1471-0056",
    "nat rev immunol": "1474-1733",
    "nature reviews immunology": "1474-1733",
    "nat rev drug discov": "1474-1776",
    "nature reviews drug discovery": "1474-1776",
    "nat hum behav": "2522-5804",
    "nature human behaviour": "2522-5804",
    "nature aging": "2662-1355",
    "nature cancer": "2662-1347",
    "nat metab": "2522-5812",
    "nature metabolism": "2522-5812",
    "nat cardiovasc res": "2522-1094",
    "nature cardiovascular research": "2522-1094",
    "nat chem biol": "1552-4450",
    "nature chemical biology": "1552-4450",
    "nat ecol evol": "2397-3374",
    "nature ecology & evolution": "2397-3374",
    "nat electron": "2520-1131",
    "nature electronics": "2520-1131",
    "nat energy": "2058-7546",
    "nature energy": "2058-7546",
    "nat food": "2662-1355",
    "nature food": "2662-1355",
    "nat nanotechnol": "1748-3387",
    "nature nanotechnology": "1748-3387",
    "nat protoc": "1754-2189",
    "nature protocols": "1754-2189",
    "nat rev clin oncol": "1759-4774",
    "nature reviews clinical oncology": "1759-4774",
    "nat rev chem": "2397-3358",
    "nature reviews chemistry": "2397-3358",
    "nat rev phys": "2524-4914",
    "nature reviews physics": "2524-4914",
    "nat rev mater": "2058-7546",
    "nature reviews materials": "2058-7546",
    "nat rev methods primers": "2662-8449",
    "nature reviews methods primers": "2662-8449",
    # ========== Science 系列 ==========
    "science": "0036-8075",
    "sci adv": "2375-2548",
    "science advances": "2375-2548",
    "sci transl med": "1946-6234",
    "science translational medicine": "1946-6234",
    "sci immunol": "2470-2986",
    "science immunology": "2470-2986",
    "sci robot": "2470-9476",
    "science robotics": "2470-9476",
    "sci signal": "1945-0877",
    "science signaling": "1945-0877",
    # ========== Cell 系列 ==========
    "cell": "0092-8674",
    "cell rep": "2211-1247",
    "cell reports": "2211-1247",
    "cell stem cell": "1934-5909",
    "cell metabolism": "1550-4131",
    "cell met": "1550-4131",
    "mol cell": "1097-2765",
    "molecular cell": "1097-2765",
    "cancer cell": "1535-6108",
    "neuron": "0896-6273",
    "immunity": "1074-7613",
    "cell host microbe": "1931-3128",
    "cell host & microbe": "1931-3128",
    "cell syst": "2405-4712",
    "cell systems": "2405-4712",
    "cell chem biol": "2451-9456",
    "cell chemical biology": "2451-9456",
    "cell rep med": "2666-3791",
    "cell reports medicine": "2666-3791",
    "cell rep phys sci": "2666-6836",
    "cell reports physical science": "2666-6836",
    "cell genomics": "2666-979X",
    "cell genomics": "2666-979X",
    "iscience": "2589-0042",
    "iscience": "2589-0042",
    # ========== 生物医学顶刊 ==========
    "lancet": "0140-6736",
    "the lancet": "0140-6736",
    "new engl j med": "0028-4793",
    "the new england journal of medicine": "0028-4793",
    "n engl j med": "0028-4793",
    "jama": "0098-7484",
    "journal of the american medical association": "0098-7484",
    "bmj": "0959-8138",
    "bmj-british medical journal": "0959-8138",
    "annals of internal medicine": "0003-4819",
    "ann intern med": "0003-4819",
    "nat rev clin oncol": "1759-4774",
    # ========== 化学 ==========
    "j am chem soc": "0002-7863",
    "journal of the american chemical society": "0002-7863",
    "jacs": "0002-7863",
    "angew chem int edit": "1433-7851",
    "angewandte chemie international edition": "1433-7851",
    "angew chem": "0044-8249",
    "chem rev": "0009-2665",
    "chemical reviews": "0009-2665",
    "chem soc rev": "0306-0012",
    "chemical society reviews": "0306-0012",
    "nat chem": "1476-1122",
    "nat chem biol": "1552-4450",
    "acs nano": "1936-0851",
    "nano lett": "1530-6984",
    "nano letters": "1530-6984",
    "acs cent sci": "2374-7943",
    "acs central science": "2374-7943",
    "adv mater": "0935-9648",
    "advanced materials": "0935-9648",
    "adv funct mater": "1616-301X",
    "advanced functional materials": "1616-301X",
    "adv energy mater": "1614-6832",
    "advanced energy materials": "1614-6832",
    "energy environ sci": "1754-5692",
    "energy & environmental science": "1754-5692",
    # ========== 生物学 ==========
    "cell": "0092-8674",
    "mol cell": "1097-2765",
    "nat cell biol": "1465-7392",
    "nat genet": "1061-4036",
    "nat immunol": "1529-2908",
    "genes dev": "0890-9369",
    "genes & development": "0890-9369",
    "genome res": "1088-9051",
    "genome research": "1088-9051",
    "genome biol": "1474-760X",
    "genome biology": "1474-760X",
    "nat biotechnol": "1087-0156",
    "nat methods": "1546-1696",
    "plos biol": "1544-9173",
    "plos biology": "1544-9173",
    "elife": "2050-084X",
    # ========== 医学 ==========
    "lancet": "0140-6736",
    "lancet oncol": "1470-2045",
    "lancet oncology": "1470-2045",
    "lancet neurol": "1474-4422",
    "lancet neurology": "1474-4422",
    "lancet psychiatry": "2215-0366",
    "lancet psychiatry": "2215-0366",
    "nat med": "1078-8956",
    "nat rev clin oncol": "1759-4774",
    "j clin oncol": "0732-183X",
    "journal of clinical oncology": "0732-183X",
    "j clin invest": "0021-9738",
    "journal of clinical investigation": "0021-9738",
    "j exp med": "0022-1007",
    "journal of experimental medicine": "0022-1007",
    "j immunol": "0022-1767",
    "journal of immunology": "0022-1767",
    # ========== 材料科学 ==========
    "nat mater": "1476-1121",
    "nat nanotechnol": "1748-3387",
    "adv mater": "0935-9648",
    "adv funct mater": "1616-301X",
    "acs nano": "1936-0851",
    "nano lett": "1530-6984",
    "nano today": "1748-0132",
    "nanoscale": "2040-3364",
    "small": "1613-6816",
    "chem mater": "0897-4756",
    "chemistry of materials": "0897-4756",
    "acs appl mater interf": "1944-8244",
    "acs applied materials & interfaces": "1944-8244",
    "adv energy mater": "1614-6832",
    "adv mater interfaces": "2196-7350",
    # ========== 物理学 ==========
    "nat phys": "1745-2473",
    "phys rev lett": "0031-9007",
    "physical review letters": "0031-9007",
    "phys rev x": "2160-3308",
    "physical review x": "2160-3308",
    "rev mod phys": "0034-6861",
    "reviews of modern physics": "0034-6861",
    "nat photonics": "1749-4885",
    "optica": "2334-2536",
    "opt express": "1094-4087",
    "optics express": "1094-4087",
    "light sci appl": "2047-7533",
    "light: science & applications": "2047-7533",
    # ========== 计算机科学 ==========
    "nature": "0028-0836",
    "science": "0036-8075",
    "acm comput surv": "0360-0300",
    "acm computing surveys": "0360-0300",
    "ieee trans pattern anal": "0162-8828",
    "ieee transactions on pattern analysis and machine intelligence": "0162-8828",
    "j mach learn res": "1532-4435",
    "journal of machine learning research": "1532-4435",
    "neurips": "1049-5258",
    "nips": "1049-5258",
    "icml": "0162-8828",
    "cvpr": "1063-6919",
    "iclr": "2640-3498",
    # ========== 其他顶刊 ==========
    "pnas": "0027-8424",
    "proceedings of the national academy of sciences": "0027-8424",
    "proc natl acad sci usa": "0027-8424",
    "nat rev drug discov": "1474-1776",
    "nat rev genet": "1471-0056",
    "nat rev immunol": "1474-1733",
    "nat rev mol cell biol": "1465-7392",
    "nat rev neurosci": "1471-003X",
    "nat rev chem": "2397-3358",
    "nat rev phys": "2524-4914",
    "nat rev mater": "2058-7546",
}

# ISSN → 规范期刊名映射（用于将各种名称统一为标准名）
ISSN_TO_CANONICAL = {
    "0028-0836": "Nature",
    "1546-1696": "Nat Methods",
    "1749-4885": "Nat Photonics",
    "1465-7392": "Nat Cell Biol",
    "1097-6256": "Nat Neurosci",
    "1087-0156": "Nat Biotechnol",
    "2041-1723": "Nat Commun",
    "1476-1122": "Nat Chem",
    "1745-2473": "Nat Phys",
    "1476-1121": "Nat Mater",
    "1078-8956": "Nat Med",
    "2157-846X": "Nat Biomed Eng",
    "1061-4036": "Nat Genet",
    "1529-2908": "Nat Immunol",
    "1545-9993": "Nat Struct Mol Biol",
    "1471-003X": "Nat Rev Neurosci",
    "1471-0056": "Nat Rev Genet",
    "1474-1733": "Nat Rev Immunol",
    "1474-1776": "Nat Rev Drug Discov",
    "2522-5804": "Nat Hum Behav",
    "2662-1355": "Nature Aging",
    "2662-1347": "Nature Cancer",
    "2522-5812": "Nat Metab",
    "2522-1094": "Nat Cardiovasc Res",
    "1552-4450": "Nat Chem Biol",
    "2397-3374": "Nat Ecol Evol",
    "2520-1131": "Nat Electron",
    "2058-7546": "Nat Energy",
    "1748-3387": "Nat Nanotechnol",
    "1754-2189": "Nat Protoc",
    "1759-4774": "Nat Rev Clin Oncol",
    "2397-3358": "Nat Rev Chem",
    "2524-4914": "Nat Rev Phys",
    "2058-7546": "Nat Rev Mater",
    "2662-8449": "Nat Rev Methods Primers",
    "0036-8075": "Science",
    "2375-2548": "Sci Adv",
    "1946-6234": "Sci Transl Med",
    "2470-2986": "Sci Immunol",
    "2470-9476": "Sci Robot",
    "1945-0877": "Sci Signal",
    "0092-8674": "Cell",
    "2211-1247": "Cell Rep",
    "1934-5909": "Cell Stem Cell",
    "1550-4131": "Cell Metab",
    "1097-2765": "Mol Cell",
    "1535-6108": "Cancer Cell",
    "0896-6273": "Neuron",
    "1074-7613": "Immunity",
    "1931-3128": "Cell Host Microbe",
    "2405-4712": "Cell Syst",
    "2451-9456": "Cell Chem Biol",
    "2666-3791": "Cell Rep Med",
    "2666-6836": "Cell Rep Phys Sci",
    "2666-979X": "Cell Genomics",
    "2589-0042": "iScience",
    "0140-6736": "The Lancet",
    "0028-4793": "N Engl J Med",
    "0098-7484": "JAMA",
    "0959-8138": "BMJ",
    "0003-4819": "Ann Intern Med",
    "0002-7863": "J Am Chem Soc",
    "1433-7851": "Angew Chem Int Ed",
    "0044-8249": "Angew Chem",
    "0009-2665": "Chem Rev",
    "0306-0012": "Chem Soc Rev",
    "1936-0851": "ACS Nano",
    "1530-6984": "Nano Lett",
    "2374-7943": "ACS Cent Sci",
    "0935-9648": "Adv Mater",
    "1616-301X": "Adv Funct Mater",
    "1614-6832": "Adv Energy Mater",
    "1754-5692": "Energy Environ Sci",
    "0890-9369": "Genes Dev",
    "1088-9051": "Genome Res",
    "1474-760X": "Genome Biol",
    "1544-9173": "PLoS Biol",
    "2050-084X": "eLife",
    "1470-2045": "Lancet Oncol",
    "1474-4422": "Lancet Neurol",
    "2215-0366": "Lancet Psychiatry",
    "0732-183X": "J Clin Oncol",
    "0021-9738": "J Clin Invest",
    "0022-1007": "J Exp Med",
    "0022-1767": "J Immunol",
    "1748-0132": "Nano Today",
    "2040-3364": "Nanoscale",
    "1613-6816": "Small",
    "0897-4756": "Chem Mater",
    "1944-8244": "ACS Appl Mater Interfaces",
    "2196-7350": "Adv Mater Interfaces",
    "0031-9007": "Phys Rev Lett",
    "2160-3308": "Phys Rev X",
    "0034-6861": "Rev Mod Phys",
    "2334-2536": "Optica",
    "1094-4087": "Opt Express",
    "2047-7533": "Light Sci Appl",
    "0360-0300": "ACM Comput Surv",
    "1049-5258": "NeurIPS",
    "1532-4435": "J Mach Learn Res",
    "1063-6919": "CVPR",
    "2640-3498": "ICLR",
    "0027-8424": "PNAS",
}

# 用户自定义期刊别名（运行时可扩展）
CUSTOM_JOURNAL_ALIASES = {}


# 期刊组定义：输入组名自动搜索该系列所有期刊
JOURNAL_GROUPS = {
    "nature": [
        "Nature",
        "Nat Methods",
        "Nat Photonics",
        "Nat Cell Biol",
        "Nat Neurosci",
        "Nat Biotechnol",
        "Nat Commun",
        "Nat Chem",
        "Nat Phys",
        "Nat Mater",
        "Nat Med",
        "Nat Biomed Eng",
        "Nat Genet",
        "Nat Immunol",
        "Nat Struct Mol Biol",
        "Nat Rev Mol Cell Biol",
        "Nat Rev Neurosci",
        "Nat Rev Genet",
        "Nat Rev Immunol",
        "Nat Rev Drug Discov",
        "Nat Hum Behav",
        "Nature Aging",
        "Nature Cancer",
        "Nat Metab",
        "Nat Cardiovasc Res",
        "Nat Chem Biol",
        "Nat Ecol Evol",
        "Nat Electron",
        "Nat Energy",
        "Nat Food",
        "Nat Nanotechnol",
        "Nat Protoc",
        "Nat Rev Clin Oncol",
        "Nat Rev Chem",
        "Nat Rev Phys",
        "Nat Rev Mater",
        "Nat Rev Methods Primers",
    ],
    "cell": [
        "Cell",
        "Cell Rep",
        "Cell Stem Cell",
        "Cell Metab",
        "Mol Cell",
        "Cancer Cell",
        "Neuron",
        "Immunity",
        "Cell Host Microbe",
        "Cell Syst",
        "Cell Chem Biol",
        "Cell Rep Med",
        "Cell Rep Phys Sci",
        "Cell Genomics",
        "iScience",
        "Chem",
        "Joule",
        "Matter",
        "One Earth",
        "Patterns",
    ],
    "science": [
        "Science",
        "Sci Adv",
        "Sci Transl Med",
        "Sci Immunol",
        "Sci Robot",
        "Sci Signal",
    ],
}


def _resolve_journal_issn(journal_name: str) -> Optional[str]:
    """将期刊名解析为 ISSN

    支持全称、缩写、各种变体。优先级：
    1. 用户自定义别名
    2. 标准别名映射
    3. ISSN 映射表
    4. 返回 None（回退到名称匹配）

    Args:
        journal_name: 期刊名（如 "Nature Methods"、"Nat Methods"）

    Returns:
        ISSN 字符串（如 "1546-1696"），未找到返回 None
    """
    if not journal_name:
        return None

    name_lower = journal_name.lower().strip()

    # 1. 用户自定义别名优先
    if name_lower in CUSTOM_JOURNAL_ALIASES:
        resolved = CUSTOM_JOURNAL_ALIASES[name_lower]
        # 如果解析结果是 ISSN 格式，直接返回
        if re.match(r"^\d{4}-\d{3}[\dX]$", resolved):
            return resolved
        # 否则递归解析
        return _resolve_journal_issn(resolved)

    # 2. 标准别名映射（缩写 → 规范名）
    canonical = JOURNAL_ALIASES.get(name_lower, journal_name)
    canonical_lower = canonical.lower()

    # 3. 从 ISSN 映射表查找
    issn = JOURNAL_ISSN.get(canonical_lower) or JOURNAL_ISSN.get(name_lower)
    if issn:
        return issn

    # 4. 直接匹配（可能是 ISSN 格式输入）
    if re.match(r"^\d{4}-\d{3}[\dX]$", name_lower):
        return name_lower

    return None


def _get_canonical_journal_name(journal_name: str) -> str:
    """获取期刊的规范名称

    Args:
        journal_name: 期刊名（任意变体）

    Returns:
        规范期刊名，未找到返回原名
    """
    if not journal_name:
        return journal_name

    name_lower = journal_name.lower().strip()

    # 1. 用户自定义别名
    if name_lower in CUSTOM_JOURNAL_ALIASES:
        resolved = CUSTOM_JOURNAL_ALIASES[name_lower]
        if re.match(r"^\d{4}-\d{3}[\dX]$", resolved):
            # ISSN 格式，反查规范名
            return ISSN_TO_CANONICAL.get(resolved, journal_name)
        return _get_canonical_journal_name(resolved)

    # 2. 标准别名映射
    canonical = JOURNAL_ALIASES.get(name_lower)
    if canonical:
        return canonical

    # 3. 通过 ISSN 反查
    issn = JOURNAL_ISSN.get(name_lower)
    if issn:
        return ISSN_TO_CANONICAL.get(issn, journal_name)

    return journal_name


def add_custom_journal_alias(alias: str, target: str):
    """添加用户自定义期刊别名

    Args:
        alias: 别名（如 "nat meth"）
        target: 目标期刊名或 ISSN（如 "Nature Methods" 或 "1546-1696"）
    """
    CUSTOM_JOURNAL_ALIASES[alias.lower().strip()] = target


def _clean_search_query(query: str) -> str:
    """清理搜索查询，去掉自然语言部分，只保留关键词

    Examples:
        "找一下周金华发表的论文" → "周金华"
        "搜索张伟教授的论文" → "张伟"
        "find papers by Jinhua Zhou" → "Jinhua Zhou"
        "search for CRISPR review" → "CRISPR review"
    """
    clean = query.strip()

    # 中文自然语言清理
    clean = re.sub(r"^(找一下?|搜索|查找|查询|检索)\s*", "", clean)
    clean = re.sub(
        r"\s*(发表的?论文|发表的?文章|的论文|的文章|论文|文章)\s*$", "", clean
    )
    clean = re.sub(r"\s*(教授|博士|老师|先生|女士)\s*", "", clean)

    # 英文自然语言清理
    clean = re.sub(
        r"^(find|search|look|get|show)\s+(for\s+|papers?\s+by\s+|articles?\s+by\s+|publications?\s+by\s+)",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(
        r"\s*(papers?|articles?|publications?|studies?|research)\s+(by|from|of|about|on|regarding)\s*$",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"\s*(Prof\.?|Dr\.?|Professor)\s*", "", clean, flags=re.IGNORECASE)

    clean = clean.strip()
    return clean if clean else query


def _convert_author_name_for_pubmed(name: str) -> str:
    """将作者名转换为 PubMed 标准格式 (LastName Initials)

    Examples:
        "Jinhua Zhou" → "Zhou JH"
        "Wei Zhang" → "Zhang W"
        "Jinhua" → "Jinhua" (单名不转换)
        "周金华教授" → "周金华" (移除职称后缀)
    """
    # 移除职称后缀
    suffixes = ["教授", "博士", "老师", "先生", "女士", "Prof.", "Dr.", "Professor"]
    clean_name = name.strip()
    for suffix in suffixes:
        if clean_name.endswith(suffix):
            clean_name = clean_name[: -len(suffix)].strip()

    # 如果是纯中文名（没有空格），直接返回（不转换）
    if " " not in clean_name and any("一" <= c <= "鿿" for c in clean_name):
        return clean_name

    parts = clean_name.split()
    if len(parts) >= 2:
        # 假设最后一部分是姓，前面的是名
        family_name = parts[-1]
        given_names = parts[:-1]
        # 生成首字母缩写
        initials = "".join(n[0].upper() for n in given_names if n)
        return f"{family_name} {initials}"
    return clean_name


def build_pubmed_query(
    keywords: str,
    journal: str = "",
    field: str = "",
    year_from: int = 0,
    year_to: int = 0,
    mesh_term: str = "",
    pub_type: str = "",
) -> str:
    """智能构建 PubMed 检索式

    Args:
        keywords: 用户输入的关键词（可含字段标签）
        journal: 期刊过滤（支持缩写或全名）
        field: 默认字段标签（ti/tiab/au/tw），当用户未指定时使用
        year_from: 起始年份
        year_to: 截止年份
        mesh_term: MeSH 主题词
        pub_type: 文献类型（review/clinical trial 等）
    """
    parts = []

    # 处理关键词
    kw = keywords.strip()
    if kw:
        # 如果用户已经写了字段标签（如 xxx[ti]），直接使用
        if re.search(r"\[(ti|tiab|au|ta|tw|mh|pt|pdat)\]", kw, re.IGNORECASE):
            parts.append(f"({kw})")
        elif field == "au":
            # 作者搜索：支持OR查询（如 "周金华 OR Jinhua Zhou"）
            if " OR " in kw.upper():
                # 分割OR查询，对每个部分单独转换
                or_parts = re.split(r"\s+OR\s+", kw, flags=re.IGNORECASE)
                au_parts = []
                for part in or_parts:
                    part = part.strip()
                    if part:
                        converted = _convert_author_name_for_pubmed(part)
                        au_parts.append(f"{converted}[au]")
                parts.append(f"({' OR '.join(au_parts)})")
            else:
                # 单个作者名
                converted = _convert_author_name_for_pubmed(kw)
                parts.append(f"({converted}[au])")
        elif field:
            # 用户指定了默认字段
            parts.append(f"({kw}[{field}])")
        else:
            # 智能判断：如果有引号或布尔运算符，当作高级查询
            if any(op in kw.upper() for op in [" AND ", " OR ", " NOT "]) or '"' in kw:
                parts.append(f"({kw})")
            else:
                # 默认在标题+摘要中搜索
                parts.append(f"({kw}[tiab])")

    # 期刊过滤（支持逗号分隔的多期刊）
    if journal:
        # 支持逗号分隔的多期刊
        journal_list = [j.strip() for j in journal.split(",") if j.strip()]
        journal_parts = []
        for j in journal_list:
            j_lower = j.lower()
            # 优先检查是否是期刊组名（如 "nature" → 搜索所有 Nature 系列）
            if j_lower in JOURNAL_GROUPS:
                group_journals = JOURNAL_GROUPS[j_lower]
                journal_parts.extend([f"{gj}[ta]" for gj in group_journals])
            else:
                # 单刊查询：检查是否是已知缩写
                canonical = JOURNAL_ALIASES.get(j_lower, j)
                journal_parts.append(f"{canonical}[ta]")
        if journal_parts:
            parts.append(f"({' OR '.join(journal_parts)})")

    # MeSH 主题词
    if mesh_term:
        parts.append(f"{mesh_term}[mh]")

    # 文献类型
    if pub_type:
        parts.append(f"{pub_type}[pt]")

    # 年份范围（0 表示不限制）
    if year_from and year_to:
        parts.append(f"{year_from}:{year_to}[pdat]")
    elif year_from:
        parts.append(f"{year_from}:{datetime.now().year}[pdat]")
    elif year_to:
        parts.append(f"1900:{year_to}[pdat]")

    return " AND ".join(parts) if parts else keywords


class PubMedSearch:
    BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(self, email="", api_key="", proxy=None):
        self.email = email
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "PaperLens/1.0"
        if proxy:
            self.session.proxies = proxy

    def search(
        self,
        query: str,
        year_from=2020,
        year_to=0,
        sort="relevance",
        max_results=50,
        journal="",
        field="",
        mesh_term="",
        pub_type="",
    ) -> tuple:
        """返回 (PMID 列表, 精确 DOI 或 None)

        Args:
            query: 检索词（可含 PubMed 字段标签）
            journal: 期刊过滤
            field: 默认字段标签
            mesh_term: MeSH 主题词
            pub_type: 文献类型
        """
        # 动态获取当前年份
        if not year_to:
            year_to = datetime.now().year

        # 检测是否是 DOI 查询
        exact_doi = None
        doi_match = re.match(r"^(10\.\d{4,}/\S+)$", query.strip())
        if doi_match:
            # 用 DOI[aid] 精确查询，后续需要过滤精确匹配
            term = f"{query.strip()}[aid]"
            exact_doi = query.strip().lower()
        else:
            # 构建检索式
            term = build_pubmed_query(
                keywords=query,
                journal=journal,
                field=field,
                year_from=year_from,
                year_to=year_to,
                mesh_term=mesh_term,
                pub_type=pub_type,
            )

        if not term:
            return [], exact_doi

        # 映射排序参数
        sort_map = {
            "relevance": "relevance",
            "date": "pub+date",
            "citations": "relevance",  # PubMed 无引用排序，回退到相关度
        }

        params = {
            "db": "pubmed",
            "term": term,
            "retmax": max_results,
            "sort": sort_map.get(sort, "relevance"),
            "retmode": "json",
        }
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key

        try:
            # 带重试的请求（应对 PubMed 限流）
            r = None
            for attempt in range(3):
                r = self.session.get(
                    f"{self.BASE}/esearch.fcgi", params=params, timeout=20
                )
                if r.status_code == 429:
                    wait = min(2**attempt, 5)
                    print(
                        f"PubMed rate limited, waiting {wait}s (attempt {attempt + 1}/3)"
                    )
                    time.sleep(wait)
                    continue
                break
            r.raise_for_status()
            data = r.json()
            return data.get("esearchresult", {}).get("idlist", []), exact_doi
        except Exception as e:
            print(f"PubMed search error: {e}")
            return [], exact_doi

    def fetch_details(self, pmids: list[str]) -> list:
        """批量获取文献详情"""
        if not pmids:
            return []

        papers = []
        for i in range(0, len(pmids), 100):
            batch = pmids[i : i + 100]
            params = {
                "db": "pubmed",
                "id": ",".join(batch),
                "retmode": "xml",
            }
            if self.email:
                params["email"] = self.email
            if self.api_key:
                params["api_key"] = self.api_key

            try:
                # 带重试的请求
                r = None
                for attempt in range(3):
                    r = self.session.get(
                        f"{self.BASE}/efetch.fcgi", params=params, timeout=30
                    )
                    if r.status_code == 429:
                        wait = min(2**attempt, 5)
                        print(f"PubMed rate limited (fetch), waiting {wait}s")
                        time.sleep(wait)
                        continue
                    break
                r.raise_for_status()
                papers.extend(self._parse_xml(r.text))
            except Exception as e:
                print(f"PubMed fetch error: {e}")

            if i + 100 < len(pmids):
                time.sleep(0.5)

        return papers

    def _parse_xml(self, xml_text: str) -> list:
        papers = []
        try:
            # 使用安全的 XML 解析器，禁用外部实体
            try:
                parser = ET.XMLParser(resolve_entities=False)
            except TypeError:
                # 某些 Python 版本不支持 resolve_entities 参数
                parser = ET.XMLParser()
            root = ET.fromstring(xml_text, parser=parser)
        except ET.ParseError:
            return papers

        for article in root.findall(".//PubmedArticle"):
            p = Paper(source="pubmed")

            pmid_el = article.find(".//PMID")
            if pmid_el is not None:
                p.pmid = pmid_el.text or ""

            title_el = article.find(".//ArticleTitle")
            if title_el is not None:
                p.title = self._get_text(title_el)

            for author in article.findall(".//Author"):
                last = author.find("LastName")
                first = author.find("ForeName")
                if last is not None and last.text:
                    name = last.text
                    if first is not None and first.text:
                        name += f", {first.text}"
                    p.authors.append(name)

            # 提取机构信息
            for aff_info in article.findall(".//AffiliationInfo"):
                aff_el = aff_info.find("Affiliation")
                if aff_el is not None and aff_el.text:
                    aff_text = aff_el.text.strip()
                    if aff_text and aff_text not in p.affiliations:
                        p.affiliations.append(aff_text)

            journal_el = article.find(".//Journal/Title")
            if journal_el is not None:
                p.journal = journal_el.text or ""

            year_el = article.find(".//PubDate/Year")
            if year_el is not None and year_el.text:
                try:
                    p.year = int(year_el.text)
                except ValueError:
                    pass
            # 回退到 MedlineDate 提取年份
            if not p.year:
                medline_date_el = article.find(".//PubDate/MedlineDate")
                if medline_date_el is not None and medline_date_el.text:
                    try:
                        p.year = int(medline_date_el.text[:4])
                    except (ValueError, IndexError):
                        pass

            for aid in article.findall(".//ArticleId"):
                if aid.get("IdType") == "doi":
                    p.doi = aid.text or ""

            # 提取卷号、期号、页码
            volume_el = article.find(".//JournalIssue/Volume")
            if volume_el is not None and volume_el.text:
                p.volume = volume_el.text.strip()
            issue_el = article.find(".//JournalIssue/Issue")
            if issue_el is not None and issue_el.text:
                p.issue = issue_el.text.strip()
            # 页码：尝试 Pagination/StartPage-EndPage 或 MedlinePgn
            pagination_el = article.find(".//Pagination")
            if pagination_el is not None:
                start_page = pagination_el.find("StartPage")
                end_page = pagination_el.find("EndPage")
                if start_page is not None and start_page.text:
                    p.pages = start_page.text.strip()
                    if end_page is not None and end_page.text:
                        p.pages += f"-{end_page.text.strip()}"
            if not p.pages:
                medline_pgn = article.find(".//MedlinePgn")
                if medline_pgn is not None and medline_pgn.text:
                    p.pages = medline_pgn.text.strip()
            # ISSN
            issn_el = article.find(".//ISSN")
            if issn_el is not None and issn_el.text:
                p.issn = issn_el.text.strip()

            abstract_el = article.find(".//Abstract")
            if abstract_el is not None:
                parts = []
                for text_el in abstract_el.findall("AbstractText"):
                    label = text_el.get("Label", "")
                    text = self._get_text(text_el)
                    if label:
                        parts.append(f"{label}: {text}")
                    else:
                        parts.append(text)
                p.abstract = " ".join(parts)

            for kw in article.findall(".//Keyword"):
                if kw.text:
                    p.keywords.append(kw.text)

            papers.append(p)

        return papers

    def _get_text(self, el) -> str:
        return "".join(el.itertext()).strip()


class OpenAlexSearch:
    BASE = "https://api.openalex.org"

    def __init__(self, email="", api_key="", proxy=None):
        self.email = email
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "PaperLens/1.0"
        self._last_keywords = set()
        if proxy:
            self.session.proxies = proxy

    def _find_author_id(self, author_name: str) -> list:
        """通过 OpenAlex Authors API 精确搜索作者，返回作者 ID 列表

        Args:
            author_name: 作者名（支持中文名、英文名、缩写、OR 查询等格式）

        Returns:
            作者 ID 列表（如 ["A1234567890", "A0987654321"]）
        """
        if not author_name:
            return []

        # 清理作者名：移除职称后缀
        suffixes = ["教授", "博士", "老师", "先生", "女士", "Prof.", "Dr.", "Professor"]
        clean_name = author_name.strip()
        for suffix in suffixes:
            if clean_name.endswith(suffix):
                clean_name = clean_name[: -len(suffix)].strip()

        if not clean_name:
            return []

        # 处理 OR 查询：如 "周金华 OR Jinhua Zhou"
        # 分割 OR 查询，对每个部分单独搜索，合并结果
        if " OR " in clean_name.upper():
            or_parts = re.split(r"\s+OR\s+", clean_name, flags=re.IGNORECASE)
            all_author_ids = []
            for part in or_parts:
                part = part.strip()
                if part:
                    ids = self._find_author_id_single(part)
                    all_author_ids.extend(ids)
            # 去重并返回
            seen = set()
            unique_ids = []
            for aid in all_author_ids:
                if aid not in seen:
                    seen.add(aid)
                    unique_ids.append(aid)
            return unique_ids[:5]  # 最多返回 5 个作者 ID

        return self._find_author_id_single(clean_name)

    def _find_author_id_single(self, author_name: str) -> list:
        """搜索单个作者名的作者 ID

        Args:
            author_name: 单个作者名

        Returns:
            作者 ID 列表
        """
        if not author_name:
            return []

        # 构建搜索参数：使用 display_name.search 进行模糊匹配
        params = {
            "filter": f"display_name.search:{author_name}",
            "per_page": 10,  # 返回前 10 个最匹配的结果
            "select": "id,display_name,works_count",
        }
        if self.email:
            params["mailto"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key

        try:
            # 带重试的请求
            r = None
            for attempt in range(3):
                r = self.session.get(f"{self.BASE}/authors", params=params, timeout=10)
                if r.status_code == 429:
                    wait = min(2**attempt * 2, 10)
                    print(f"OpenAlex rate limited (authors), waiting {wait}s")
                    time.sleep(wait)
                    continue
                break
            r.raise_for_status()
            data = r.json()

            # 提取作者 ID，按相关性排序（works_count 越高越可能是目标作者）
            authors = []
            for author in data.get("results", []):
                author_id = author.get("id", "")
                if author_id:
                    # 从 URL 中提取纯 ID（如 https://openalex.org/A1234567890 → A1234567890）
                    if "/" in author_id:
                        author_id = author_id.split("/")[-1]
                    authors.append(
                        {
                            "id": author_id,
                            "name": author.get("display_name", ""),
                            "works_count": author.get("works_count", 0),
                        }
                    )

            # 按 works_count 降序排序（更活跃的作者更可能是目标）
            authors.sort(key=lambda x: x["works_count"], reverse=True)

            # 返回前 3 个最匹配的作者 ID
            return [a["id"] for a in authors[:3]]

        except Exception as e:
            print(f"OpenAlex author search error: {e}")
            return []

    def search(
        self,
        query: str,
        year_from=2020,
        year_to=0,
        max_results=50,
        journal="",
        field="",
    ) -> list:
        """OpenAlex 检索"""
        # 动态获取当前年份
        if not year_to:
            year_to = datetime.now().year

        # 检测 DOI 查询，使用专用端点
        doi_match = re.match(r"^(10\.\d{4,}/\S+)$", query.strip())
        if doi_match:
            return self._search_by_doi(query.strip())

        # 清理 PubMed 字段标签，OpenAlex 不识别
        clean_query = re.sub(
            r"\[(?:ti|tiab|au|ta|tw|mh|pt|pdat)\]", "", query, flags=re.IGNORECASE
        )
        # 清理布尔运算符中的多余空格
        clean_query = re.sub(r"\s+", " ", clean_query).strip()
        # 去掉年份过滤（OpenAlex 用 filter 参数处理）
        clean_query = re.sub(r"\d{4}:\d{4}\[pdat\]", "", clean_query).strip()
        # 去掉末尾的 AND/OR
        clean_query = re.sub(
            r"\s+(AND|OR|NOT)\s*$", "", clean_query, flags=re.IGNORECASE
        ).strip()

        if not clean_query:
            return []

        # [Fix] 提取核心关键词：先按布尔运算符分割，再按空格分割
        # 之前只按 AND/OR/NOT 分割，导致 "2D fullerene electrocatalysis" 被当作一个关键词
        self._last_keywords = set()
        # 先按布尔运算符分割
        bool_parts = re.split(r"\s+(?:AND|OR|NOT)\s+", clean_query, flags=re.IGNORECASE)
        for part in bool_parts:
            # 再按空格分割每个部分
            for word in re.split(r"\s+", part):
                word = word.strip("()\"' ")
                # [Fix] 允许2字符的含数字关键词（如"2D"），过滤短停用词
                if (
                    len(word) > 2 or (len(word) == 2 and any(c.isdigit() for c in word))
                ) and word.lower() not in ("and", "or", "not", "the", "for", "with"):
                    self._last_keywords.add(word.lower())

        # 构建过滤条件
        filter_parts = []
        # [Fix #12] 与 PubMed 行为一致：year_from=0 时使用 1800 作为默认起始年
        effective_year_from = year_from if year_from else 1800
        if year_from or year_to:
            filter_parts.append(
                f"publication_year:{effective_year_from}-{year_to or datetime.now().year}"
            )
        if journal:
            # 逗号分隔的期刊名需要逐个检查是否为期刊组，再用 | 连接（OpenAlex OR 语法）
            journal_names = [j.strip() for j in journal.split(",") if j.strip()]
            all_journals = []
            for jn in journal_names:
                jn_lower = jn.lower()
                if jn_lower in JOURNAL_GROUPS:
                    all_journals.extend(JOURNAL_GROUPS[jn_lower])
                else:
                    all_journals.append(jn)
            # 分批处理期刊过滤器，限制总长度避免 URL 过长导致 400/414
            # 最多取前 20 个期刊名，超出则直接丢弃期刊过滤（宁可多搜不少搜）
            MAX_JOURNAL_FILTER = 20
            if len(all_journals) > MAX_JOURNAL_FILTER:
                print(
                    f"[OpenAlex] Journal filter too long ({len(all_journals)} names), truncating to first {MAX_JOURNAL_FILTER}"
                )
                all_journals = all_journals[:MAX_JOURNAL_FILTER]
            if len(all_journals) > 10:
                journal_batches = [
                    all_journals[i : i + 10] for i in range(0, len(all_journals), 10)
                ]
                journal_filters = [
                    f"primary_location.source.display_name:{'|'.join(batch)}"
                    for batch in journal_batches
                ]
                filter_parts.append(f"({'|'.join(journal_filters)})")
            elif all_journals:
                filter_parts.append(
                    f"primary_location.source.display_name:{'|'.join(all_journals)}"
                )

        params = {
            "filter": ",".join(filter_parts) if filter_parts else "",
            "per_page": min(max_results * 2, 200),  # 多取一些，后续过滤
            "sort": "relevance_score:desc",
        }
        # 根据搜索类型选择过滤器
        if field == "au" and clean_query:
            # 作者搜索：先通过 Authors API 精确查找作者 ID，再用 ID 过滤论文
            author_ids = self._find_author_id(clean_query)
            if author_ids:
                # 使用 authorships.author.id 精确匹配（OR 逻辑）
                author_filter = f"authorships.author.id:{'|'.join(author_ids)}"
                print(
                    f"[OpenAlex] Author search: found {len(author_ids)} author IDs for '{clean_query}'"
                )
            else:
                # 回退到模糊搜索
                author_filter = f"authorships.author.display_name.search:{clean_query}"
                print(
                    f"[OpenAlex] Author search: no exact match, using fuzzy search for '{clean_query}'"
                )
            if params["filter"]:
                params["filter"] += f",{author_filter}"
            else:
                params["filter"] = author_filter
        elif field == "ti" and clean_query:
            # 仅标题搜索
            title_filter = f"title.search:{clean_query}"
            if params["filter"]:
                params["filter"] += f",{title_filter}"
            else:
                params["filter"] = title_filter
        elif clean_query:
            # 标题+摘要搜索代替全文搜索，提升结果相关性
            title_filter = f"title.search:{clean_query}"
            abstract_filter = f"abstract.search:{clean_query}"
            if params["filter"]:
                params["filter"] += f",{title_filter},{abstract_filter}"
            else:
                params["filter"] = f"{title_filter},{abstract_filter}"
        if self.email:
            params["mailto"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key

        try:
            # 带重试的请求（应对 OpenAlex 限流 429）
            r = None
            for attempt in range(3):
                r = self.session.get(f"{self.BASE}/works", params=params, timeout=15)
                if r.status_code == 429:
                    # 限流，等待后重试
                    wait = min(2**attempt * 2, 10)  # 2s, 4s, 8s
                    print(
                        f"OpenAlex rate limited, waiting {wait}s (attempt {attempt + 1}/3)"
                    )
                    time.sleep(wait)
                    continue
                break
            r.raise_for_status()
            data = r.json()
            results = self._parse_results(data.get("results", []))

            # 作者搜索时跳过相关性过滤（作者名通常不在标题/摘要中）
            if field == "au":
                return results[:max_results]

            # 基本相关性过滤：标题或摘要包含搜索关键词
            keywords = getattr(self, "_last_keywords", set())
            if keywords and len(keywords) >= 2:
                # 2+ 关键词时过滤，提升短查询精度
                filtered = []
                for p in results:
                    title_lower = p.title.lower()
                    abstract_lower = (p.abstract or "").lower()
                    # 标题包含任意关键词，或摘要包含 ≥1 个关键词
                    title_match = any(
                        re.search(r"\b" + re.escape(kw) + r"\b", title_lower)
                        for kw in keywords
                    )
                    abstract_match = (
                        sum(
                            1
                            for kw in keywords
                            if re.search(r"\b" + re.escape(kw) + r"\b", abstract_lower)
                        )
                        >= 1
                    )
                    if title_match or abstract_match:
                        filtered.append(p)
                # 如果过滤后结果太少，回退到原始结果
                if len(filtered) >= 3:
                    return filtered[:max_results]
            return results[:max_results]
        except Exception as e:
            print(f"OpenAlex search error: {e}")
            return []

    def enrich_with_citations(self, papers: list) -> list:
        """用 OpenAlex 补充引用次数和 OA 链接（并发执行）"""
        papers_with_doi = [p for p in papers if p.doi]
        if not papers_with_doi:
            return papers

        # 分批查询（每批最多 25 个，避免 URL 过长）
        batches = [
            papers_with_doi[i : i + 25] for i in range(0, len(papers_with_doi), 25)
        ]

        def fetch_batch(batch):
            """查询单个批次的引用数据"""
            doi_values = "|".join([p.doi for p in batch])
            doi_filter = f"doi:{doi_values}"
            params = {
                "filter": doi_filter,
                "per_page": 50,
            }
            if self.email:
                params["mailto"] = self.email
            if self.api_key:
                params["api_key"] = self.api_key

            # 带重试的请求（应对 OpenAlex 限流 429）
            r = None
            for attempt in range(3):
                r = self.session.get(f"{self.BASE}/works", params=params, timeout=15)
                if r.status_code == 429:
                    wait = min(2**attempt * 2, 10)
                    print(f"OpenAlex rate limited (enrich), waiting {wait}s")
                    time.sleep(wait)
                    continue
                break
            r.raise_for_status()
            return r.json()

        # 并发执行所有批次
        with ThreadPoolExecutor(max_workers=min(len(batches), 4)) as executor:
            future_to_batch = {
                executor.submit(fetch_batch, batch): batch for batch in batches
            }
            for future in as_completed(future_to_batch):
                batch = future_to_batch[future]
                try:
                    data = future.result()
                    # 构建 DOI → OpenAlex 结果的映射
                    doi_map = {}
                    for w in data.get("results", []):
                        oa_doi = (
                            (w.get("doi", "") or "")
                            .replace("https://doi.org/", "")
                            .lower()
                        )
                        if oa_doi:
                            doi_map[oa_doi] = w

                    # 精确匹配补充信息：仅在 OpenAlex 有有效数据时更新
                    for p in batch:
                        doi_key = p.doi.lower()
                        if doi_key in doi_map:
                            w = doi_map[doi_key]
                            oa_citations = w.get("cited_by_count", 0)
                            if oa_citations > 0:
                                p.citation_count = oa_citations
                            if not p.oa_url:
                                oa = w.get("open_access", {})
                                p.oa_url = oa.get("oa_url", "") or ""
                except Exception as e:
                    print(f"OpenAlex enrich error: {e}")

        return papers

    @staticmethod
    def _sanitize_text(text: str) -> str:
        """清理文本：去除 HTML 标签和无效占位符"""
        if not text:
            return ""
        # 去掉 HTML 标签
        clean = re.sub(r"<[^>]+>", "", text)
        clean = clean.strip()
        # 过滤无效占位符（OpenAlex 部分论文标题为 "[Not Available]"）
        if clean.lower() in ("[not available]", "not available", "n/a", "null", "none"):
            return ""
        return clean

    def _parse_results(self, results) -> list:
        papers = []
        for w in results:
            p = Paper(source="openalex", sources=["openalex"])
            p.title = self._sanitize_text(w.get("title", "") or "")
            loc = w.get("primary_location") or {}
            src = loc.get("source") or {}
            p.journal = src.get("display_name", "") or ""
            p.year = w.get("publication_year", 0) or 0
            p.doi = (w.get("doi", "") or "").replace("https://doi.org/", "")
            p.citation_count = w.get("cited_by_count", 0)

            # 提取卷号、期号、页码
            biblio = w.get("biblio") or {}
            p.volume = str(biblio.get("volume", "") or "")
            p.issue = str(biblio.get("issue", "") or "")
            first_page = str(biblio.get("first_page", "") or "")
            last_page = str(biblio.get("last_page", "") or "")
            if first_page:
                p.pages = (
                    first_page
                    if not last_page or first_page == last_page
                    else f"{first_page}-{last_page}"
                )
            # ISSN（OpenAlex 可能返回列表，取第一个）
            issn_raw = src.get("issn", "") or ""
            if isinstance(issn_raw, list):
                p.issn = issn_raw[0] if issn_raw else ""
            else:
                p.issn = str(issn_raw)

            # OpenAlex 摘要是反转索引格式，需要重建
            abstract_inv = w.get("abstract_inverted_index")
            if abstract_inv:
                p.abstract = self._reconstruct_abstract(abstract_inv)

            for author in w.get("authorships", []):
                name = author.get("author", {}).get("display_name", "")
                if name:
                    p.authors.append(name)
                # 提取通讯作者 ORCID
                if not p.orcid:
                    orcid = author.get("author", {}).get("orcid", "") or ""
                    if orcid:
                        p.orcid = orcid.replace("https://orcid.org/", "")
                # 提取机构信息
                for inst in author.get("institutions", []):
                    inst_name = inst.get("display_name", "") or ""
                    if inst_name and inst_name not in p.affiliations:
                        p.affiliations.append(inst_name)

            oa = w.get("open_access", {})
            p.oa_url = oa.get("oa_url", "") or ""

            # 关键词
            for kw in w.get("keywords", []):
                k = kw.get("display_name", "") if isinstance(kw, dict) else str(kw)
                if k:
                    p.keywords.append(k)

            # Phase 5a: 文章类型
            p.article_type = w.get("type", "") or ""

            # Phase 5a: 会议名称（从 locations 中提取 proceedings 来源）
            for loc_item in w.get("locations", []):
                loc_src = loc_item.get("source") or {}
                src_type = loc_src.get("type", "")
                if src_type == "proceedings":
                    conf = loc_src.get("display_name", "") or ""
                    if conf:
                        p.conference = conf
                        break

            # Phase 5a: 资助信息
            for fg in w.get("funder_grants", []):
                funder = fg.get("funder", {}) or {}
                fname = funder.get("display_name", "") or ""
                if fname and fname not in p.funding:
                    p.funding.append(fname)

            papers.append(p)
        return papers

    @staticmethod
    def _reconstruct_abstract(inverted_index: dict) -> str:
        """从 OpenAlex 反转索引重建摘要文本"""
        if not inverted_index:
            return ""
        try:
            word_positions = []
            for word, positions in inverted_index.items():
                for pos in positions:
                    word_positions.append((pos, word))
            word_positions.sort(key=lambda x: x[0])
            return " ".join(w for _, w in word_positions)
        except Exception:
            return ""

    def _search_by_doi(self, doi: str) -> list:
        """通过 DOI 精确查询 OpenAlex"""
        try:
            params = {}
            if self.email:
                params["mailto"] = self.email
            if self.api_key:
                params["api_key"] = self.api_key
            r = self.session.get(
                f"{self.BASE}/works/doi:{doi}", params=params, timeout=10
            )
            if r.status_code == 200:
                w = r.json()
                p = Paper(source="openalex", sources=["openalex"])
                p.title = self._sanitize_text(w.get("title", "") or "")
                loc = w.get("primary_location") or {}
                src = loc.get("source") or {}
                p.journal = src.get("display_name", "") or ""
                p.year = w.get("publication_year", 0) or 0
                p.doi = (w.get("doi", "") or "").replace("https://doi.org/", "")
                p.citation_count = w.get("cited_by_count", 0)
                # 提取卷号、期号、页码
                biblio = w.get("biblio") or {}
                p.volume = str(biblio.get("volume", "") or "")
                p.issue = str(biblio.get("issue", "") or "")
                first_page = str(biblio.get("first_page", "") or "")
                last_page = str(biblio.get("last_page", "") or "")
                if first_page:
                    p.pages = (
                        first_page
                        if not last_page or first_page == last_page
                        else f"{first_page}-{last_page}"
                    )
                # ISSN（OpenAlex 可能返回列表，取第一个）
                issn_raw = src.get("issn", "") or ""
                if isinstance(issn_raw, list):
                    p.issn = issn_raw[0] if issn_raw else ""
                else:
                    p.issn = str(issn_raw)
                abstract_inv = w.get("abstract_inverted_index")
                if abstract_inv:
                    p.abstract = self._reconstruct_abstract(abstract_inv)
                for author in w.get("authorships", []):
                    name = author.get("author", {}).get("display_name", "")
                    if name:
                        p.authors.append(name)
                    # 提取通讯作者 ORCID
                    if not p.orcid:
                        orcid = author.get("author", {}).get("orcid", "") or ""
                        if orcid:
                            p.orcid = orcid.replace("https://orcid.org/", "")
                oa = w.get("open_access", {})
                p.oa_url = oa.get("oa_url", "") or ""
                for kw in w.get("keywords", []):
                    if isinstance(kw, dict):
                        kw = kw.get("display_name", "")
                    if isinstance(kw, str) and kw:
                        p.keywords.append(kw)
                # Phase 5a: 文章类型
                p.article_type = w.get("type", "") or ""
                # Phase 5a: 会议名称
                for loc_item in w.get("locations", []):
                    loc_src = loc_item.get("source") or {}
                    if loc_src.get("type", "") == "proceedings":
                        conf = loc_src.get("display_name", "") or ""
                        if conf:
                            p.conference = conf
                            break
                # Phase 5a: 资助信息
                for fg in w.get("funder_grants", []):
                    funder = fg.get("funder", {}) or {}
                    fname = funder.get("display_name", "") or ""
                    if fname and fname not in p.funding:
                        p.funding.append(fname)
                return [p]
        except Exception as e:
            print(f"OpenAlex DOI search error: {e}")
        return []


class GoogleScholarSearch:
    """Google Scholar 搜索（实验性，依赖 scholarly 库）"""

    def __init__(self, proxy=None):
        self.proxy = proxy
        self._available = None

    def _check_available(self):
        if self._available is None:
            try:
                import scholarly

                self._available = True
            except ImportError:
                self._available = False
                print(
                    "Google Scholar: scholarly 库未安装，请运行 pip install scholarly"
                )
        return self._available

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=20, field=""
    ) -> list:
        if not self._check_available():
            return []

        # 动态获取当前年份
        if not year_to:
            year_to = datetime.now().year

        try:
            from scholarly import scholarly as sch

            sch.set_timeout(30)
            # 设置代理（scholarly 支持免费代理）
            if self.proxy:
                proxy_url = self.proxy.get("https") or self.proxy.get("http")
                if proxy_url:
                    try:
                        sch.use_proxy(proxies={"http": proxy_url, "https": proxy_url})
                    except Exception:
                        pass  # scholarly 版本可能不支持 use_proxy
            results = []

            # 作者搜索：使用 search_author 方法
            if field == "au":
                search_query = sch.search_author(query)
                for i, author in enumerate(search_query):
                    if i >= max_results:
                        break
                    # 获取作者的论文
                    author.fill()
                    for pub in author.get("publications", []):
                        if len(results) >= max_results:
                            break
                        p = Paper(source="google_scholar")
                        bib = pub.get("bib", {})
                        p.title = bib.get("title", "")
                        raw_authors = bib.get("author", [])
                        if isinstance(raw_authors, list):
                            p.authors = [a for a in raw_authors if a]
                        elif raw_authors:
                            p.authors = [raw_authors]
                        else:
                            p.authors = []
                        p.journal = bib.get("venue", "")
                        p.year = (
                            int(bib.get("pub_year", 0)) if bib.get("pub_year") else 0
                        )
                        p.abstract = bib.get("abstract", "")
                        p.doi = pub.get("doi", "") or ""
                        # 卷/期/页码
                        vol = bib.get("volume", "")
                        if vol:
                            p.volume = str(vol)
                        iss = bib.get("number", "")
                        if iss:
                            p.issue = str(iss)
                        pg = bib.get("pages", "")
                        if pg:
                            p.pages = str(pg)
                        # Google Scholar 引用数
                        p.citation_count = pub.get("num_citations", 0) or 0
                        p.oa_url = pub.get("eprint_url", "") or ""
                        results.append(p)
            else:
                search_query = sch.search_pubs(
                    query, year_low=year_from, year_high=year_to
                )
                for i, result in enumerate(search_query):
                    if i >= max_results:
                        break
                    p = Paper(source="google_scholar")
                    bib = result.get("bib", {})
                    p.title = bib.get("title", "")
                    raw_authors = bib.get("author", [])
                    if isinstance(raw_authors, list):
                        p.authors = [a for a in raw_authors if a]
                    elif raw_authors:
                        p.authors = [raw_authors]
                    else:
                        p.authors = []
                    p.journal = bib.get("venue", "")
                    p.year = int(bib.get("pub_year", 0)) if bib.get("pub_year") else 0
                    p.abstract = bib.get("abstract", "")
                    p.doi = result.get("doi", "") or ""
                    # 卷/期/页码
                    vol = bib.get("volume", "")
                    if vol:
                        p.volume = str(vol)
                    iss = bib.get("number", "")
                    if iss:
                        p.issue = str(iss)
                    pg = bib.get("pages", "")
                    if pg:
                        p.pages = str(pg)
                    # Google Scholar 引用数
                    p.citation_count = result.get("num_citations", 0) or 0
                    p.oa_url = result.get("eprint_url", "") or ""
                    results.append(p)
            return results
        except Exception as e:
            print(f"Google Scholar search error: {e}")
            return []


class PlaywrightBrowser:
    """Playwright 浏览器管理器（单例，用于需要 JavaScript 渲染的网站）"""

    _instance = None
    _browser = None
    _playwright = None
    _proxy = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, proxy=None):
        with cls._lock:
            # 代理变化时，关闭旧浏览器，用新代理重建
            if cls._instance is not None and proxy != cls._proxy:
                cls._close_browser()
                cls._proxy = proxy
            if cls._instance is None:
                cls._instance = cls()
                cls._proxy = proxy
        return cls._instance

    @classmethod
    def _close_browser(cls):
        """关闭浏览器和 Playwright（调用前需持有锁）"""
        if cls._browser:
            try:
                cls._browser.close()
            except Exception:
                pass
            cls._browser = None
        if cls._playwright:
            try:
                cls._playwright.stop()
            except Exception:
                pass
            cls._playwright = None

    def get_browser(self):
        # [Fix #4] 双重检查锁定：外层无锁快速路径，内层持锁初始化
        # CPython GIL 保证属性读写原子性，外层检查是安全的优化
        browser = PlaywrightBrowser._browser
        if browser is None or not browser.is_connected():
            with PlaywrightBrowser._lock:
                if (
                    PlaywrightBrowser._browser is None
                    or not PlaywrightBrowser._browser.is_connected()
                ):
                    self._init_browser()
        return PlaywrightBrowser._browser

    @staticmethod
    def _setup_playwright_path():
        """自动检测并设置 Playwright 浏览器路径（委托 shared 实现）"""
        from access_proxy import _setup_playwright_browsers_path

        _setup_playwright_browsers_path()

    @staticmethod
    def _detect_headless():
        """检测是否应使用 headless 模式

        优先级：
        1. 环境变量 PAPERLENS_HEADLESS=1 强制 headless
        2. Windows/macOS 默认非 headless（有显示器）
        3. Linux 检查 DISPLAY/WAYLAND_DISPLAY 环境变量
        """
        import os

        env_headless = os.environ.get("PAPERLENS_HEADLESS", "").strip()
        if env_headless == "1":
            return True
        if sys.platform in ("win32", "darwin"):
            return False
        return not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")

    def _init_browser(self):
        try:
            # 自动检测 Playwright 浏览器路径
            self._setup_playwright_path()

            from playwright.sync_api import sync_playwright

            if PlaywrightBrowser._playwright is None:
                PlaywrightBrowser._playwright = sync_playwright().start()
            launch_args = {
                "headless": PlaywrightBrowser._detect_headless(),
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            # 代理：Playwright launch 接受 server.proxy 格式
            proxy = PlaywrightBrowser._proxy
            if proxy:
                proxy_url = proxy.get("https") or proxy.get("http")
                if proxy_url:
                    launch_args["proxy"] = {"server": proxy_url}
                    print(f"Playwright browser using proxy: {proxy_url}")
            # 优先使用已安装的 Chrome，回退到 bundled Chromium
            try:
                PlaywrightBrowser._browser = (
                    PlaywrightBrowser._playwright.chromium.launch(
                        channel="chrome", **launch_args
                    )
                )
                print("Playwright browser initialized (Chrome)")
            except Exception:
                PlaywrightBrowser._browser = (
                    PlaywrightBrowser._playwright.chromium.launch(**launch_args)
                )
                print("Playwright browser initialized (Chromium)")
        except Exception as e:
            print(f"Playwright init error: {e}")
            PlaywrightBrowser._browser = None

    def new_page(self):
        browser = self.get_browser()
        if browser is None:
            return None
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
            )
            page = context.new_page()
            return page
        except Exception as e:
            print(f"Playwright new page error: {e}")
            return None

    def close(self):
        with PlaywrightBrowser._lock:
            PlaywrightBrowser._close_browser()


class CNKISearch:
    """中国知网搜索（Playwright 浏览器模式）

    CNKI 有严格的反爬机制（验证码 + 行为检测），直接 API 调用会被拦截。
    使用 Playwright 复用浏览器实例，保持会话状态，减少重复验证。
    """

    BASE = "https://kns.cnki.net"
    # 持久化浏览器实例（线程安全，可跨线程共享）
    _browser_instance = None
    _playwright_instance = None
    _browser_lock = threading.RLock()

    def __init__(self, proxy=None, access_proxy=None, cookies=None):
        self.proxy = proxy
        self.access_proxy = access_proxy
        self.cookies = cookies
        # CARSI cookies 有效期检查缓存（避免每次搜索都发起 HTTP 请求）
        self._cookies_last_checked = 0  # 上次检查的时间戳
        self._cookies_valid = None  # None=未检查, True=有效, False=过期
        self._COOKIE_CHECK_INTERVAL = 600  # 检查间隔：10 分钟

    def _get_or_create_browser(self):
        """获取或创建持久化浏览器实例

        返回共享的 Browser 实例。Browser 本身是线程安全的，
        但 BrowserContext 不是——每个搜索应通过 _create_context() 创建独立 context。
        注意：调用方必须持有 _browser_lock（browser.contexts 等操作不是线程安全的）。
        """
        try:
            from playwright.sync_api import sync_playwright
            from access_proxy import _setup_playwright_browsers_path

            _setup_playwright_browsers_path()
        except ImportError:
            print("CNKI: Playwright 未安装")
            return None

        # 如果浏览器实例存在且仍然可用，直接复用
        if CNKISearch._browser_instance is not None:
            try:
                # 测试浏览器是否仍然可用（在锁内检查，避免竞态条件）
                CNKISearch._browser_instance.contexts
                return CNKISearch._browser_instance
            except Exception:
                # 浏览器已关闭，重新创建
                CNKISearch._browser_instance = None

        try:
            # 清理旧的 Playwright 实例
            if CNKISearch._playwright_instance is not None:
                try:
                    CNKISearch._playwright_instance.stop()
                except Exception:
                    pass
                CNKISearch._playwright_instance = None

            # 创建新的浏览器实例
            p = sync_playwright().start()
            # [Fix] 添加反检测参数，避免被 CNKI 识别为自动化浏览器
            browser = p.chromium.launch(
                headless=PlaywrightBrowser._detect_headless(),
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--no-first-run",
                    "--disable-dev-shm-usage",
                ],
            )

            CNKISearch._browser_instance = browser
            CNKISearch._playwright_instance = p
            return browser
        except Exception as e:
            print(f"CNKI: 浏览器创建失败: {e}")
            return None

    def _validate_carsi_cookies(self):
        """检查 CARSI cookies 是否仍然有效（轻量级 HTTP 检查，带缓存）

        通过请求 fsso.cnki.net 验证 CNKI CARSI cookies 有效性。
        网络错误时假设 cookies 可能有效（避免误判）。
        """
        if not self.cookies or not isinstance(self.cookies, dict):
            return False

        cnki_cookies = self.cookies.get("fsso.cnki.net", {})
        if not cnki_cookies:
            return False

        try:
            import requests as req

            r = req.get(
                "https://fsso.cnki.net/",
                cookies=cnki_cookies,
                timeout=5,
                allow_redirects=False,
            )
            # 200 表示会话仍有效；302/303 是重定向到登录页，说明 cookies 已过期
            return r.status_code == 200
        except Exception:
            # 网络不可达时假设 cookies 可能有效，避免误跳过
            return True

    def _create_context(self, browser):
        """为每次搜索创建独立的 BrowserContext

        BrowserContext 不是线程安全的，不能跨线程共享。
        每次搜索调用此方法获取独立 context，搜索结束后必须关闭。
        注意：调用方必须持有 _browser_lock（Playwright sync API 不是线程安全的）。
        """
        context = browser.new_context(
            ignore_https_errors=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        # 注入反检测 JavaScript
        context.add_init_script("""
            // 覆盖 navigator.webdriver 属性
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            // 模拟浏览器插件
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            // 设置语言
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
            // 模拟 Chrome 对象
            window.chrome = {runtime: {}};
            // 覆盖 permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
            );
        """)

        # 注入 CARSI cookies（使用调用方预验证的结果，避免在锁内发起 HTTP 请求）
        if self.cookies and isinstance(self.cookies, dict) and self._cookies_valid:
            for domain, domain_cookies in self.cookies.items():
                if isinstance(domain_cookies, dict):
                    for name, value in domain_cookies.items():
                        context.add_cookies(
                            [
                                {
                                    "name": name,
                                    "value": str(value),
                                    "domain": domain,
                                    "path": "/",
                                }
                            ]
                        )

        return context

    def _check_captcha(self, page) -> bool:
        """检查页面是否需要人机验证"""
        try:
            # 检查URL是否包含验证路径
            current_url = page.url
            if "/verify/" in current_url or "verify" in current_url.lower():
                return True
            # 检查是否存在验证码DOM元素（更新选择器以适配 CNKI 新版）
            captcha_selectors = [
                ".verify-container",
                ".captcha",
                "#verify",
                ".ant-modal",
                ".geetest_panel",
                "#captcha",
                # CNKI 新版可能使用的验证组件
                ".slide-verify",
                ".nc-container",
                "#nc_1_wrapper",
                ".verify-wrap",
                ".verify-box",
                "#verify_img",
                ".tcaptcha-popup",
                "#tcaptcha_popup",
            ]
            for selector in captcha_selectors:
                try:
                    if page.query_selector(selector):
                        return True
                except Exception:
                    continue
            # [Fix] 增加基于页面文本内容的检测（CNKI 可能使用动态插入的验证）
            try:
                page_text = page.text_content("body") or ""
                captcha_keywords = [
                    "请完成验证",
                    "安全验证",
                    "拖动滑块",
                    "请按住",
                    "请完成安全验证",
                    "点击按钮进行验证",
                    "滑动完成验证",
                    "向右拖动滑块",
                ]
                if any(kw in page_text for kw in captcha_keywords):
                    return True
            except Exception:
                pass
            return False
        except Exception:
            return False

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=20, field=""
    ) -> list:
        """使用 Playwright + JS evaluate 搜索 CNKI（适配 cnki-skills 模式）"""
        need_cookie_check = False
        if self.cookies and isinstance(self.cookies, dict):
            now = time.time()
            browser_reuse = CNKISearch._browser_instance is not None
            if (
                browser_reuse
                or self._cookies_valid is None
                or (now - self._cookies_last_checked > self._COOKIE_CHECK_INTERVAL)
            ):
                need_cookie_check = True
        cookies_valid_result = None
        if need_cookie_check:
            cookies_valid_result = self._validate_carsi_cookies()

        with CNKISearch._browser_lock:
            if need_cookie_check:
                self._cookies_valid = cookies_valid_result
                self._cookies_last_checked = time.time()
                if not cookies_valid_result:
                    print("CNKI: CARSI cookies 已过期，跳过搜索")
                    return []
            browser = self._get_or_create_browser()
            if browser is None:
                return []

            context, page = None, None
            try:
                context = self._create_context(browser)
                deadline = time.monotonic() + 120  # 增加总超时到120秒
                page = context.new_page()

                # 搜索入口
                search_urls = [
                    f"{self.BASE}/kns8s/defaultresult/index",
                    f"{self.BASE}/kns8/defaultresult/index",
                    f"{self.BASE}/kns/defaultresult/index",
                ]
                page_loaded = False
                for search_url in search_urls:
                    try:
                        page.goto(search_url, timeout=20000)
                        page.wait_for_timeout(2000)
                        test_input = page.evaluate("""() => {
                            return !!document.querySelector('#txt_1_value1, input[name="txt_1_value1"], input.search-input, input[type="text"]');
                        }""")
                        if test_input:
                            page_loaded = True
                            print(f"CNKI: 页面加载成功: {search_url}")
                            break
                    except Exception as e:
                        print(f"CNKI: 尝试 {search_url} 失败: {e}")
                        continue
                if not page_loaded:
                    print("CNKI: 所有搜索入口均加载失败")
                    return []

                # 验证码检测 + 人工等待（增加到90秒）
                if self._check_captcha(page):
                    print(
                        "CNKI: 检测到验证码，请在浏览器中完成人机验证（等待最多 90 秒）"
                    )
                    for _ in range(90):
                        time.sleep(1)
                        if time.monotonic() > deadline:
                            print("CNKI: 总超时")
                            return []
                        if not self._check_captcha(page):
                            print("CNKI: 验证完成，等待 3 秒后刷新页面")
                            time.sleep(3)
                            page.reload()
                            page.wait_for_load_state("domcontentloaded", timeout=15000)
                            page.wait_for_timeout(2000)
                            break
                    else:
                        print("CNKI: 验证超时（90秒）")
                        return []

                if time.monotonic() > deadline:
                    return []

                # 人机验证完成后，刷新页面恢复状态
                # 清理查询文本：去掉自然语言部分，只保留关键词
                clean_query = _clean_search_query(query)
                print(f"CNKI: 清理后查询: '{clean_query}'")

                # JS 注入：填写搜索框 + 点击搜索按钮
                # 作者搜索：选择"作者"字段
                field_select_js = ""
                if field == "au":
                    field_select_js = """
                    const fieldSel = document.querySelector('#txt_1_special1, select[name="txt_1_special1"]');
                    if (fieldSel) { fieldSel.value = 'AU'; fieldSel.dispatchEvent(new Event('change', {bubbles:true})); }
                    """
                search_js = f"""
                (() => {{
                    {field_select_js}
                    const input = document.querySelector('#txt_1_value1, input[name="txt_1_value1"], input.search-input, input[type="text"][id*="txt"], input[type="text"][name*="txt"], input[name="keyword"]');
                    if (!input) return 'no_input';
                    input.value = {json.dumps(clean_query)};
                    input.dispatchEvent(new Event('input', {{bubbles:true}}));
                    const btn = document.querySelector('input[type="submit"], button.search-btn, .search-btn, button[type="submit"], input.btn-search, input[value="搜索"], input[value="检索"]');
                    if (btn) {{ btn.click(); return 'clicked'; }}
                    input.form && input.form.submit();
                    return 'submitted';
                }})()
                """
                result = page.evaluate(search_js)
                print(f"CNKI: 搜索提交结果: {result}")
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    page.wait_for_timeout(3000)

                # 搜索提交后也检查验证码（新增）
                if self._check_captcha(page):
                    print(
                        "CNKI: 搜索后检测到验证码，请在浏览器中完成人机验证（等待最多 90 秒）"
                    )
                    for _ in range(90):
                        time.sleep(1)
                        if time.monotonic() > deadline:
                            print("CNKI: 总超时")
                            return []
                        if not self._check_captcha(page):
                            print("CNKI: 验证完成，等待 3 秒后刷新页面")
                            time.sleep(3)
                            page.reload()
                            page.wait_for_load_state("domcontentloaded", timeout=15000)
                            page.wait_for_timeout(2000)
                            break
                    else:
                        print("CNKI: 验证超时（90秒）")
                        return []

                # 等待结果页加载（验证码/跳转检测）
                max_wait = max(0, int(deadline - time.monotonic()))
                waited = 0
                verification_prompted = False
                while waited < max_wait:
                    if time.monotonic() > deadline:
                        return []
                    try:
                        url = page.url
                        if "/verify/" in url or "verify" in url:
                            if not verification_prompted:
                                print(
                                    "CNKI: 需要验证码，请在浏览器中完成验证（等待最多 90 秒）"
                                )
                                verification_prompted = True
                            page.wait_for_timeout(5000)
                            waited += 5
                            continue
                        captcha = page.evaluate("""() => {
                            return !!document.querySelector('.verify-container, .captcha, #verify, .ant-modal, .yidun_modal, .geetest_panel');
                        }""")
                        if captcha:
                            if not verification_prompted:
                                print(
                                    "CNKI: 需要验证码，请在浏览器中完成验证（等待最多 90 秒）"
                                )
                                verification_prompted = True
                            page.wait_for_timeout(5000)
                            waited += 5
                            continue
                        if "search" in url or "result" in url or "kns" in url:
                            break
                        page.wait_for_timeout(2000)
                        waited += 2
                    except Exception:
                        page.wait_for_timeout(5000)
                        waited += 5

                if time.monotonic() > deadline:
                    return []

                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    page.wait_for_timeout(3000)

                # JS evaluate 批量提取搜索结果（cnki-skills 模式）
                papers_raw = page.evaluate("""() => {
                    const rows = document.querySelectorAll('table.result-table-list tbody tr, .result-table tbody tr, table.result-table tbody tr, .result-list tbody tr, div.result-item, li.result-item');
                    return Array.from(rows).map(row => {
                        const titleEl = row.querySelector('td.name a, .title a, a.fz14, td:nth-child(2) a, .result-list-title a, h3 a, .title-wrap a');
                        const authorEl = row.querySelector('td.author, .author, td:nth-child(3), .result-list-author, .author-list');
                        const sourceEl = row.querySelector('td.source, .source, td:nth-child(4), .result-list-source, .journal-name');
                        const dateEl = row.querySelector('td.date, .date, td:nth-child(5), .result-list-date, .publish-date');
                        const doiEl = row.querySelector('td.doi, .doi, td:nth-child(6), .result-list-doi');
                        const detailLink = (titleEl && titleEl.closest('a')) ? titleEl.closest('a').href : (row.querySelector('a[href*="detail"]') || {}).href || '';
                        return {
                            title: (titleEl && titleEl.textContent || '').trim(),
                            authors: (authorEl && authorEl.textContent || '').trim(),
                            journal: (sourceEl && sourceEl.textContent || '').trim(),
                            year: (dateEl && dateEl.textContent || '').trim(),
                            doi: (doiEl && doiEl.textContent || '').trim().replace(/^DOI:/i, '').trim(),
                            detailUrl: detailLink
                        };
                    });
                }""")
                print(f"CNKI: JS evaluate 提取到 {len(papers_raw)} 条原始结果")

                papers = []
                for raw in papers_raw[:max_results]:
                    if not raw.get("title"):
                        continue
                    p = Paper(source="cnki")
                    p.title = raw["title"].strip()
                    if raw.get("authors"):
                        p.authors = [
                            a.strip()
                            for a in raw["authors"].replace(";", ";").split(";")
                            if a.strip()
                        ]
                    p.journal = raw.get("journal", "").strip()
                    year_match = re.search(r"(\d{4})", raw.get("year", ""))
                    if year_match:
                        p.year = int(year_match.group(1))
                    p.doi = raw.get("doi", "").strip()
                    p._detail_url = raw.get("detailUrl", "")
                    if p.journal:
                        self._parse_vol_issue_pages(p, p.journal)
                    if p.doi and (not p.volume or not p.pages):
                        try:
                            record = self._fetch_crossref_record(p.doi)
                            if record:
                                if not p.volume:
                                    p.volume = str(record.get("volume", "") or "")
                                if not p.issue:
                                    p.issue = str(record.get("issue", "") or "")
                                if not p.pages:
                                    p.pages = str(record.get("page", "") or "")
                                if not p.abstract:
                                    p.abstract = (record.get("abstract", "") or "")[
                                        :500
                                    ]
                        except Exception:
                            pass
                    papers.append(p)

                # 详情页抓取摘要（每篇论文用独立 page，最多 10 篇）
                detail_count = 0
                for p in papers:
                    if p.abstract or not getattr(p, "_detail_url", ""):
                        continue
                    if detail_count >= 10:
                        break
                    try:
                        dp = context.new_page()
                        dp.goto(p._detail_url, timeout=15000)
                        dp.wait_for_timeout(1500)
                        detail = dp.evaluate("""() => {
                            const absEl = document.querySelector('#ChDivSummary, .abstract-text, .abstract, .summary, .row-abstract p, .abstract-content');
                            const kwEls = document.querySelectorAll('.keywords a, .kw a, .keyWords a, .keyword a');
                            return {
                                abstract: (absEl && absEl.textContent || '').trim(),
                                keywords: Array.from(kwEls).map(k => (k.textContent || '').trim()).filter(Boolean)
                            };
                        }""")
                        dp.close()
                        if detail.get("abstract"):
                            p.abstract = detail["abstract"][:500]
                            detail_count += 1
                            print(
                                f"CNKI: 详情页提取摘要 [{detail_count}]: {p.title[:40]}..."
                            )
                        if detail.get("keywords") and not p.keywords:
                            p.keywords = detail["keywords"][:10]
                    except Exception:
                        pass

                if not papers:
                    print("CNKI: 未提取到结果")
                return papers
            except Exception as e:
                print(f"CNKI search error: {e}")
                return []
            finally:
                if page:
                    try:
                        page.close()
                    except Exception:
                        pass
                if context:
                    try:
                        context.close()
                    except Exception:
                        pass

    @staticmethod
    def _parse_vol_issue_pages(paper, source_text):
        """从 CNKI/万方/维普来源文本中解析卷/期/页码。
        常见格式: "期刊名, 2024, 73(12): 123702" 或 "期刊名, 73(12): 123702"
        """
        if not source_text or not paper:
            return
        # 匹配 "卷(期): 页码" 或 "卷(期):页码"
        m = re.search(r"(\d+)\((\d+)\)\s*:\s*(\S+)", source_text)
        if m:
            if not paper.volume:
                paper.volume = m.group(1)
            if not paper.issue:
                paper.issue = m.group(2)
            if not paper.pages:
                paper.pages = m.group(3).rstrip(".,;")
            return
        # 仅匹配 "卷(期)" 无页码
        m = re.search(r"(\d+)\((\d+)\)", source_text)
        if m:
            if not paper.volume:
                paper.volume = m.group(1)
            if not paper.issue:
                paper.issue = m.group(2)

    @staticmethod
    def _fetch_crossref_record(doi):
        """通过 DOI 从 CrossRef 获取完整记录（用于中文数据库兜底富化）"""
        try:
            import requests as _req

            r = _req.get(
                f"https://api.crossref.org/works/{doi}",
                timeout=10,
                headers={"User-Agent": "PaperLens/1.0"},
            )
            if r.status_code == 200:
                return r.json().get("message", {})
        except Exception:
            pass
        return None


def _fetch_chinese_detail_abstracts(papers: list):
    """从万方/维普详情页并发抓取摘要"""
    from concurrent.futures import ThreadPoolExecutor

    def _fetch(p):
        if p.abstract or not getattr(p, "_detail_url", ""):
            return
        try:
            r = requests.get(
                p._detail_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"}
            )
            r.encoding = "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            abs_el = soup.select_one(
                "div.abstract, div.detail-box .abstract, .article-abstract, #abstract, div.row-abstract p"
            )
            if abs_el:
                p.abstract = abs_el.get_text(strip=True)[:500]
            kw_els = soup.select("div.keywords a, .kw a, .keyWords a, .keyword a")
            if kw_els and not p.keywords:
                p.keywords = [
                    k.get_text(strip=True)
                    for k in kw_els[:10]
                    if k.get_text(strip=True)
                ]
        except Exception:
            pass

    needs = [p for p in papers if not p.abstract and getattr(p, "_detail_url", "")]
    if needs:
        print(f"中文详情页: 抓取 {len(needs)} 篇摘要...")
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(_fetch, needs))


class WanfangSearch:
    """万方数据搜索（实验性，网页抓取，支持 Cookie 登录）"""

    BASE = "https://s.wanfangdata.com.cn/paper"

    def __init__(
        self,
        proxy=None,
        cookie="",
        access_proxy=None,
        cookies=None,
        wanfang_cookies=None,
    ):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        self.session.headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        )
        self.session.headers["Accept-Language"] = "zh-CN,zh;q=0.9"
        if cookies and isinstance(cookies, dict):
            # CARSI cookies 是嵌套结构 {domain: {name: value}}，需扁平化
            for domain_cookies in cookies.values():
                if isinstance(domain_cookies, dict):
                    self.session.cookies.update(domain_cookies)
        if wanfang_cookies and isinstance(wanfang_cookies, dict):
            # 万方结构化 cookies: {domain: {name: {value, path}}}，保留域名和路径
            # 优先使用结构化 cookies（按域名匹配发送），不设置扁平 header
            for domain, domain_cookies in wanfang_cookies.items():
                if isinstance(domain_cookies, dict):
                    for name, info in domain_cookies.items():
                        if isinstance(info, dict):
                            self.session.cookies.set(
                                name,
                                info["value"],
                                domain=domain,
                                path=info.get("path", "/"),
                            )
                        else:
                            # 向后兼容：值为字符串时按旧格式处理
                            self.session.cookies.set(name, info, domain=domain)
        elif cookie:
            # 解析扁平 cookie 字符串（Set-Cookie 格式）
            # Set-Cookie 格式中 Domain/Path 出现在 cookie 之后：
            #   name=value; Domain=xxx; Path=/; next_name=next_value; ...
            # 需要先遇到 cookie，再收集其后的属性，遇到下一个 cookie 时才设置上一个
            _ATTR_NAMES = frozenset(
                {
                    "domain",
                    "path",
                    "expires",
                    "max-age",
                    "httponly",
                    "secure",
                    "samesite",
                }
            )
            domain = ".wanfangdata.com.cn"
            path = "/"
            pending = None  # (name, value) 等待设置
            for item in cookie.split(";"):
                item = item.strip()
                if "=" not in item:
                    continue
                name, value = item.split("=", 1)
                name_s = name.strip()
                value_s = value.strip()
                if name_s.lower() in _ATTR_NAMES:
                    if name_s.lower() == "domain":
                        domain = value_s
                    elif name_s.lower() == "path":
                        path = value_s
                else:
                    # 遇到新 cookie，先设置上一个（带其 domain/path）
                    if pending:
                        self.session.cookies.set(
                            pending[0], pending[1], domain=domain, path=path
                        )
                    pending = (name_s, value_s)
                    domain = ".wanfangdata.com.cn"
                    path = "/"
            # 设置最后一个 cookie
            if pending:
                self.session.cookies.set(
                    pending[0], pending[1], domain=domain, path=path
                )
        if proxy:
            self.session.proxies = proxy
        self.access_proxy = access_proxy

    def _url(self, url):
        return self.access_proxy.rewrite(url) if self.access_proxy else url

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=20, field=""
    ) -> list:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            print("万方: beautifulsoup4 未安装，请运行 pip install beautifulsoup4")
            return []

        try:
            # [Fix #6] year_to=0 时使用当前年份，避免发送无效参数
            effective_year_to = year_to if year_to else datetime.now().year
            # StyleID: x=全部, a=作者, t=标题, m=摘要
            style_id = "a" if field == "au" else "x"

            # 清理查询文本：去掉自然语言部分
            clean_query = _clean_search_query(query)

            params = {
                "q": clean_query,
                "StyleID": style_id,
                "Sort": "Correlation",
                "DateType": "Between",
                "PublishDateFrom": str(year_from),
                "PublishDateTo": str(effective_year_to),
            }
            r = self.session.get(self._url(self.BASE), params=params, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"

            soup = BeautifulSoup(r.text, "html.parser")
            papers = []
            items = soup.select("div.normal-list")

            for item in items[:max_results]:
                try:
                    p = Paper(source="wanfang")
                    # 标题
                    title_el = item.select_one("a.title")
                    if title_el:
                        p.title = title_el.get_text(strip=True)
                    # 作者
                    author_el = item.select_one("div.author")
                    if author_el:
                        authors_text = author_el.get_text(strip=True)
                        p.authors = [
                            a.strip()
                            for a in authors_text.replace(";", ",").split(",")
                            if a.strip()
                        ]
                    # 期刊
                    source_el = item.select_one("div.source")
                    if source_el:
                        p.journal = source_el.get_text(strip=True)
                    # 年份
                    date_el = item.select_one("div.year")
                    if date_el:
                        try:
                            p.year = int(date_el.get_text(strip=True)[:4])
                        except ValueError:
                            pass
                    # DOI
                    doi_el = item.select_one("a.doi")
                    if doi_el:
                        p.doi = doi_el.get_text(strip=True)
                    # 被引
                    cite_el = item.select_one("div.cited")
                    if cite_el:
                        try:
                            p.citation_count = int(
                                re.sub(r"[^\d]", "", cite_el.get_text())
                            )
                        except ValueError:
                            pass
                    detail_url = title_el.get("href", "") if title_el else ""
                    if detail_url and not detail_url.startswith("http"):
                        detail_url = "https://s.wanfangdata.com.cn" + detail_url
                    p._detail_url = detail_url
                    # 从来源文本解析卷/期/页码
                    if p.journal:
                        CNKISearch._parse_vol_issue_pages(p, p.journal)
                    if p.doi and (not p.volume or not p.pages):
                        try:
                            record = CNKISearch._fetch_crossref_record(p.doi)
                            if record:
                                if not p.volume:
                                    p.volume = str(record.get("volume", "") or "")
                                if not p.issue:
                                    p.issue = str(record.get("issue", "") or "")
                                if not p.pages:
                                    p.pages = str(record.get("page", "") or "")
                                if not p.abstract:
                                    p.abstract = (record.get("abstract", "") or "")[
                                        :500
                                    ]
                        except Exception:
                            pass
                    if p.title:
                        papers.append(p)
                except Exception:
                    continue

            if papers:
                _fetch_chinese_detail_abstracts(papers[:8])
            return papers
        except Exception as e:
            print(f"万方 search error: {e}")
            return []


class VIPSearch:
    """维普搜索（实验性，网页抓取）"""

    BASE = "https://www.cqvip.com/search/search.aspx"

    def __init__(self, proxy=None, access_proxy=None, cookies=None):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        if proxy:
            self.session.proxies = proxy
        if cookies and isinstance(cookies, dict):
            # CARSI cookies 是嵌套结构 {domain: {name: value}}，需扁平化
            for domain_cookies in cookies.values():
                if isinstance(domain_cookies, dict):
                    self.session.cookies.update(domain_cookies)
        self.access_proxy = access_proxy

    def _url(self, url):
        return self.access_proxy.rewrite(url) if self.access_proxy else url

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=20, field=""
    ) -> list:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            print("维普: beautifulsoup4 未安装，请运行 pip install beautifulsoup4")
            return []

        try:
            # [Fix #6] year_to=0 时使用当前年份，避免发送无效参数
            effective_year_to = year_to if year_to else datetime.now().year

            # 清理查询文本：去掉自然语言部分
            clean_query = _clean_search_query(query)

            # 作者搜索：使用作者字段搜索
            if field == "au":
                # 维普的作者搜索可能需要特殊的参数
                # 尝试使用 AU= 前缀
                search_query = f"AU={clean_query}"
            else:
                search_query = clean_query
            params = {
                "k": search_query,
                "s": "0",  # 相关度排序
                "p": "0",
                "y": f"{year_from}-{effective_year_to}",
            }
            r = self.session.get(self._url(self.BASE), params=params, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"

            soup = BeautifulSoup(r.text, "html.parser")
            papers = []
            items = soup.select("div.result-list li, div.search-result-item")

            for item in items[:max_results]:
                try:
                    p = Paper(source="vip")
                    # 标题
                    title_el = item.select_one("h3 a, a.title, .result-title a")
                    if title_el:
                        p.title = title_el.get_text(strip=True)
                    # 作者
                    author_el = item.select_one(".author, .result-author")
                    if author_el:
                        authors_text = author_el.get_text(strip=True)
                        p.authors = [
                            a.strip()
                            for a in authors_text.replace(";", ",").split(",")
                            if a.strip()
                        ]
                    # 期刊
                    source_el = item.select_one(".source, .result-source")
                    if source_el:
                        p.journal = source_el.get_text(strip=True)
                    # 年份
                    date_el = item.select_one(".date, .result-date")
                    if date_el:
                        try:
                            p.year = int(
                                re.search(r"\d{4}", date_el.get_text()).group()
                            )
                        except (ValueError, AttributeError):
                            pass
                    # DOI
                    doi_el = item.select_one("a[href*='doi.org']")
                    if doi_el:
                        href = doi_el.get("href", "")
                        doi_match = re.search(r"10\.\d{4,}/\S+", href)
                        if doi_match:
                            p.doi = doi_match.group()
                    # 从来源文本解析卷/期/页码（维普格式: "期刊名, 73(12): 123702"）
                    if p.journal:
                        CNKISearch._parse_vol_issue_pages(p, p.journal)
                    # DOI 富化兜底
                    if p.doi and (not p.volume or not p.pages):
                        try:
                            record = CNKISearch._fetch_crossref_record(p.doi)
                            if record:
                                if not p.volume:
                                    v = record.get("volume", "")
                                    if v:
                                        p.volume = str(v)
                                if not p.issue:
                                    iss = record.get("issue", "")
                                    if iss:
                                        p.issue = str(iss)
                                if not p.pages:
                                    pg = record.get("page", "")
                                    if pg:
                                        p.pages = str(pg)
                                if not p.abstract:
                                    ab = record.get("abstract", "")
                                    if ab:
                                        p.abstract = ab.strip()[:500]
                        except Exception:
                            pass
                    # 提取详情页链接用于摘要抓取
                    detail_url = None
                    if title_el and title_el.name == "a":
                        detail_url = title_el.get("href", "")
                        if detail_url and not detail_url.startswith("http"):
                            detail_url = "https://www.cqvip.com" + detail_url
                    p._detail_url = detail_url
                    if p.title:
                        papers.append(p)
                except Exception:
                    continue

            if papers:
                _fetch_chinese_detail_abstracts(papers[:8])
            return papers
        except Exception as e:
            print(f"维普 search error: {e}")
            return []


class BingScholarSearch:
    """Bing 学术搜索（中国区 cn.bing.com，需要 Playwright 渲染）"""

    BASE = "https://cn.bing.com/academic"

    def __init__(self, proxy=None, access_proxy=None):
        self.proxy = proxy
        self.access_proxy = access_proxy

    def _url(self, url):
        return self.access_proxy.rewrite(url) if self.access_proxy else url

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=20, field=""
    ) -> list:
        """使用 Playwright 搜索 Bing Academic（中国区）"""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            print("Bing Academic: beautifulsoup4 未安装")
            return []

        if not year_to:
            year_to = datetime.now().year

        # 作者搜索：在查询中添加 author: 前缀
        search_query = query
        if field == "au":
            search_query = f"author:{query}"

        page = None
        try:
            pb = PlaywrightBrowser.get_instance(proxy=self.proxy)
            page = pb.new_page()
            if page is None:
                print("Bing Academic: Playwright 不可用")
                return []

            # 构建搜索 URL（添加年份过滤）
            url = self._url(f"{self.BASE}?q={search_query}")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)  # 等待 JavaScript 渲染

            content = page.content()
            soup = BeautifulSoup(content, "html.parser")
            papers = []

            # Bing 学术结果选择器（cn.bing.com/academic）
            items = soup.select("li.aca_algo, li[class*='algo']")

            for item in items[:max_results]:
                try:
                    p = Paper(source="bing_academic")

                    # 标题（处理 HTML 标签导致的缺少空格问题）
                    title_el = item.select_one("h2 a")
                    if title_el:
                        p.title = " ".join(
                            title_el.get_text(separator=" ", strip=True).split()
                        )

                    # 作者（在 div.caption_author 中）
                    author_el = item.select_one(".caption_author")
                    if author_el:
                        author_links = author_el.select("a")
                        p.authors = [
                            a.get_text(strip=True)
                            for a in author_links
                            if a.get_text(strip=True)
                        ]

                    # 期刊和年份（在 div.caption_venue 中）
                    venue_el = item.select_one(".caption_venue")
                    if venue_el:
                        venue_text = venue_el.get_text(strip=True)
                        # 提取年份
                        year_match = re.search(r"\b(20\d{2})\b", venue_text)
                        if year_match:
                            p.year = int(year_match.group(1))
                        # 提取期刊名（在 a 标签中）
                        journal_el = venue_el.select_one("a")
                        if journal_el:
                            p.journal = journal_el.get_text(strip=True)

                    # 摘要（在 div.caption_abstract 中）
                    abstract_el = item.select_one(".caption_abstract p")
                    if abstract_el:
                        p.abstract = abstract_el.get_text(strip=True)

                    # 引用数（在 span.caption_cite_count 中）
                    cite_el = item.select_one(".caption_cite_count")
                    if cite_el:
                        cite_text = cite_el.get_text(strip=True)
                        cite_match = re.search(r"\d+", cite_text)
                        if cite_match:
                            p.citation_count = int(cite_match.group())

                    if p.title and len(p.title) > 5:
                        papers.append(p)
                except Exception:
                    continue

            return papers
        except Exception as e:
            print(f"Bing Academic search error: {e}")
            return []
        finally:
            if page:
                try:
                    page.context.close()
                except Exception:
                    pass


class SemanticScholarSearch:
    """Semantic Scholar 搜索（免费 API，收录部分中文论文）"""

    BASE = "https://api.semanticscholar.org/graph/v1"

    def __init__(self, api_key="", proxy=None):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "PaperLens/1.0"
        if api_key:
            self.session.headers["x-api-key"] = api_key
        if proxy:
            self.session.proxies = proxy

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=20, field=""
    ) -> list:
        if not year_to:
            year_to = datetime.now().year

        try:
            params = {
                "query": query,
                "limit": min(max_results, 100),
                "fields": "title,authors,year,abstract,citationCount,externalIds,journal,openAccessPdf,publicationVenue",
            }
            # 作者搜索：使用 author 参数
            if field == "au":
                params["query"] = ""  # 清空 query，使用 author 参数
                params["author"] = query
            # year 参数：仅在有效的年份范围时添加
            if year_from > 0 and year_to > 0:
                params["year"] = f"{year_from}-{year_to}"

            # 带重试的请求（应对限流）
            r = None
            for attempt in range(3):
                r = self.session.get(
                    f"{self.BASE}/paper/search", params=params, timeout=15
                )
                if r.status_code == 429:
                    wait = min(2**attempt * 2, 10)
                    print(f"Semantic Scholar rate limited, waiting {wait}s")
                    time.sleep(wait)
                    continue
                # 403 可能是查询被拒绝或需要 API key，不重试
                if r.status_code == 403:
                    print(
                        "Semantic Scholar access denied (403), query may be rejected or API key required"
                    )
                    return []
                break
            r.raise_for_status()
            data = r.json()

            papers = []
            for item in data.get("data", []):
                try:
                    p = Paper(source="semantic_scholar")
                    p.title = item.get("title", "") or ""
                    if not p.title:
                        continue

                    # 作者
                    for author in item.get("authors", []):
                        name = author.get("name", "")
                        if name:
                            p.authors.append(name)
                        # 提取机构信息
                        for aff in author.get("affiliations", []):
                            if aff and aff not in p.affiliations:
                                p.affiliations.append(aff)

                    p.year = item.get("year", 0) or 0
                    p.abstract = item.get("abstract", "") or ""
                    p.citation_count = item.get("citationCount", 0) or 0

                    # 外部 ID
                    ext_ids = item.get("externalIds", {})
                    p.doi = ext_ids.get("DOI", "") or ""
                    p.pmid = ext_ids.get("PubMed", "") or ""

                    # 期刊
                    journal = item.get("journal", {})
                    if journal:
                        p.journal = journal.get("name", "") or ""

                    # OA 链接
                    oa = item.get("openAccessPdf", {})
                    if oa:
                        p.oa_url = oa.get("url", "") or ""
                    # 卷/期/页码
                    venue = item.get("publicationVenue", {}) or {}
                    if venue:
                        v = venue.get("volume", "")
                        if v:
                            p.volume = str(v)
                        iss = venue.get("issue", "")
                        if iss:
                            p.issue = str(iss)
                        pg = venue.get("pages", "")
                        if pg:
                            p.pages = str(pg)

                    papers.append(p)
                except Exception:
                    continue

            return papers
        except Exception as e:
            print(f"Semantic Scholar search error: {e}")
            return []


def _http_retry(session, url, params=None, timeout=15, retries=4, label=""):
    """通用 HTTP GET 重试（429/5xx 指数退避 + 随机抖动）"""
    import random

    for attempt in range(retries):
        r = session.get(url, params=params, timeout=timeout)
        if r.status_code in (429, 502, 503, 504):
            # 指数退避 + 随机抖动，避免雷鸣效应
            base_wait = min(2**attempt * 1.5, 15)
            jitter = random.uniform(0, base_wait * 0.3)
            wait = base_wait + jitter
            if label:
                print(
                    f"{label}: {r.status_code} 限流，等待 {wait:.1f}s ({attempt + 1}/{retries})"
                )
            time.sleep(wait)
            continue
        return r
    return r


class CrossRefSearch:
    """CrossRef 搜索（免费 API，学术元数据）"""

    BASE = "https://api.crossref.org"

    def __init__(self, email="", proxy=None):
        self.email = email
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "PaperLens/1.0"
        if proxy:
            self.session.proxies = proxy

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=50, field=""
    ) -> list:
        try:
            params = {
                "query": query,
                "rows": min(max_results, 100),
                "sort": "relevance",
            }
            # 作者搜索：使用 query.author 参数
            if field == "au":
                params["query.author"] = query
                del params["query"]
            if self.email:
                params["mailto"] = self.email
            filter_parts = []
            if year_from:
                filter_parts.append(f"from-pub-date:{year_from}")
            if year_to:
                filter_parts.append(f"until-pub-date:{year_to}")
            if filter_parts:
                params["filter"] = ",".join(filter_parts)

            r = _http_retry(
                self.session, f"{self.BASE}/works", params=params, label="CrossRef"
            )
            data = r.json()
            papers = []
            for item in data.get("message", {}).get("items", []):
                try:
                    p = Paper(source="crossref")
                    p.title = (item.get("title", [""]) or [""])[0]
                    p.doi = item.get("DOI", "") or ""
                    p.year = 0
                    pub_date = item.get(
                        "published-print", item.get("published-online", {})
                    )
                    if pub_date and pub_date.get("date-parts"):
                        parts = pub_date["date-parts"][0]
                        if parts and parts[0]:
                            p.year = parts[0]
                    p.journal = ""
                    container = item.get("container-title", [""])
                    if container and container[0]:
                        p.journal = container[0]
                    p.citation_count = item.get("is-referenced-by-count", 0)
                    authors = item.get("author", [])
                    for a in authors[:10]:
                        name = f"{a.get('given', '')} {a.get('family', '')}".strip()
                        if name:
                            p.authors.append(name)
                        # 提取机构信息
                        for aff in a.get("affiliation", []):
                            aff_name = aff.get("name", "")
                            if aff_name and aff_name not in p.affiliations:
                                p.affiliations.append(aff_name)
                    # OA 链接
                    oa = item.get("link", [])
                    if oa:
                        p.oa_url = oa[0].get("URL", "") or ""
                    # 卷/期/页码
                    vol = item.get("volume", "")
                    if vol:
                        p.volume = str(vol)
                    iss = item.get("issue", "")
                    if iss:
                        p.issue = str(iss)
                    pg = item.get("page", "")
                    if pg:
                        p.pages = str(pg)
                    # ISSN
                    issn_list = item.get("ISSN", [])
                    if issn_list:
                        p.issn = str(issn_list[0])
                    # 摘要（CrossRef 搜索通常不返回，但完整 record 有）
                    abstract = item.get("abstract", "")
                    if abstract:
                        p.abstract = abstract.strip()[:500]
                    papers.append(p)
                except Exception:
                    continue
            return papers
        except Exception as e:
            print(f"CrossRef search error: {e}")
            return []


class CrossRefPublisherSearch:
    """基于 CrossRef API 的出版商搜索（免费，按 member ID 过滤）

    支持的出版商：
    - ACS (316): American Chemical Society，化学/材料
    - Optica (285): Optica Publishing Group，光学/光子学
    - IOP (266): IOP Publishing，物理学
    - AIP (317): AIP Publishing，物理学
    """

    BASE = "https://api.crossref.org"

    def __init__(self, member_id: int, source_name: str, email="", proxy=None):
        self.member_id = member_id
        self.source_name = source_name
        self.email = email
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "PaperLens/1.0"
        if proxy:
            self.session.proxies = proxy

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=50, field=""
    ) -> list:
        try:
            # 作者搜索：使用 query.author 参数
            if field == "au":
                params = {
                    "query.author": query,
                    "rows": min(max_results, 100),
                    "sort": "relevance",
                }
            else:
                params = {
                    "query": query,
                    "rows": min(max_results, 100),
                    "sort": "relevance",
                }
            if self.email:
                params["mailto"] = self.email

            # 年份 + 出版商过滤
            filter_parts = [f"member:{self.member_id}"]
            if year_from:
                filter_parts.append(f"from-pub-date:{year_from}")
            if year_to:
                filter_parts.append(f"until-pub-date:{year_to}")
            params["filter"] = ",".join(filter_parts)

            # 带重试的请求（429 限流时指数退避）
            for attempt in range(3):
                r = self.session.get(f"{self.BASE}/works", params=params, timeout=15)
                if r.status_code == 429:
                    wait = (attempt + 1) * 2  # 2s, 4s, 6s
                    print(
                        f"{self.source_name}: 429 限流，等待 {wait}s 后重试 ({attempt + 1}/3)"
                    )
                    time.sleep(wait)
                    continue
                break
            r.raise_for_status()
            data = r.json()
            papers = []
            for item in data.get("message", {}).get("items", []):
                try:
                    p = Paper(source=self.source_name)
                    p.title = (item.get("title", [""]) or [""])[0]
                    p.doi = item.get("DOI", "") or ""
                    p.year = 0
                    pub_date = item.get(
                        "published-print", item.get("published-online", {})
                    )
                    if pub_date and pub_date.get("date-parts"):
                        parts = pub_date["date-parts"][0]
                        if parts and parts[0]:
                            p.year = parts[0]
                    p.journal = ""
                    container = item.get("container-title", [""])
                    if container and container[0]:
                        p.journal = container[0]
                    p.citation_count = item.get("is-referenced-by-count", 0)
                    authors = item.get("author", [])
                    for a in authors[:10]:
                        name = f"{a.get('given', '')} {a.get('family', '')}".strip()
                        if name:
                            p.authors.append(name)
                        # 提取机构信息
                        for aff in a.get("affiliation", []):
                            aff_name = aff.get("name", "")
                            if aff_name and aff_name not in p.affiliations:
                                p.affiliations.append(aff_name)
                    # OA 链接
                    oa = item.get("link", [])
                    if oa:
                        p.oa_url = oa[0].get("URL", "") or ""
                    # 摘要（CrossRef 通常无摘要，但有时有）
                    abstract = item.get("abstract", "")
                    if abstract:
                        p.abstract = abstract.strip()[:500]
                    papers.append(p)
                except Exception:
                    continue
            # DOI 富化：补全缺失的标题和摘要
            enriched = self._enrich_from_full_records(papers)
            if enriched > 0:
                print(
                    f"[{self.source_name}] DOI 富化: {enriched} 篇论文补全了标题/摘要"
                )
            return papers
        except Exception as e:
            print(f"{self.source_name} search error: {e}")
            return []

    def _fetch_full_record(self, doi: str):
        """通过 DOI 从 CrossRef 获取单个 work 的完整记录，返回 message dict 或 None"""
        try:
            url = f"{self.BASE}/works/{doi}"
            params = {}
            if self.email:
                params["mailto"] = self.email
            # 带重试
            for attempt in range(2):
                r = self.session.get(url, params=params, timeout=10)
                if r.status_code == 429:
                    wait = (attempt + 1) * 3
                    time.sleep(wait)
                    continue
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                data = r.json()
                return data.get("message", {})
            return None
        except Exception as e:
            print(f"[{self.source_name}] _fetch_full_record({doi}) error: {e}")
            return None

    def _enrich_from_full_records(self, papers: list) -> int:
        """批量查询 CrossRef 完整记录，补全缺失的 title/abstract/volume/pages 等字段。
        返回成功富化的论文数。"""
        # 筛选有 DOI 且缺 title 或缺 abstract 的论文
        needs_enrich = [p for p in papers if p.doi and (not p.title or not p.abstract)]
        if not needs_enrich:
            return 0
        enriched = 0
        max_enrich = min(len(needs_enrich), 50)  # 每批最多富化 50 篇
        batch = needs_enrich[:max_enrich]
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_map = {
                executor.submit(self._fetch_full_record, p.doi): p for p in batch
            }
            for future in as_completed(future_map):
                paper = future_map[future]
                try:
                    record = future.result()
                    if not record:
                        continue
                    changed = False
                    # 补 title
                    if not paper.title:
                        titles = record.get("title", [])
                        if titles and titles[0]:
                            paper.title = titles[0]
                            changed = True
                    # 补 abstract
                    if not paper.abstract:
                        abstract = record.get("abstract", "")
                        if abstract:
                            paper.abstract = abstract.strip()[:500]
                            changed = True
                    # 补卷/期/页码
                    if not paper.volume:
                        vol = record.get("volume", "")
                        if vol:
                            paper.volume = str(vol)
                            changed = True
                    if not paper.issue:
                        iss = record.get("issue", "")
                        if iss:
                            paper.issue = str(iss)
                            changed = True
                    if not paper.pages:
                        pg = record.get("page", "")
                        if pg:
                            paper.pages = str(pg)
                            changed = True
                    if not paper.issn:
                        issn_list = record.get("ISSN", [])
                        if issn_list:
                            paper.issn = str(issn_list[0])
                            changed = True
                    if changed:
                        enriched += 1
                except Exception:
                    continue
                # 礼貌间隔
                time.sleep(0.06)
        return enriched


class ArxivSearch:
    """arXiv 搜索（免费 API，预印本）"""

    BASE = "https://export.arxiv.org/api/query"  # [Fix #17] 改用 HTTPS

    def __init__(self, proxy=None):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "PaperLens/1.0"
        if proxy:
            self.session.proxies = proxy

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=50, field=""
    ) -> list:
        try:
            import xml.etree.ElementTree as ET

            # 清理 PubMed 字段标签语法（arXiv 不识别）
            clean_query = re.sub(
                r"\[(ti|tiab|au|ta|tw|mh|pt|pdat)\]", "", query, flags=re.IGNORECASE
            )
            # 作者搜索：使用 au: 前缀
            if field == "au":
                search_query = f"au:{clean_query}"
            else:
                search_query = f"all:{clean_query}"
            params = {
                "search_query": search_query,
                "start": 0,
                "max_results": min(max_results, 100),
                "sortBy": "relevance",
            }
            r = self.session.get(self.BASE, params=params, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"

            root = ET.fromstring(r.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            papers = []
            for entry in root.findall("atom:entry", ns):
                try:
                    p = Paper(source="arxiv")
                    title_el = entry.find("atom:title", ns)
                    if title_el is not None and title_el.text:
                        p.title = title_el.text.strip().replace("\n", " ")
                    # arXiv ID 作为 DOI
                    id_el = entry.find("atom:id", ns)
                    if id_el is not None and id_el.text:
                        arxiv_id = id_el.text.strip().split("/abs/")[-1]
                        p.doi = f"arXiv:{arxiv_id}"
                    # 年份
                    published_el = entry.find("atom:published", ns)
                    if published_el is not None and published_el.text:
                        try:
                            p.year = int(published_el.text[:4])
                        except ValueError:
                            pass
                    # 作者
                    for author in entry.findall("atom:author", ns):
                        name_el = author.find("atom:name", ns)
                        if name_el is not None and name_el.text:
                            p.authors.append(name_el.text.strip())
                    # 摘要
                    summary_el = entry.find("atom:summary", ns)
                    if summary_el is not None and summary_el.text:
                        p.abstract = summary_el.text.strip()[:500]
                    # PDF 链接
                    for link in entry.findall("atom:link", ns):
                        if link.get("title") == "pdf":
                            p.oa_url = link.get("href", "")
                            break
                    # 分类/关键词
                    for cat in entry.findall("atom:category", ns):
                        term = cat.get("term", "")
                        if term:
                            p.keywords.append(term)
                    # 期刊
                    journal_el = entry.find("atom:journal_ref", ns)
                    if journal_el is not None and journal_el.text:
                        p.journal = journal_el.text.strip()
                    papers.append(p)
                except Exception:
                    continue

            # 年份过滤（arXiv API 不支持年份参数过滤）
            if year_from or year_to:
                filtered = []
                for p in papers:
                    if not p.year:
                        filtered.append(p)
                        continue
                    if year_from and p.year < year_from:
                        continue
                    if year_to and p.year > year_to:
                        continue
                    filtered.append(p)
                return filtered
            return papers
        except Exception as e:
            print(f"arXiv search error: {e}")
            return []


class DBLPSearch:
    """DBLP 搜索（免费 API，计算机科学会议/期刊论文核心索引）"""

    BASE = "https://dblp.org/search/publ/api"

    def __init__(self, proxy=None):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "PaperLens/1.0"
        if proxy:
            self.session.proxies = proxy

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=50, field=""
    ) -> list:
        try:
            # 清理 PubMed 字段标签语法（DBLP 不识别）
            clean_query = re.sub(
                r"\[(ti|tiab|au|ta|tw|mh|pt|pdat)\]", "", query, flags=re.IGNORECASE
            )
            # 作者搜索：使用 author: 前缀
            if field == "au":
                search_query = f"author:{clean_query.strip()}"
            else:
                search_query = clean_query.strip()
            params = {
                "q": search_query,
                "format": "json",
                "h": min(max_results, 100),
                "f": 0,
            }
            # 带重试的请求（500 临时错误时重试）
            for attempt in range(2):
                r = self.session.get(self.BASE, params=params, timeout=15)
                if r.status_code == 500:
                    print(f"DBLP: 500 临时错误，等待 3s 后重试 ({attempt + 1}/2)")
                    time.sleep(3)
                    continue
                break
            r.raise_for_status()
            data = r.json()

            hits = data.get("result", {}).get("hits", {}).get("hit", [])
            if not hits:
                return []

            papers = []
            for hit in hits:
                try:
                    info = hit.get("info", {})
                    title = info.get("title", "")
                    if not title:
                        continue

                    p = Paper(source="dblp")
                    p.title = title.strip().rstrip(".")

                    # DOI
                    doi = info.get("doi", "")
                    if doi:
                        p.doi = doi

                    # 年份
                    year_str = info.get("year", "")
                    if year_str:
                        try:
                            p.year = int(year_str)
                        except ValueError:
                            pass

                    # 作者（可能是列表或单个）
                    authors_data = info.get("authors", {}).get("author", [])
                    if isinstance(authors_data, dict):
                        authors_data = [authors_data]
                    for author in authors_data:
                        if isinstance(author, dict):
                            name = author.get("text", "")
                            if name:
                                p.authors.append(name)
                        elif isinstance(author, str):
                            p.authors.append(author)

                    # 期刊/会议
                    venue = info.get("venue", "")
                    if isinstance(venue, list):
                        venue = ", ".join(str(v) for v in venue)
                    if venue:
                        p.journal = venue

                    # 类型
                    pub_type = info.get("type", "")
                    if pub_type:
                        p.keywords.append(pub_type)

                    # URL
                    url = info.get("url", "")
                    if url:
                        p.oa_url = url

                    papers.append(p)
                except Exception:
                    continue

            # 年份过滤（DBLP API 不直接支持年份参数）
            if year_from or year_to:
                filtered = []
                for p in papers:
                    if not p.year:
                        filtered.append(p)
                        continue
                    if year_from and p.year < year_from:
                        continue
                    if year_to and p.year > year_to:
                        continue
                    filtered.append(p)
                if filtered:
                    _enrich_dblp_abstracts(filtered[:10])
                return filtered
            if papers:
                _enrich_dblp_abstracts(papers[:10])
            return papers
        except Exception as e:
            print(f"DBLP search error: {e}")
            return []


def _enrich_dblp_abstracts(papers: list):
    """跨源补 DBLP 论文摘要（DOI→CrossRef，标题→Semantic Scholar）"""
    from concurrent.futures import ThreadPoolExecutor

    def _fetch(p):
        if p.abstract:
            return
        try:
            if p.doi:
                r = requests.get(
                    f"https://api.crossref.org/works/{p.doi}",
                    timeout=10,
                    headers={"User-Agent": "PaperLens/1.0"},
                )
                if r.status_code == 200 and r.json().get("message", {}).get("abstract"):
                    p.abstract = r.json()["message"]["abstract"][:500]
                    return
            if p.title:
                r2 = requests.get(
                    "https://api.semanticscholar.org/graph/v1/paper/search",
                    params={"query": p.title, "limit": 1, "fields": "title,abstract"},
                    timeout=10,
                )
                if r2.status_code == 200:
                    d = r2.json().get("data", [])
                    if d and d[0].get("abstract"):
                        p.abstract = d[0]["abstract"][:500]
        except Exception:
            pass

    needs = [p for p in papers if not p.abstract]
    if needs:
        print(f"DBLP: S2/CrossRef 补摘要 {len(needs)} 篇...")
        with ThreadPoolExecutor(max_workers=3) as ex:
            list(ex.map(_fetch, needs))


class BioRxivSearch:
    """bioRxiv/medRxiv 搜索（通过 Europe PMC API，生物医学预印本）"""

    BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self, proxy=None):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "PaperLens/1.0"
        if proxy:
            self.session.proxies = proxy

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=50, field=""
    ) -> list:
        try:
            # 清理 PubMed 字段标签语法
            clean_query = re.sub(
                r"\[(ti|tiab|au|ta|tw|mh|pt|pdat)\]", "", query, flags=re.IGNORECASE
            ).strip()

            # 作者搜索：使用 AUTH:"" 语法
            if field == "au":
                search_query = f'AUTH:"{clean_query}"'
            else:
                search_query = clean_query

            # 构建查询：关键词 + 来源过滤（bioRxiv OR medRxiv）+ 年份过滤
            # 注意：bioRxiv/medRxiv 在 Europe PMC 中是 PPR（预印本），publisher 信息
            # 在 bookOrReportDetails.publisher 中，必须用 PUBLISHER: 而非 JOURNAL: 过滤
            search_query = (
                f'{search_query} AND (PUBLISHER:"bioRxiv" OR PUBLISHER:"medRxiv")'
            )
            if year_from and year_to:
                search_query += (
                    f" AND (FIRST_PDATE:[{year_from}-01-01 TO {year_to}-12-31])"
                )
            elif year_from:
                search_query += f" AND (FIRST_PDATE:[{year_from}-01-01 TO 3000-01-01])"

            params = {
                "query": search_query,
                "format": "json",
                "pageSize": min(max_results, 100),
                "resultType": "core",
            }
            r = self.session.get(self.BASE, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()

            results = data.get("resultList", {}).get("result", [])
            if not results:
                return []

            papers = []
            for item in results:
                try:
                    # 确定来源：优先用 bookOrReportDetails.publisher（PPR 预印本），
                    # 回退到 journalInfo.journal.title（已发表论文）
                    publisher = (item.get("bookOrReportDetails", {}) or {}).get(
                        "publisher", ""
                    )
                    journal_info = item.get("journalInfo", {}) or {}
                    journal_obj = journal_info.get("journal", {}) or {}
                    journal_title = (journal_obj.get("title") or "").lower()
                    journal_abbr = (
                        journal_obj.get("medlineAbbreviation") or ""
                    ).lower()
                    source_name = (
                        "medrxiv"
                        if (
                            "medrxiv" in publisher.lower()
                            or "medrxiv" in journal_title
                            or "medrxiv" in journal_abbr
                        )
                        else "biorxiv"
                    )

                    p = Paper(source=source_name)
                    p.title = item.get("title", "") or ""
                    if not p.title:
                        continue

                    # DOI
                    doi = item.get("doi", "")
                    if doi:
                        p.doi = doi

                    # PMID
                    pmid = item.get("pmid", "")
                    if pmid:
                        p.pmid = pmid

                    # 年份
                    pub_year = item.get("pubYear", "")
                    if pub_year:
                        try:
                            p.year = int(pub_year)
                        except ValueError:
                            pass

                    # 作者
                    author_list = item.get("authorString", "")
                    if author_list:
                        for author in author_list.split(","):
                            author = author.strip()
                            if author:
                                p.authors.append(author)

                    # 提取机构信息
                    for author_detail in item.get("authorList", {}).get("author", []):
                        for aff_detail in author_detail.get(
                            "authorAffiliationDetailsList", {}
                        ).get("authorAffiliation", []):
                            aff_text = aff_detail.get("affiliation", "")
                            if aff_text and aff_text not in p.affiliations:
                                p.affiliations.append(aff_text)

                    # 摘要
                    abstract = item.get("abstractText", "")
                    if abstract:
                        p.abstract = abstract.strip()[:500]

                    # 期刊/预印本来源
                    if journal_title:
                        p.journal = journal_obj.get("title", "")
                    elif publisher:
                        p.journal = publisher

                    # OA 链接
                    url_list = item.get("fullTextUrlList", {}).get("fullTextUrl", [])
                    for u in url_list:
                        if (
                            u.get("documentStyle") == "html"
                            or u.get("availability") == "Open access"
                        ):
                            p.oa_url = u.get("url", "")
                            break
                    if not p.oa_url and url_list:
                        p.oa_url = url_list[0].get("url", "")
                    # 预印本结果通常只有 DOI 链接，构造直接访问 URL
                    if p.oa_url and "doi.org" in p.oa_url and p.doi:
                        server = "medrxiv" if source_name == "medrxiv" else "biorxiv"
                        p.oa_url = f"https://www.{server}.org/content/early/{p.doi}"

                    # 引用次数
                    p.citation_count = item.get("citedByCount", 0)

                    # 关键词
                    keywords = item.get("keywordList", {}).get("keyword", [])
                    for kw in keywords[:5]:
                        if kw:
                            p.keywords.append(kw)

                    papers.append(p)
                except Exception:
                    continue

            return papers
        except Exception as e:
            print(f"bioRxiv/medRxiv search error: {e}")
            return []


class AgrisSearch:
    """AGRIS 搜索（免费 API，FAO 维护，农业/环境/食品科学，1300万+ 记录）"""

    BASE = "https://agris.fao.org/search/en/sd/json"

    def __init__(self, proxy=None):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "PaperLens/1.0"
        if proxy:
            self.session.proxies = proxy

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=50, field=""
    ) -> list:
        try:
            # 清理 PubMed 字段标签语法
            clean_query = re.sub(
                r"\[(ti|tiab|au|ta|tw|mh|pt|pdat)\]", "", query, flags=re.IGNORECASE
            ).strip()

            # 作者搜索：使用 author: 前缀
            if field == "au":
                search_query = f"author:{clean_query}"
            else:
                search_query = clean_query

            params = {
                "q": search_query,
                "pageSize": min(max_results, 100),
                "page": 0,
            }
            # 年份过滤
            if year_from:
                params["filterIssuetimeFrom"] = f"{year_from}"
            if year_to:
                params["filterIssuetimeTo"] = f"{year_to}"

            # 带重试的请求（应对 429 限流）
            r = None
            for attempt in range(3):
                r = self.session.get(self.BASE, params=params, timeout=20)
                if r.status_code == 429:
                    wait = min(2**attempt * 2, 10)
                    print(
                        f"AGRIS rate limited, waiting {wait}s (attempt {attempt + 1}/3)"
                    )
                    time.sleep(wait)
                    continue
                break
            if r.status_code == 404:
                print("AGRIS: API 端点返回 404，可能已迁移。跳过此数据源。")
                return []
            r.raise_for_status()
            data = r.json()

            records = data.get("results", [])
            if not records:
                return []

            papers = []
            for record in records:
                try:
                    title = record.get("title", "")
                    if not title:
                        continue

                    p = Paper(source="agris")
                    p.title = title.strip()

                    # DOI
                    doi = record.get("doi", "")
                    if doi:
                        p.doi = doi

                    # 年份
                    year_str = record.get("year", "") or record.get("issuetime", "")
                    if year_str:
                        try:
                            p.year = int(str(year_str)[:4])
                        except ValueError:
                            pass

                    # 作者
                    authors = record.get("authors", [])
                    if isinstance(authors, list):
                        for author in authors:
                            if isinstance(author, dict):
                                name = author.get("name", "") or author.get("value", "")
                                if name:
                                    p.authors.append(name)
                            elif isinstance(author, str):
                                p.authors.append(author)

                    # 摘要
                    abstract = record.get("description", "") or record.get(
                        "abstract", ""
                    )
                    if abstract:
                        p.abstract = abstract.strip()[:500]

                    # 期刊/来源
                    source_title = record.get("journalTitle", "") or record.get(
                        "sourceTitle", ""
                    )
                    if source_title:
                        p.journal = source_title

                    # 关键词
                    subjects = record.get("subjects", [])
                    if isinstance(subjects, list):
                        for subj in subjects[:5]:
                            if isinstance(subj, dict):
                                kw = subj.get("value", "") or subj.get("name", "")
                                if kw:
                                    p.keywords.append(kw)
                            elif isinstance(subj, str):
                                p.keywords.append(subj)

                    # URL
                    ags_no = record.get("ags_no", "")
                    if ags_no:
                        p.oa_url = f"https://agris.fao.org/agris-search/search.do?recordID={ags_no}"
                    elif doi:
                        p.oa_url = f"https://doi.org/{doi}"

                    # ISSN
                    issn = record.get("issn", "")
                    if issn:
                        p.issn = issn

                    papers.append(p)
                except Exception:
                    continue

            return papers
        except Exception as e:
            print(f"AGRIS search error: {e}")
            return []


class EuropePMCSearch:
    """Europe PMC 搜索（免费 API，生物医学 OA 文献，PubMed 补充）"""

    BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self, proxy=None):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "PaperLens/1.0"
        if proxy:
            self.session.proxies = proxy

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=50, field=""
    ) -> list:
        try:
            # 清理 PubMed 字段标签语法
            clean_query = re.sub(
                r"\[(ti|tiab|au|ta|tw|mh|pt|pdat)\]", "", query, flags=re.IGNORECASE
            ).strip()

            # 作者搜索：使用 AUTH:"" 语法
            if field == "au":
                search_query = f'AUTH:"{clean_query}"'
            else:
                search_query = clean_query

            # 构建查询（支持年份过滤）
            if year_from and year_to:
                search_query += (
                    f" AND (FIRST_PDATE:[{year_from}-01-01 TO {year_to}-12-31])"
                )
            elif year_from:
                search_query += f" AND (FIRST_PDATE:[{year_from}-01-01 TO 3000-01-01])"

            params = {
                "query": search_query,
                "format": "json",
                "pageSize": min(max_results, 100),
                "resultType": "core",
            }
            r = self.session.get(self.BASE, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()

            results = data.get("resultList", {}).get("result", [])
            if not results:
                return []

            papers = []
            for item in results:
                try:
                    p = Paper(source="europepmc")
                    p.title = item.get("title", "") or ""
                    if not p.title:
                        continue

                    # DOI
                    doi = item.get("doi", "")
                    if doi:
                        p.doi = doi

                    # PMID
                    pmid = item.get("pmid", "")
                    if pmid:
                        p.pmid = pmid

                    # 年份
                    pub_year = item.get("pubYear", "")
                    if pub_year:
                        try:
                            p.year = int(pub_year)
                        except ValueError:
                            pass

                    # 作者
                    author_list = item.get("authorString", "")
                    if author_list:
                        for author in author_list.split(","):
                            author = author.strip()
                            if author:
                                p.authors.append(author)

                    # 提取机构信息
                    for author_detail in item.get("authorList", {}).get("author", []):
                        for aff_detail in author_detail.get(
                            "authorAffiliationDetailsList", {}
                        ).get("authorAffiliation", []):
                            aff_text = aff_detail.get("affiliation", "")
                            if aff_text and aff_text not in p.affiliations:
                                p.affiliations.append(aff_text)

                    # 摘要
                    abstract = item.get("abstractText", "")
                    if abstract:
                        p.abstract = abstract.strip()[:500]

                    # 期刊
                    journal = item.get("journalTitle", "")
                    if journal:
                        p.journal = journal

                    # OA 链接
                    url = item.get("fullTextUrlList", {}).get("fullTextUrl", [])
                    for u in url:
                        if (
                            u.get("documentStyle") == "html"
                            or u.get("availability") == "Open access"
                        ):
                            p.oa_url = u.get("url", "")
                            break
                    if not p.oa_url and url:
                        p.oa_url = url[0].get("url", "")

                    # 引用次数
                    p.citation_count = item.get("citedByCount", 0)

                    # 关键词
                    keywords = item.get("keywordList", {}).get("keyword", [])
                    for kw in keywords[:5]:
                        if kw:
                            p.keywords.append(kw)
                    # 卷/期/页码
                    jinfo = item.get("journalInfo", {}) or {}
                    if jinfo and jinfo.get("journal"):
                        j = jinfo["journal"]
                        v = j.get("volume", "")
                        if v:
                            p.volume = str(v)
                        iss = j.get("issue", "")
                        if iss:
                            p.issue = str(iss)
                        pg = j.get("pages", "")
                        if pg:
                            p.pages = str(pg)
                    # ISSN
                    issn = item.get("issn", "")
                    if issn:
                        p.issn = issn

                    papers.append(p)
                except Exception:
                    continue

            return papers
        except Exception as e:
            print(f"Europe PMC search error: {e}")
            return []


class ScraperAPIProxy:
    """ScraperAPI 代理（付费服务，绕过反爬机制）"""

    BASE = "http://api.scraperapi.com"

    def __init__(self, api_key):
        self.api_key = api_key

    def get(self, url, params=None, timeout=30, **kwargs):
        """通过 ScraperAPI 代理请求"""
        # [Fix #18] 用 header 传递 API key，避免明文出现在 URL 中
        proxy_params = {
            "url": url,
            "render": "true",  # 启用 JavaScript 渲染
        }
        if params:
            # 将原始参数编码到 URL 中
            from urllib.parse import urlencode

            proxy_params["url"] = f"{url}?{urlencode(params)}"

        headers = {"Authorization": f"Bearer {self.api_key}"}
        return requests.get(
            self.BASE, params=proxy_params, headers=headers, timeout=timeout
        )


class ScienceDirectSearch:
    """ScienceDirect 搜索（CARSI 认证，Elsevier 全学科）"""

    BASE = "https://www.sciencedirect.com"

    def __init__(self, proxy=None, cookies=None):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            }
        )
        if proxy:
            self.session.proxies = proxy
        if cookies and isinstance(cookies, dict):
            for domain_cookies in cookies.values():
                if isinstance(domain_cookies, dict):
                    self.session.cookies.update(domain_cookies)

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=50, field=""
    ) -> list:
        try:
            # 作者搜索：使用 authors 参数
            if field == "au":
                params = {
                    "authors": query,
                    "show": min(max_results, 100),
                    "sortBy": "relevance",
                }
            else:
                params = {
                    "qs": query,
                    "show": min(max_results, 100),
                    "sortBy": "relevance",
                }
            if year_from:
                params["date"] = f"{year_from}-{year_to or datetime.now().year}"
            r = self.session.get(f"{self.BASE}/search/api", params=params, timeout=15)
            if r.status_code != 200:
                return []
            data = r.json()
            papers = []
            for item in data.get("searchResults", {}).get("results", []):
                try:
                    p = Paper(source="sciencedirect")
                    p.title = item.get("title", "") or ""
                    p.doi = item.get("doi", "") or ""
                    p.year = 0
                    pub = item.get("publicationDate", "")
                    if pub:
                        try:
                            p.year = int(pub[:4])
                        except ValueError:
                            pass
                    p.journal = item.get("sourceTitle", "") or ""
                    p.citation_count = item.get("citedBy", 0)
                    authors = item.get("authors", [])
                    for a in authors[:10]:
                        name = a.get("name", "")
                        if name:
                            p.authors.append(name)
                    p.abstract = item.get("abstract", "") or ""
                    # 卷/期/页码
                    vol = item.get("volume", "")
                    if vol:
                        p.volume = str(vol)
                    iss = item.get("issue", "")
                    if iss:
                        p.issue = str(iss)
                    pg = item.get("pages", "")
                    if pg:
                        p.pages = str(pg)
                    papers.append(p)
                except Exception:
                    continue
            return papers
        except Exception as e:
            print(f"ScienceDirect search error: {e}")
            return []


class ScopusSearch:
    """Scopus 搜索（CARSI 认证，Elsevier 文献索引）"""

    BASE = "https://www.scopus.com"

    def __init__(self, proxy=None, cookies=None):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            }
        )
        if proxy:
            self.session.proxies = proxy
        if cookies and isinstance(cookies, dict):
            for domain_cookies in cookies.values():
                if isinstance(domain_cookies, dict):
                    self.session.cookies.update(domain_cookies)

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=50, field=""
    ) -> list:
        try:
            # 作者搜索：使用 AUTH() 查询语法
            if field == "au":
                search_query = f"AUTH({query})"
            else:
                search_query = query
            # Scopus 搜索 API
            params = {
                "query": search_query,
                "count": min(max_results, 100),
                "sort": "relevance",
            }
            if year_from:
                params["date"] = f"{year_from}-{year_to or datetime.now().year}"
            r = self.session.get(f"{self.BASE}/search/api", params=params, timeout=15)
            if r.status_code != 200:
                return []
            data = r.json()
            papers = []
            for item in data.get("results", []):
                try:
                    p = Paper(source="scopus")
                    p.title = item.get("title", "") or ""
                    p.doi = item.get("doi", "") or ""
                    p.year = 0
                    pub = item.get("coverDate", "")
                    if pub:
                        try:
                            p.year = int(pub[:4])
                        except ValueError:
                            pass
                    p.journal = item.get("publicationName", "") or ""
                    p.citation_count = item.get("citedbyCount", 0)
                    authors = item.get("authorNames", "").split(";")
                    for a in authors[:10]:
                        a = a.strip()
                        if a:
                            p.authors.append(a)
                    p.abstract = item.get("description", "") or ""
                    # 卷/期/页码
                    vol = item.get("volume", "")
                    if vol:
                        p.volume = str(vol)
                    iss = item.get("issueIdentifier", "")
                    if iss:
                        p.issue = str(iss)
                    pg = item.get("pageRange", "")
                    if pg:
                        p.pages = str(pg)
                    papers.append(p)
                except Exception:
                    continue
            return papers
        except Exception as e:
            print(f"Scopus search error: {e}")
            return []


class JstorSearch:
    """JSTOR 搜索（CARSI 认证，人文社科期刊）"""

    BASE = "https://www.jstor.org"

    def __init__(self, proxy=None, cookies=None):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            }
        )
        if proxy:
            self.session.proxies = proxy
        if cookies and isinstance(cookies, dict):
            for domain_cookies in cookies.values():
                if isinstance(domain_cookies, dict):
                    self.session.cookies.update(domain_cookies)

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=50, field=""
    ) -> list:
        try:
            from bs4 import BeautifulSoup

            # 作者搜索：使用 au: 前缀
            if field == "au":
                search_query = f"au:{query}"
            else:
                search_query = query
            params = {
                "q": search_query,
                "pagemark": "1",
                "pageSize": min(max_results, 100),
                "sortBy": "relevance",
            }
            if year_from:
                params["sd"] = str(year_from)
            if year_to:
                params["ed"] = str(year_to)
            r = self.session.get(
                f"{self.BASE}/search/do/basic", params=params, timeout=15
            )
            if r.status_code != 200:
                return []
            r.encoding = "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            papers = []
            for item in soup.select(".search-result"):
                try:
                    p = Paper(source="jstor")
                    title_el = item.select_one(".result-title a")
                    if title_el:
                        p.title = title_el.get_text(strip=True)
                        href = title_el.get("href", "")
                        if href:
                            doi = href.split("/stable/")[-1].split("?")[0]
                            p.doi = f"jstor:{doi}" if doi else ""
                    authors_el = item.select_one(".result-authors")
                    if authors_el:
                        for a in authors_el.get_text(strip=True).split(","):
                            a = a.strip()
                            if a:
                                p.authors.append(a)
                    journal_el = item.select_one(".result-journal")
                    if journal_el:
                        p.journal = journal_el.get_text(strip=True)
                    year_el = item.select_one(".result-year")
                    if year_el:
                        try:
                            p.year = int(year_el.get_text(strip=True)[:4])
                        except ValueError:
                            pass
                    papers.append(p)
                except Exception:
                    continue
            return papers
        except Exception as e:
            print(f"JSTOR search error: {e}")
            return []


class CORESearch:
    """CORE 搜索（开放获取论文聚合，3亿+记录）

    CORE (core.ac.uk) 是全球最大的开放获取论文聚合平台，
    覆盖机构仓储、预印本平台、OA 期刊等。
    免费 API key 注册：https://core.ac.uk/services/api
    """

    BASE = "https://api.core.ac.uk/v3"

    def __init__(self, api_key="", proxy=None):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
            }
        )
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"
        if proxy:
            self.session.proxies = proxy

    def search(
        self, query: str, year_from=2020, year_to=0, max_results=50, field=""
    ) -> list:
        """搜索 CORE 数据库"""
        try:
            # 作者搜索：使用 authors: 前缀
            if field == "au":
                search_query = f"authors:{query}"
            else:
                search_query = query
            params = {
                "q": search_query,
                "limit": min(max_results, 100),
            }
            # 年份过滤
            if year_from or year_to:
                year_filter = []
                if year_from:
                    year_filter.append(f">={year_from}")
                if year_to:
                    year_filter.append(f"<={year_to or datetime.now().year}")
                if year_filter:
                    params["yearFilter"] = ",".join(year_filter)

            r = self.session.get(f"{self.BASE}/search/works", params=params, timeout=15)
            if r.status_code == 401:
                print("CORE: API key 无效或未配置")
                return []
            if r.status_code != 200:
                print(f"CORE: 请求失败，状态码 {r.status_code}")
                return []

            data = r.json()
            papers = []
            for item in data.get("results", []):
                try:
                    p = Paper(source="core")
                    p.title = item.get("title", "") or ""
                    p.abstract = item.get("abstract", "") or ""
                    p.doi = item.get("doi", "") or ""
                    p.year = 0
                    pub_year = item.get("yearPublished") or item.get(
                        "publishedDate", ""
                    )
                    if pub_year:
                        try:
                            p.year = int(str(pub_year)[:4])
                        except ValueError:
                            pass
                    # 作者
                    authors = item.get("authors", [])
                    if isinstance(authors, list):
                        for a in authors[:10]:
                            if isinstance(a, dict):
                                name = a.get("name", "")
                            else:
                                name = str(a)
                            if name:
                                p.authors.append(name)
                    # 期刊名
                    journals = item.get("journals", [])
                    if journals and isinstance(journals, list) and journals[0]:
                        j = journals[0]
                        if isinstance(j, dict):
                            p.journal = j.get("title", "") or ""
                        elif isinstance(j, str):
                            p.journal = j
                    # OA 链接
                    sources = item.get("sourceFulltextUrls", [])
                    if sources:
                        p.oa_url = sources[0] if isinstance(sources[0], str) else ""
                    # 引用数
                    p.citation_count = item.get("citationCount", 0) or 0
                    # 关键词
                    keywords = item.get("topics", [])
                    if isinstance(keywords, list):
                        p.keywords = [str(k) for k in keywords[:10]]
                    if p.title:
                        papers.append(p)
                except Exception:
                    continue
            return papers
        except Exception as e:
            print(f"CORE search error: {e}")
            return []


class LensSearch:
    """Lens.org 搜索（学术文献+专利，2.5亿+记录）

    Lens.org 是唯一同时覆盖学术文献和专利的开放平台。
    免费 API token 注册：https://www.lens.org
    """

    BASE_SCHOLARLY = "https://api.lens.org/scholarly"
    BASE_PATENT = "https://api.lens.org/patent"

    def __init__(self, api_key="", proxy=None):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"
        if proxy:
            self.session.proxies = proxy

    def search(
        self,
        query: str,
        year_from=2020,
        year_to=0,
        max_results=50,
        patent_mode=False,
        field="",
    ) -> list:
        """搜索 Lens.org 学术文献或专利

        Args:
            query: 检索词
            year_from: 起始年份
            year_to: 结束年份
            max_results: 最大结果数
            patent_mode: True 时搜索专利（使用 /patent/search 端点）
            field: 搜索字段（"au" 表示作者搜索）
        """
        try:
            # 选择端点：学术文献 or 专利
            base = self.BASE_PATENT if patent_mode else self.BASE_SCHOLARLY

            # 构建 Elasticsearch 风格的查询
            must_clauses = []
            if query:
                # 作者搜索：使用 author.name 字段
                if field == "au":
                    must_clauses.append({"match": {"author.name": query}})
                else:
                    must_clauses.append(
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["title", "abstract", "keywords"],
                            }
                        }
                    )
            # 年份过滤
            if year_from or year_to:
                year_range = {}
                if year_from:
                    year_range["gte"] = year_from
                if year_to:
                    year_range["lte"] = year_to or datetime.now().year
                must_clauses.append({"range": {"year_published": year_range}})

            payload = {
                "query": {"bool": {"must": must_clauses}},
                "size": min(max_results, 50),
                "sort": [{"_score": "desc"}],
            }

            r = self.session.post(f"{base}/search", json=payload, timeout=15)
            if r.status_code == 401:
                print("Lens: API key 无效或未配置")
                return []
            if r.status_code != 200:
                print(f"Lens: 请求失败，状态码 {r.status_code}")
                return []

            data = r.json()
            papers = []
            for hit in data.get("hits", {}).get("hits", []):
                try:
                    source = hit.get("_source", {})
                    p = Paper(source="lens")

                    if patent_mode:
                        # 专利解析
                        p.doc_type = "patent"
                        p.title = source.get("title", "") or ""
                        p.abstract = source.get("abstract", "") or ""
                        p.year = 0
                        pub_year = source.get("date_published")
                        if pub_year:
                            try:
                                p.year = int(pub_year[:4])
                            except (ValueError, TypeError):
                                pass
                        # 专利号（用作标识）
                        patent_number = source.get("patent_number", "")
                        application_number = source.get("application_number", "")
                        p.doi = patent_number or application_number
                        # 发明人
                        inventors = source.get("inventor", [])
                        if isinstance(inventors, list):
                            for inv in inventors[:10]:
                                if isinstance(inv, dict):
                                    name = (
                                        inv.get("name", "")
                                        or f"{inv.get('first_name', '')} {inv.get('last_name', '')}".strip()
                                    )
                                else:
                                    name = str(inv)
                                if name:
                                    p.authors.append(name)
                        # 申请人
                        applicants = source.get("applicant", [])
                        if isinstance(applicants, list):
                            for app in applicants[:5]:
                                if isinstance(app, dict):
                                    name = app.get("name", "") or ""
                                else:
                                    name = str(app)
                                if name:
                                    p.journal = name  # 复用 journal 字段存储申请人
                                    break
                        # IPC 分类号
                        ipc = source.get("IPCR", [])
                        if isinstance(ipc, list):
                            p.keywords = [str(k) for k in ipc[:10]]
                        # 全文链接
                        p.oa_url = (
                            source.get("granted_bibliographic_data_url", "") or ""
                        )
                    else:
                        # 学术文献解析（保持原有逻辑）
                        p.doc_type = "paper"
                        p.title = source.get("title", "") or ""
                        p.abstract = source.get("abstract", "") or ""
                        p.doi = source.get("doi", "") or ""
                        p.year = 0
                        pub_year = source.get("year_published")
                        if pub_year:
                            try:
                                p.year = int(pub_year)
                            except (ValueError, TypeError):
                                pass
                        # 作者
                        authors = source.get("authors", [])
                        if isinstance(authors, list):
                            for a in authors[:10]:
                                if isinstance(a, dict):
                                    name = (
                                        a.get("display_name", "")
                                        or f"{a.get('first_name', '')} {a.get('last_name', '')}".strip()
                                    )
                                    # 提取机构信息
                                    for aff in a.get("affiliations", []):
                                        if isinstance(aff, dict):
                                            aff_name = aff.get("name", "")
                                        else:
                                            aff_name = str(aff)
                                        if aff_name and aff_name not in p.affiliations:
                                            p.affiliations.append(aff_name)
                                else:
                                    name = str(a)
                                if name:
                                    p.authors.append(name)
                        # 期刊
                        p.journal = source.get("journal", {}).get("title", "") or ""
                        # 卷/期/页码
                        vol = source.get("volume", "")
                        if vol:
                            p.volume = str(vol)
                        iss = source.get("issue", "")
                        if iss:
                            p.issue = str(iss)
                        pg = source.get("page", "") or source.get("pages", "")
                        if pg:
                            p.pages = str(pg)
                        # 引用数
                        p.citation_count = (
                            source.get("scholarly_citations_count", 0) or 0
                        )
                        # 关键词
                        keywords = source.get("keywords", [])
                        if isinstance(keywords, list):
                            p.keywords = [str(k) for k in keywords[:10]]
                        # OA 链接
                        p.oa_url = source.get("open_access", {}).get("url", "") or ""

                    if p.title:
                        papers.append(p)
                except Exception:
                    continue
            return papers
        except Exception as e:
            print(f"Lens search error: {e}")
            return []


class UnpaywallCache:
    """线程安全的 DOI → OA URL 缓存（带文件持久化和自动过期）

    特性：
    - 内存缓存 + 文件持久化（~/.paperlens/unpaywall_cache.json）
    - 线程安全（threading.Lock）
    - LRU 淘汰（超过 maxsize 时淘汰最久未访问的条目）
    - 自动过期：30天未更新的缓存条目自动清理
    """

    CACHE_TTL_DAYS = 30  # 缓存有效期（天）

    def __init__(self, cache_file: str = None, maxsize: int = 50000):
        self._cache: OrderedDict = OrderedDict()  # doi -> {"url": str, "ts": float}
        self._cache_file = cache_file
        self._maxsize = maxsize
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._load_cache()

    def _load_cache(self):
        if not self._cache_file:
            return
        try:
            import json
            import os
            import time

            if os.path.exists(self._cache_file):
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 兼容旧格式：直接 dict（无时间戳）
                if isinstance(data, dict):
                    now = time.time()
                    ttl_seconds = self.CACHE_TTL_DAYS * 86400
                    expired_count = 0
                    for doi, val in data.items():
                        if isinstance(val, dict) and "ts" in val:
                            # 新格式：检查是否过期
                            if now - val["ts"] < ttl_seconds:
                                self._cache[doi] = val
                            else:
                                expired_count += 1
                        else:
                            # 旧格式：直接 URL 字符串，添加时间戳
                            self._cache[doi] = {"url": val, "ts": now}
                    if expired_count > 0:
                        print(f"[INFO] Unpaywall 缓存已清理 {expired_count} 条过期条目")
                        self._save_cache()
                print(f"[INFO] Unpaywall 缓存已加载: {len(self._cache)} 条")
        except Exception as e:
            print(f"[WARN] 加载 Unpaywall 缓存失败: {e}")

    def _save_cache(self):
        if not self._cache_file:
            return
        try:
            import json
            import os

            os.makedirs(os.path.dirname(self._cache_file), exist_ok=True)
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(dict(self._cache), f, ensure_ascii=False)
        except Exception as e:
            print(f"[WARN] 保存 Unpaywall 缓存失败: {e}")

    def get(self, doi: str) -> Optional[str]:
        import time

        with self._lock:
            entry = self._cache.get(doi)
            if entry is not None:
                # 检查是否过期
                if time.time() - entry["ts"] >= self.CACHE_TTL_DAYS * 86400:
                    del self._cache[doi]
                    self._misses += 1
                    return None
                self._hits += 1
                self._cache.move_to_end(doi)
                return entry["url"]
            else:
                self._misses += 1
                return None

    def put(self, doi: str, oa_url: str):
        import time

        with self._lock:
            if doi in self._cache:
                self._cache.move_to_end(doi)
                self._cache[doi] = {"url": oa_url, "ts": time.time()}
            else:
                if len(self._cache) >= self._maxsize:
                    self._cache.popitem(last=False)
                self._cache[doi] = {"url": oa_url, "ts": time.time()}
            # 每 500 条写一次文件（降低 IO）
            if (self._hits + self._misses) % 500 == 0:
                self._save_cache()

    def flush(self):
        """显式写盘"""
        with self._lock:
            self._save_cache()

    def cleanup_expired(self) -> int:
        """手动清理过期缓存，返回清理条数"""
        import time

        with self._lock:
            now = time.time()
            ttl_seconds = self.CACHE_TTL_DAYS * 86400
            expired = [
                doi
                for doi, entry in self._cache.items()
                if now - entry["ts"] >= ttl_seconds
            ]
            for doi in expired:
                del self._cache[doi]
            if expired:
                self._save_cache()
            return len(expired)

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": f"{(self._hits / total * 100):.1f}%"
                if total > 0
                else "N/A",
            }


class UnpaywallSearch:
    """Unpaywall OA 全文链接查询

    API 文档：https://unpaywall.org/products/api
    免费，只需提供邮箱作为用户标识。
    每个 DOI 返回 OA 链接（best-oa-location.url_for_pdf > url_for_landing_page）。
    """

    BASE = "https://api.unpaywall.org/v2"

    def __init__(self, email: str = "", proxy=None):
        self.email = email
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "PaperLens/1.0"
        if proxy:
            self.session.proxies = proxy
        # 初始化缓存
        from pathlib import Path

        cache_dir = Path.home() / ".paperlens"
        cache_file = str(cache_dir / "unpaywall_cache.json")
        self._cache = UnpaywallCache(cache_file=cache_file)

    def _query_one(self, doi: str) -> Optional[str]:
        """查询单个 DOI 的 OA 链接（带重试）"""
        # 先查缓存
        cached = self._cache.get(doi)
        if cached is not None:
            return cached

        if not self.email:
            return None

        url = f"{self.BASE}/{doi}?email={self.email}"
        try:
            r = None
            for attempt in range(3):
                r = self.session.get(url, timeout=10)
                if r.status_code == 429:
                    wait = min(2**attempt, 5)
                    time.sleep(wait)
                    continue
                break
            if r is None or r.status_code != 200:
                # 404 表示 DOI 不在 Unpaywall 数据库中，缓存空值避免重复查询
                if r and r.status_code == 404:
                    self._cache.put(doi, "")
                return None

            data = r.json()
            best_oa = data.get("best_oa_location")
            if not best_oa:
                self._cache.put(doi, "")
                return None

            # 优先 PDF 链接，其次 landing page
            oa_url = (
                best_oa.get("url_for_pdf") or best_oa.get("url_for_landing_page") or ""
            )
            self._cache.put(doi, oa_url)
            return oa_url

        except Exception as e:
            print(f"[WARN] Unpaywall query error for {doi}: {e}")
            return None

    def enrich_papers(self, papers: list, max_workers: int = 4) -> list:
        """批量查询 OA 链接，填充缺少 oa_url 的论文

        Args:
            papers: Paper 列表
            max_workers: 并发线程数

        Returns:
            list: 同一 papers 列表（原地修改）
        """
        # 只处理有 DOI 且缺少 oa_url 的论文
        needs_enrich = [p for p in papers if p.doi and not p.oa_url]
        if not needs_enrich:
            return papers

        print(f"[Unpaywall] 需要查询 {len(needs_enrich)} 篇论文的 OA 链接")

        def _fetch(paper):
            oa_url = self._query_one(paper.doi)
            if oa_url:
                paper.oa_url = oa_url

        with ThreadPoolExecutor(
            max_workers=min(max_workers, len(needs_enrich))
        ) as executor:
            list(executor.map(_fetch, needs_enrich))

        # 刷新缓存到磁盘
        self._cache.flush()

        stats = self._cache.stats()
        enriched = sum(1 for p in needs_enrich if p.oa_url)
        print(
            f"[Unpaywall] 完成: {enriched}/{len(needs_enrich)} 获取到 OA 链接 | "
            f"缓存 {stats['size']} 条, 命中率 {stats['hit_rate']}"
        )

        return papers


class JstageSearch:
    """J-STAGE 日本学术论文搜索（JST 免费 API）

    API 文档：https://api.jstage.jst.go.jp
    免费开放，无需 API key。收录日本学术期刊论文，支持日文/英文关键词。
    API 返回 Atom XML 或 JSON，使用 OpenSearch 分页。
    """

    BASE = "https://api.jstage.jst.go.jp/searchapi/do"

    def __init__(self, proxy=None):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "PaperLens/1.0"
        if proxy:
            self.session.proxies = proxy

    def search(
        self, query: str, year_from=0, year_to=0, max_results=20, field=""
    ) -> list:
        if not year_to:
            year_to = datetime.now().year

        try:
            # 作者搜索：使用 author 关键字
            if field == "au":
                search_query = f"author:{query}"
            else:
                search_query = query
            params = {
                "service": 3,
                "keyword": search_query,
                "count": min(max_results, 50),
                "start": 1,
                "response": "json",
            }
            # J-STAGE API 原生年份过滤
            if year_from > 0:
                params["pubyearfrom"] = year_from
            if year_to > 0:
                params["pubyearto"] = year_to

            r = self.session.get(self.BASE, params=params, timeout=15)
            r.raise_for_status()

            # J-STAGE API 可能返回 XML 或 JSON，均需处理
            content_type = r.headers.get("Content-Type", "")
            if "json" in content_type:
                data = r.json()
                return self._parse_json(data, year_from, year_to)
            else:
                return self._parse_xml(r.text, year_from, year_to)

        except Exception as e:
            print(f"J-STAGE search error: {e}")
            return []

    def _parse_json(self, data: dict, year_from: int, year_to: int) -> list:
        """解析 JSON 格式响应"""
        papers = []
        entries = data.get("entry", [])
        if isinstance(entries, dict):
            entries = [entries]

        for item in entries:
            try:
                p = self._entry_to_paper(item, source="jstage")
                if not p.title:
                    continue
                if not self._year_in_range(p.year, year_from, year_to):
                    continue
                papers.append(p)
            except Exception:
                continue
        return papers

    def _parse_xml(self, xml_text: str, year_from: int, year_to: int) -> list:
        """解析 Atom XML 格式响应"""
        papers = []
        try:
            root = ET.fromstring(xml_text)
            ns = {
                "atom": "http://www.w3.org/2005/Atom",
                "jstage": "http://www.jstage.jst.go.jp/searchapi",
                "prism": "http://prismstandard.org/namespaces/basic/2.0/",
            }
            for entry in root.findall("atom:entry", ns):
                try:
                    item = self._xml_entry_to_dict(entry, ns)
                    p = self._entry_to_paper(item, source="jstage")
                    if not p.title:
                        continue
                    if not self._year_in_range(p.year, year_from, year_to):
                        continue
                    papers.append(p)
                except Exception:
                    continue
        except ET.ParseError as e:
            print(f"J-STAGE XML parse error: {e}")
        return papers

    def _xml_entry_to_dict(self, entry, ns: dict) -> dict:
        """将 XML entry 元素转换为与 JSON 格式一致的字典

        J-STAGE Atom XML 中，自定义元素（article_title, author,
        material_title, pubyear 等）使用 Atom 默认命名空间，
        prism 元素使用 prism 命名空间。
        """

        def _get(tag):
            el = entry.find(tag, ns)
            if el is None:
                return ""
            # 处理 CDATA 和普通文本
            text = "".join(el.itertext()).strip()
            return text

        def _get_lang_child(parent_tag, lang):
            """从父元素中按 lang 属性获取子元素文本"""
            parent = entry.find(parent_tag, ns)
            if parent is None:
                return ""
            for child in parent:
                child_lang = child.get("{http://www.w3.org/XML/1998/namespace}lang", "")
                if child_lang == lang:
                    text = "".join(child.itertext()).strip()
                    return text
            # 没找到指定 lang，取第一个有内容的子元素
            for child in parent:
                text = "".join(child.itertext()).strip()
                if text:
                    return text
            return ""

        def _get_authors(lang):
            """获取指定语言的作者列表"""
            authors = []
            author_el = entry.find("atom:author", ns)
            if author_el is None:
                return authors
            lang_el = None
            for child in author_el:
                child_lang = child.get("{http://www.w3.org/XML/1998/namespace}lang", "")
                if child_lang == lang:
                    lang_el = child
                    break
            if lang_el is None:
                # 回退：取第一个子元素
                lang_el = author_el.find("atom:en", ns) or next(iter(author_el), None)
            if lang_el is not None:
                for name_el in lang_el.findall("atom:name", ns):
                    text = "".join(name_el.itertext()).strip()
                    if text:
                        authors.append({"name": text})
            return authors

        # 从 entry id 提取 article_link
        entry_id = _get("atom:id")
        article_link = {"en": entry_id, "ja": entry_id}
        for link_el in entry.findall("atom:link", ns):
            href = link_el.get("href", "")
            if href:
                lang = link_el.get("{http://www.w3.org/XML/1998/namespace}lang", "en")
                if lang == "ja":
                    article_link["ja"] = href
                else:
                    article_link["en"] = href

        return {
            "article_title": {
                "en": _get_lang_child("atom:article_title", "en"),
                "ja": _get_lang_child("atom:article_title", "ja"),
            },
            "article_link": article_link,
            "author": {
                "en": _get_authors("en"),
                "ja": _get_authors("ja"),
            },
            "material_title": {
                "en": _get_lang_child("atom:material_title", "en"),
                "ja": _get_lang_child("atom:material_title", "ja"),
            },
            "pubyear": _get("atom:pubyear"),
            "prism:doi": _get("prism:doi"),
            "prism:volume": _get("prism:volume"),
            "prism:number": _get("prism:number"),
            "prism:startingPage": _get("prism:startingPage"),
            "prism:endingPage": _get("prism:endingPage"),
            "prism:issn": _get("prism:issn"),
        }

    @staticmethod
    def _entry_to_paper(item: dict, source: str = "jstage") -> Paper:
        """将 J-STAGE entry 字典转换为 Paper 对象"""
        p = Paper(source=source)

        # 标题：优先英文，回退日文
        title_obj = item.get("article_title", {})
        if isinstance(title_obj, dict):
            p.title = title_obj.get("en") or title_obj.get("ja") or ""
        else:
            p.title = str(title_obj) if title_obj else ""
        if not p.title:
            return p

        # 作者：优先英文，回退日文
        author_obj = item.get("author", {})
        if isinstance(author_obj, dict):
            author_list = author_obj.get("en") or author_obj.get("ja") or []
        else:
            author_list = author_obj if isinstance(author_obj, list) else []
        for author in author_list:
            name = author.get("name", "") if isinstance(author, dict) else str(author)
            if name:
                p.authors.append(name)

        # 期刊名：优先英文，回退日文
        journal_obj = item.get("material_title", {})
        if isinstance(journal_obj, dict):
            p.journal = journal_obj.get("en") or journal_obj.get("ja") or ""
        else:
            p.journal = str(journal_obj) if journal_obj else ""

        # 年份
        try:
            p.year = int(item.get("pubyear", 0) or 0)
        except (ValueError, TypeError):
            p.year = 0

        # DOI
        p.doi = item.get("prism:doi", "") or ""

        # 卷/期/页
        p.volume = item.get("prism:volume", "") or ""
        p.issue = item.get("prism:number", "") or ""
        start_page = item.get("prism:startingPage", "") or ""
        end_page = item.get("prism:endingPage", "") or ""
        if start_page:
            p.pages = f"{start_page}-{end_page}" if end_page else start_page

        # ISSN
        p.issn = item.get("prism:issn", "") or ""
        # 摘要（J-STAGE JSON 响应中的 description 字段）
        abstract = item.get("description", "") or ""
        if abstract:
            p.abstract = abstract.strip()[:500]

        # 文章链接
        link_obj = item.get("article_link", {})
        if isinstance(link_obj, dict):
            p.oa_url = link_obj.get("en") or link_obj.get("ja") or ""
        else:
            p.oa_url = str(link_obj) if link_obj else ""

        return p

    @staticmethod
    def _year_in_range(year: int, year_from: int, year_to: int) -> bool:
        """检查年份是否在指定范围内（year=0 表示未知年份，不过滤）"""
        if year == 0:
            return True
        if year_from > 0 and year < year_from:
            return False
        if year_to > 0 and year > year_to:
            return False
        return True


class _SearchResultCache:
    """线程安全的搜索结果 LRU 缓存（带 TTL）

    特性：
    - LRU 淘汰策略（超过 maxsize 时淘汰最久未访问的条目）
    - TTL 过期机制（默认 30 分钟）
    - 线程安全（threading.Lock）
    - 命中/未命中统计
    """

    def __init__(self, maxsize: int = 100, ttl: int = 1800):
        """
        Args:
            maxsize: 最大缓存条目数
            ttl: 缓存有效期（秒），默认 1800 = 30 分钟
        """
        self._cache: OrderedDict = OrderedDict()
        self._maxsize = maxsize
        self._ttl = ttl
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._persistent = None  # L2 持久化缓存（可选）

    @staticmethod
    def _make_key(query: str, year_from, year_to, sources_hash: str) -> str:
        """生成缓存 key（查询规范化：去标点/连字符/多余空格）"""
        q = query.strip().lower()
        q = re.sub(r"[^\w\s]", " ", q)  # 标点→空格
        q = re.sub(r"\s+", " ", q).strip()  # 合并空格
        raw = f"{q}|{year_from}|{year_to}|{sources_hash}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def get(self, query: str, year_from, year_to, sources_hash: str):
        """查询缓存，命中返回结果，未命中返回 None。
        优先精确匹配，miss 时尝试年份超集（±1年扩展）提高命中率。
        """
        key = self._make_key(query, year_from, year_to, sources_hash)
        now = time.time()
        with self._lock:
            # 精确匹配
            entry = self._cache.get(key)
            if entry is not None and now - entry["ts"] <= self._ttl:
                papers = entry["papers"]
                if papers and not isinstance(papers[0], Paper):
                    del self._cache[key]
                else:
                    self._cache.move_to_end(key)
                    self._hits += 1
                    return papers
            # 年份超集回退：±1 年扩展
            for dy in [(1, 0), (0, 1), (1, 1)]:
                super_key = self._make_key(
                    query, max(year_from - dy[0], 0), year_to + dy[1], sources_hash
                )
                entry = self._cache.get(super_key)
                if entry is not None and now - entry["ts"] <= self._ttl:
                    # 过滤到目标年份范围
                    papers = [
                        p
                        for p in entry["papers"]
                        if (not p.year) or (p.year >= year_from and p.year <= year_to)
                    ]
                    if papers:
                        # 回填精确 key
                        self._cache[key] = {"papers": papers, "ts": now}
                        return papers
                    papers = entry["papers"]
                    # 防御性检查：确保缓存中都是 Paper 对象
                    if papers and not isinstance(papers[0], Paper):
                        del self._cache[key]
                        self._misses += 1
                        return None
                    # 命中：移到末尾（最近使用）
                    self._cache.move_to_end(key)
                    self._hits += 1
                    return papers
            self._misses += 1

        # L1 miss → 尝试 L2（SQLite）
        if self._persistent is not None:
            l2_result = self._persistent.get(key)
            if l2_result is not None:
                # 防御性检查：确保 L2 返回的都是 Paper 对象
                valid_papers = [p for p in l2_result if isinstance(p, Paper)]
                if not valid_papers:
                    print("[WARN] L2 cache returned no valid Paper objects, skipping")
                    return None
                # L2 命中：回填 L1
                with self._lock:
                    if key in self._cache:
                        del self._cache[key]
                    while len(self._cache) >= self._maxsize:
                        self._cache.popitem(last=False)
                    self._cache[key] = {"papers": valid_papers, "ts": now}
                self._hits += 1  # 补偿 L1 miss 的计数
                return valid_papers

        return None

    def put(self, query: str, year_from, year_to, sources_hash: str, papers):
        """写入缓存（同时写 L1 内存 + L2 SQLite）"""
        key = self._make_key(query, year_from, year_to, sources_hash)
        now = time.time()
        with self._lock:
            # 如果 key 已存在，先删除（更新为最新）
            if key in self._cache:
                del self._cache[key]
            # LRU 淘汰：超过容量时删除最久未访问的条目
            while len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)
            self._cache[key] = {"papers": papers, "ts": now}

        # 异步写入 L2（SQLite）
        if self._persistent is not None:
            self._persistent.put(key, query, papers)

    def stats(self) -> dict:
        """返回缓存统计信息"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0
            return {
                "size": len(self._cache),
                "maxsize": self._maxsize,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": f"{hit_rate:.1f}%",
                "ttl_seconds": self._ttl,
            }

    def clear(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def set_persistent_cache(self, persistent_cache):
        """设置 L2 持久化缓存

        Args:
            persistent_cache: SQLiteSearchCache 实例
        """
        self._persistent = persistent_cache


class SQLiteSearchCache:
    """SQLite 持久化搜索结果缓存（L2 层）

    特性：
    - SQLite 存储，重启后保留历史搜索
    - FTS5 全文索引，支持搜索历史检索
    - 后台线程异步写入，不阻塞搜索响应
    - 7天自动过期清理
    - 线程安全

    与 _SearchResultCache (L1 内存缓存) 共存：
    - L1 miss → 查 L2 → 命中则回填 L1
    - 写入时同时写 L1 + L2
    """

    def __init__(self, db_path: str = None, ttl_days: int = 7):
        """
        Args:
            db_path: SQLite 数据库文件路径，默认 ~/.paperlens/search_cache.db
            ttl_days: 缓存过期天数，默认 7 天
        """
        import sqlite3
        from pathlib import Path

        self._ttl_seconds = ttl_days * 86400
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

        if db_path is None:
            cache_dir = Path.home() / ".paperlens"
            cache_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(cache_dir / "search_cache.db")
        self._db_path = db_path

        # 初始化数据库表和 FTS 索引
        conn = sqlite3.connect(db_path, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_hash TEXT UNIQUE NOT NULL,
                    query_text TEXT NOT NULL,
                    results_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_query_hash ON search_cache(query_hash)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_expires_at ON search_cache(expires_at)
            """)
            # FTS5 全文索引（对 query_text 建索引）
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS search_cache_fts
                USING fts5(query_text, content='search_cache', content_rowid='id')
            """)
            # 触发器：写入时同步 FTS
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS search_cache_ai
                AFTER INSERT ON search_cache BEGIN
                    INSERT INTO search_cache_fts(rowid, query_text)
                    VALUES (new.id, new.query_text);
                END
            """)
            # 触发器：删除时同步 FTS
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS search_cache_ad
                AFTER DELETE ON search_cache BEGIN
                    INSERT INTO search_cache_fts(search_cache_fts, rowid, query_text)
                    VALUES ('delete', old.id, old.query_text);
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS search_cache_au
                AFTER UPDATE ON search_cache BEGIN
                    INSERT INTO search_cache_fts(search_cache_fts, rowid, query_text)
                    VALUES ('delete', old.id, old.query_text);
                    INSERT INTO search_cache_fts(rowid, query_text)
                    VALUES (new.id, new.query_text);
                END
            """)
            conn.commit()
            print(f"[INFO] SQLite 搜索缓存已初始化: {db_path}")
        finally:
            conn.close()

        # 启动后台清理线程（每小时清理过期条目）
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="search-cache-cleanup"
        )
        self._cleanup_thread.start()

    def _get_conn(self):
        """获取数据库连接"""
        import sqlite3

        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def get(self, query_hash: str):
        """查询持久化缓存

        Args:
            query_hash: 缓存 key（MD5 hash）

        Returns:
            results list or None
        """
        import json

        now = time.time()
        try:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT results_json, expires_at FROM search_cache WHERE query_hash = ?",
                    (query_hash,),
                ).fetchone()
                if row is None:
                    self._misses += 1
                    return None
                results_json, expires_at = row
                if now > expires_at:
                    # 已过期，删除
                    conn.execute(
                        "DELETE FROM search_cache WHERE query_hash = ?", (query_hash,)
                    )
                    conn.commit()
                    self._misses += 1
                    return None
                self._hits += 1
                raw = json.loads(results_json)
                # 兼容旧缓存：如果元素是 dict 则反序列化为 Paper，否则丢弃无效条目
                if isinstance(raw, list):
                    papers = []
                    for item in raw:
                        if isinstance(item, dict):
                            p = _dict_to_paper(item)
                            if p:
                                papers.append(p)
                        # 跳过非 dict 元素（旧缓存中的字符串表示）
                    return papers if papers else None
                return None
            finally:
                conn.close()
        except Exception as e:
            print(f"[WARN] SQLite 缓存读取失败: {e}")
            self._misses += 1
            return None

    def put(self, query_hash: str, query_text: str, papers):
        """异步写入持久化缓存

        Args:
            query_hash: 缓存 key
            query_text: 原始查询文本（用于 FTS 检索）
            papers: 搜索结果列表
        """
        # 在后台线程执行写入，不阻塞搜索响应
        thread = threading.Thread(
            target=self._put_sync,
            args=(query_hash, query_text, papers),
            daemon=True,
            name="search-cache-write",
        )
        thread.start()

    def _put_sync(self, query_hash: str, query_text: str, papers):
        """同步写入（在后台线程中执行）"""
        import json

        try:
            now = time.time()
            expires_at = now + self._ttl_seconds
            # 将 Paper 对象序列化为 dict 列表，确保可完整反序列化
            serializable = [
                _paper_to_dict(p) if isinstance(p, Paper) else p for p in papers
            ]
            results_json = json.dumps(serializable, ensure_ascii=False)

            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO search_cache
                       (query_hash, query_text, results_json, created_at, expires_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (query_hash, query_text, results_json, now, expires_at),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"[WARN] SQLite 缓存写入失败: {e}")

    def search_history(self, keyword: str, limit: int = 20) -> list:
        """全文检索历史搜索

        Args:
            keyword: 搜索关键词
            limit: 最大返回条数

        Returns:
            list of dicts: [{"query_text": str, "created_at": float, "result_count": int}]
        """
        import json

        now = time.time()
        try:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    """SELECT sc.query_text, sc.created_at, sc.results_json
                       FROM search_cache_fts fts
                       JOIN search_cache sc ON sc.id = fts.rowid
                       WHERE search_cache_fts MATCH ? AND sc.expires_at > ?
                       ORDER BY sc.created_at DESC LIMIT ?""",
                    (keyword, now, limit),
                ).fetchall()
                results = []
                for query_text, created_at, results_json in rows:
                    papers = json.loads(results_json)
                    results.append(
                        {
                            "query_text": query_text,
                            "created_at": created_at,
                            "result_count": len(papers)
                            if isinstance(papers, list)
                            else 0,
                        }
                    )
                return results
            finally:
                conn.close()
        except Exception as e:
            print(f"[WARN] SQLite 历史搜索检索失败: {e}")
            return []

    def _cleanup_loop(self):
        """后台定期清理过期条目"""
        import sqlite3

        while True:
            time.sleep(3600)  # 每小时执行一次
            try:
                conn = sqlite3.connect(self._db_path, check_same_thread=False)
                try:
                    now = time.time()
                    cursor = conn.execute(
                        "DELETE FROM search_cache WHERE expires_at < ?", (now,)
                    )
                    deleted = cursor.rowcount
                    conn.commit()
                    if deleted > 0:
                        print(f"[INFO] SQLite 搜索缓存清理: 删除 {deleted} 条过期记录")
                finally:
                    conn.close()
            except Exception as e:
                print(f"[WARN] SQLite 缓存清理失败: {e}")

    def stats(self) -> dict:
        """返回持久化缓存统计信息"""
        import sqlite3

        try:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM search_cache WHERE expires_at > ?",
                    (time.time(),),
                ).fetchone()
                total = row[0] if row else 0
                return {
                    "size": total,
                    "hits": self._hits,
                    "misses": self._misses,
                    "db_path": self._db_path,
                }
            finally:
                conn.close()
        except Exception:
            return {"size": 0, "hits": self._hits, "misses": self._misses}

    def clear(self):
        """清空所有持久化缓存"""
        import sqlite3

        try:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            try:
                conn.execute("DELETE FROM search_cache")
                conn.commit()
                self._hits = 0
                self._misses = 0
                print("[INFO] SQLite 搜索缓存已清空")
            finally:
                conn.close()
        except Exception as e:
            print(f"[WARN] SQLite 缓存清空失败: {e}")


class SourceHealthMonitor:
    """数据源健康监控器

    跟踪每个数据源的响应时间和成功率，自动禁用不健康的源。

    健康状态：
    - green:  正常（成功率 >= 80%，平均响应时间 < 15s）
    - yellow: 退化（成功率 50%-80%，或平均响应时间 15-30s）
    - red:    异常（成功率 < 50%，或平均响应时间 > 30s，或连续失败 >= 3 次）
    - disabled: 已禁用（自动禁用或手动禁用）

    参数：
    - max_history: 保留最近 N 次搜索记录（默认 20）
    - slow_threshold: 响应时间慢阈值（秒，默认 15）
    - very_slow_threshold: 响应时间极慢阈值（秒，默认 30）
    - low_success_rate: 低成功率阈值（默认 0.5）
    - normal_success_rate: 正常成功率阈值（默认 0.8）
    - consecutive_fail_threshold: 连续失败自动禁用阈值（默认 3）
    """

    def __init__(
        self,
        max_history: int = 20,
        slow_threshold: float = 15.0,
        very_slow_threshold: float = 30.0,
        low_success_rate: float = 0.5,
        normal_success_rate: float = 0.8,
        consecutive_fail_threshold: int = 3,
    ):
        self._lock = threading.Lock()
        self._max_history = max_history
        self._slow_threshold = slow_threshold
        self._very_slow_threshold = very_slow_threshold
        self._low_success_rate = low_success_rate
        self._normal_success_rate = normal_success_rate
        self._consecutive_fail_threshold = consecutive_fail_threshold

        # 每个源的历史记录：{source_name: [{"success": bool, "time": float, "timestamp": float}]}
        self._history: dict = {}
        # 手动禁用的源
        self._manually_disabled: set = set()
        # 自动禁用的源
        self._auto_disabled: set = set()
        # 所有已知的源（包括有记录的和被禁用的）
        self._known_sources: set = set()

    def record(self, source_name: str, success: bool, response_time: float):
        """记录一次搜索结果

        Args:
            source_name: 数据源名称
            success: 是否成功
            response_time: 响应时间（秒）
        """
        with self._lock:
            self._known_sources.add(source_name)
            if source_name not in self._history:
                self._history[source_name] = []
            self._history[source_name].append(
                {
                    "success": success,
                    "time": response_time,
                    "timestamp": time.time(),
                }
            )
            # 保留最近 N 条记录
            if len(self._history[source_name]) > self._max_history:
                self._history[source_name] = self._history[source_name][
                    -self._max_history :
                ]

            # 检查是否需要自动禁用
            if source_name not in self._manually_disabled:
                self._check_auto_disable(source_name)

    def _check_auto_disable(self, source_name: str):
        """检查是否需要自动禁用源（调用时需持有锁）"""
        history = self._history.get(source_name, [])
        if len(history) < 3:
            return  # 记录太少，不做判断

        # 检查连续失败
        consecutive_fails = 0
        for record in reversed(history):
            if not record["success"]:
                consecutive_fails += 1
            else:
                break
        if consecutive_fails >= self._consecutive_fail_threshold:
            self._auto_disabled.add(source_name)
            print(
                f"[HEALTH] Auto-disabled {source_name}: {consecutive_fails} consecutive failures"
            )
            return

        # 检查成功率和响应时间
        status = self._compute_status(history)
        if status == "red":
            self._auto_disabled.add(source_name)
            print(f"[HEALTH] Auto-disabled {source_name}: status=red")

    def _compute_status(self, history: list) -> str:
        """计算健康状态（调用时需持有锁或传入副本）"""
        if not history:
            return "green"

        total = len(history)
        successes = sum(1 for r in history if r["success"])
        success_rate = successes / total if total > 0 else 1.0
        avg_time = sum(r["time"] for r in history) / total if total > 0 else 0

        # 红色：成功率 < 50% 或平均响应时间 > 30s
        if (
            success_rate < self._low_success_rate
            or avg_time > self._very_slow_threshold
        ):
            return "red"

        # 黄色：成功率 50%-80% 或平均响应时间 15-30s
        if success_rate < self._normal_success_rate or avg_time > self._slow_threshold:
            return "yellow"

        return "green"

    def is_enabled(self, source_name: str) -> bool:
        """检查源是否可用（未被禁用）"""
        with self._lock:
            if source_name in self._manually_disabled:
                return False
            if source_name in self._auto_disabled:
                return False
            return True

    def enable(self, source_name: str):
        """手动启用源"""
        with self._lock:
            self._known_sources.add(source_name)
            self._manually_disabled.discard(source_name)
            self._auto_disabled.discard(source_name)

    def disable(self, source_name: str):
        """手动禁用源"""
        with self._lock:
            self._known_sources.add(source_name)
            self._manually_disabled.add(source_name)

    def get_status(self, source_name: str) -> str:
        """获取源的健康状态"""
        with self._lock:
            if source_name in self._manually_disabled:
                return "disabled"
            if source_name in self._auto_disabled:
                return "disabled"
            history = self._history.get(source_name, [])
            return self._compute_status(list(history))

    def get_all_status(self) -> dict:
        """获取所有源的健康状态

        Returns:
            dict: {source_name: {"status": str, "success_rate": float,
                   "avg_time": float, "total": int, "successes": int,
                   "auto_disabled": bool, "manually_disabled": bool}}
        """
        with self._lock:
            result = {}
            # 使用已知源集合（包括有记录的和被禁用的）
            for source_name in self._known_sources:
                history = self._history.get(source_name, [])
                total = len(history)
                successes = sum(1 for r in history if r["success"])
                success_rate = successes / total if total > 0 else 1.0
                avg_time = sum(r["time"] for r in history) / total if total > 0 else 0

                if source_name in self._manually_disabled:
                    status = "disabled"
                elif source_name in self._auto_disabled:
                    status = "disabled"
                else:
                    status = self._compute_status(list(history))

                result[source_name] = {
                    "status": status,
                    "success_rate": round(success_rate * 100, 1),
                    "avg_time": round(avg_time, 2),
                    "total": total,
                    "successes": successes,
                    "auto_disabled": source_name in self._auto_disabled,
                    "manually_disabled": source_name in self._manually_disabled,
                }
            return result

    def reset(self, source_name: str = None):
        """重置源的历史记录和禁用状态

        Args:
            source_name: 指定源名，None 则重置全部
        """
        with self._lock:
            if source_name:
                self._history.pop(source_name, None)
                self._auto_disabled.discard(source_name)
                self._manually_disabled.discard(source_name)
                self._known_sources.discard(source_name)
            else:
                self._history.clear()
                self._auto_disabled.clear()
                self._manually_disabled.clear()
                self._known_sources.clear()


class BM25Scorer:
    """简化版 BM25 相关性评分器

    基于搜索结果集动态计算 IDF（逆文档频率），支持标题/摘要差异化权重。
    线程安全：所有状态更新通过 threading.Lock 保护。

    参数:
        k1: 词频饱和参数（默认 1.5），控制 TF 增长的饱和速度
        b:  文档长度归一化参数（默认 0.75），0=不归一化，1=完全归一化
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._lock = threading.Lock()

        # IDF 缓存：{term: idf_value}
        self._idf_cache: dict = {}
        # 文档统计
        self.doc_count: int = 0
        self.avg_title_len: float = 0.0
        self.avg_abstract_len: float = 0.0
        # 就绪标志
        self._ready: bool = False

    def build_from_papers(self, papers: list, keywords: set):
        """从论文列表构建 IDF 索引

        Args:
            papers: Paper 对象列表
            keywords: 搜索关键词集合
        """
        with self._lock:
            self._idf_cache = {}
            self._ready = False

            if not papers or not keywords:
                return

            n = len(papers)
            self.doc_count = n

            # 统计每个关键词出现在多少篇文档中
            doc_freq: dict = {}
            total_title_len = 0
            total_abstract_len = 0

            for paper in papers:
                title = (paper.title or "").lower()
                abstract = (paper.abstract or "").lower()
                total_title_len += len(title.split()) if title else 0
                total_abstract_len += len(abstract.split()) if abstract else 0

                # 记录每个关键词在当前文档中是否出现（标题或摘要）
                title_set = set(title.split()) if title else set()
                abstract_set = set(abstract.split()) if abstract else set()
                doc_tokens = title_set | abstract_set

                for kw in keywords:
                    kw_lower = kw.lower()
                    if kw_lower in doc_tokens:
                        doc_freq[kw_lower] = doc_freq.get(kw_lower, 0) + 1

            self.avg_title_len = total_title_len / max(n, 1)
            self.avg_abstract_len = total_abstract_len / max(n, 1)

            # 计算 IDF：log((N - df + 0.5) / (df + 0.5) + 1)
            # 加 1 避免负值，+1 在 log 内确保非负
            for kw in keywords:
                kw_lower = kw.lower()
                df = doc_freq.get(kw_lower, 0)
                # BM25 标准 IDF，加平滑防止除零
                idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
                self._idf_cache[kw_lower] = max(idf, 0.1)  # 最小 IDF 保底

            self._ready = True

    def is_ready(self) -> bool:
        """检查 IDF 索引是否就绪"""
        return self._ready

    def get_idf_cache(self) -> dict:
        """获取 IDF 缓存（只读副本）"""
        with self._lock:
            return dict(self._idf_cache)

    def reset(self):
        """重置索引状态"""
        with self._lock:
            self._idf_cache = {}
            self.doc_count = 0
            self.avg_title_len = 0.0
            self.avg_abstract_len = 0.0
            self._ready = False


# ============================================================
# 数据源适配器（将现有类适配为 BaseSearchSource 接口）
# ============================================================


@register_source
class PubMedSource(BaseSearchSource):
    """PubMed 数据源适配器"""

    SOURCE_NAME = "pubmed"
    DISPLAY_NAME = "PubMed"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = PubMedSearch(
            email=config.get("email", ""),
            api_key=config.get("api_key", ""),
            proxy=self.proxy,
        )

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        pmids, exact_doi = self._impl.search(
            query,
            year_from,
            year_to,
            sort=kwargs.get("sort", "relevance"),
            max_results=min(max_results, self.MAX_RESULTS),
            journal=kwargs.get("journal", ""),
            field=kwargs.get("field", ""),
            mesh_term=kwargs.get("mesh_term", ""),
            pub_type=kwargs.get("pub_type", ""),
        )
        papers = self._impl.fetch_details(pmids) if pmids else []
        if exact_doi:
            papers = [p for p in papers if p.doi and p.doi.lower() == exact_doi]
        return papers


@register_source
class OpenAlexSource(BaseSearchSource):
    """OpenAlex 数据源适配器"""

    SOURCE_NAME = "openalex"
    DISPLAY_NAME = "OpenAlex"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = OpenAlexSearch(
            email=config.get("email", ""),
            api_key=config.get("api_key", ""),
            proxy=self.proxy,
        )

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            journal=kwargs.get("journal", ""),
            field=kwargs.get("field", ""),
        )

    def enrich_with_citations(self, papers):
        return self._impl.enrich_with_citations(papers)

    @property
    def _last_keywords(self):
        return self._impl._last_keywords


@register_source
class GoogleScholarSource(BaseSearchSource):
    """Google Scholar 数据源适配器"""

    SOURCE_NAME = "google_scholar"
    DISPLAY_NAME = "Google Scholar"
    DEFAULT_ENABLED = False
    MAX_RESULTS = 20

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = GoogleScholarSearch(proxy=self.proxy)

    def search(self, query, year_from, year_to, max_results=20, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )

    def is_available(self):
        return self._impl._check_available()


@register_source
class CNKISource(BaseSearchSource):
    """中国知网数据源适配器"""

    SOURCE_NAME = "cnki"
    DISPLAY_NAME = "CNKI"
    DEFAULT_ENABLED = True
    IS_CHINESE = True
    MAX_RESULTS = 20

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = CNKISearch(
            proxy=self.proxy,
            access_proxy=self.access_proxy,
            cookies=self.carsi_cookies,
        )

    def search(self, query, year_from, year_to, max_results=20, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


@register_source
class WanfangSource(BaseSearchSource):
    """万方数据源适配器"""

    SOURCE_NAME = "wanfang"
    DISPLAY_NAME = "Wanfang"
    DEFAULT_ENABLED = True
    IS_CHINESE = True
    MAX_RESULTS = 20

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = WanfangSearch(
            proxy=self.proxy,
            cookie=config.get("cookie", ""),
            access_proxy=self.access_proxy,
            cookies=self.carsi_cookies,
            wanfang_cookies=config.get("cookies"),
        )

    def search(self, query, year_from, year_to, max_results=20, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


@register_source
class VIPSource(BaseSearchSource):
    """维普数据源适配器"""

    SOURCE_NAME = "vip"
    DISPLAY_NAME = "VIP"
    DEFAULT_ENABLED = True
    IS_CHINESE = True
    MAX_RESULTS = 20

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = VIPSearch(
            proxy=self.proxy,
            access_proxy=self.access_proxy,
            cookies=self.carsi_cookies,
        )

    def search(self, query, year_from, year_to, max_results=20, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


@register_source
class BingScholarSource(BaseSearchSource):
    """Bing 学术数据源适配器"""

    SOURCE_NAME = "bing_academic"
    DISPLAY_NAME = "Bing Academic"
    DEFAULT_ENABLED = False
    MAX_RESULTS = 20

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = BingScholarSearch(
            proxy=self.proxy,
            access_proxy=self.access_proxy,
        )

    def search(self, query, year_from, year_to, max_results=20, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


@register_source
class SemanticScholarSource(BaseSearchSource):
    """Semantic Scholar 数据源适配器"""

    SOURCE_NAME = "semantic_scholar"
    DISPLAY_NAME = "Semantic Scholar"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = SemanticScholarSearch(
            api_key=config.get("api_key", ""),
            proxy=self.proxy,
        )

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


@register_source
class CrossRefSource(BaseSearchSource):
    """CrossRef 数据源适配器"""

    SOURCE_NAME = "crossref"
    DISPLAY_NAME = "CrossRef"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = CrossRefSearch(
            email=config.get("email", ""),
            proxy=self.proxy,
        )

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


@register_source
class ArxivSource(BaseSearchSource):
    """arXiv 数据源适配器"""

    SOURCE_NAME = "arxiv"
    DISPLAY_NAME = "arXiv"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = ArxivSearch(proxy=self.proxy)

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


@register_source
class DBLPSource(BaseSearchSource):
    """DBLP 数据源适配器"""

    SOURCE_NAME = "dblp"
    DISPLAY_NAME = "DBLP"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = DBLPSearch(proxy=self.proxy)

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


@register_source
class BioRxivSource(BaseSearchSource):
    """bioRxiv 数据源适配器"""

    SOURCE_NAME = "biorxiv"
    DISPLAY_NAME = "bioRxiv"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = BioRxivSearch(proxy=self.proxy)

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


@register_source
class AgrisSource(BaseSearchSource):
    """AGRIS 数据源适配器 — API 已迁移，暂时禁用"""

    SOURCE_NAME = "agris"
    DISPLAY_NAME = "AGRIS"
    DEFAULT_ENABLED = False  # API 已下线，默认禁用
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = AgrisSearch(proxy=self.proxy)

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


@register_source
class PubAgSource(BaseSearchSource):
    """USDA PubAg 搜索源 — 替代已下线的 AGRIS，农业/生物/环境科学，免费 API"""

    SOURCE_NAME = "pubag"
    DISPLAY_NAME = "USDA PubAg"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 30
    BASE = "https://api.nal.usda.gov/pubag/rest"

    def search(
        self,
        query: str,
        year_from: int = 0,
        year_to: int = 0,
        max_results: int = 30,
        field="",
        **kwargs,
    ) -> list:
        try:
            # 作者搜索：使用 author: 前缀
            if field == "au":
                search_query = f"author:{query}"
            else:
                search_query = query
            params = {
                "query": search_query,
                "pageSize": min(max_results, 50),
                "format": "json",
            }
            r = requests.get(f"{self.BASE}/search", params=params, timeout=15)
            if r.status_code != 200:
                return []
            data = r.json()
            papers = []
            for hit in data.get("results", []):
                try:
                    p = Paper(source="pubag")
                    p.title = hit.get("title", "") or ""
                    if not p.title:
                        continue
                    p.doi = hit.get("doi", "") or ""
                    p.abstract = (hit.get("abstract", "") or "")[:5000]
                    p.journal = (
                        hit.get("journal", {}).get("name", "")
                        if isinstance(hit.get("journal"), dict)
                        else (hit.get("journal", "") or "")
                    )
                    authors = hit.get("authors", [])
                    p.authors = [
                        a.get("name", "")
                        or f"{a.get('firstName', '')} {a.get('lastName', '')}".strip()
                        for a in authors
                    ]
                    date = hit.get("publicationDate", "") or ""
                    if date:
                        try:
                            p.year = int(date[:4])
                        except ValueError:
                            pass
                    p.url = hit.get("url", "") or ""
                    papers.append(p)
                    if len(papers) >= max_results:
                        break
                except Exception:
                    continue
            return papers
        except Exception as e:
            print(f"PubAg search error: {e}")
            return []


@register_source
class EuropePMCSource(BaseSearchSource):
    """Europe PMC 数据源适配器"""

    SOURCE_NAME = "europepmc"
    DISPLAY_NAME = "Europe PMC"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = EuropePMCSearch(proxy=self.proxy)

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


@register_source
class CORESource(BaseSearchSource):
    """CORE 数据源适配器"""

    SOURCE_NAME = "core"
    DISPLAY_NAME = "CORE"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = CORESearch(
            api_key=config.get("api_key", ""),
            proxy=self.proxy,
        )

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


@register_source
class LensSource(BaseSearchSource):
    """Lens.org 数据源适配器"""

    SOURCE_NAME = "lens"
    DISPLAY_NAME = "Lens"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = LensSearch(
            api_key=config.get("api_key", ""),
            proxy=self.proxy,
        )

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        patent_mode = kwargs.get("patent_mode", False)
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            patent_mode=patent_mode,
            field=kwargs.get("field", ""),
        )


@register_source
class ScienceDirectSource(BaseSearchSource):
    """ScienceDirect 数据源适配器（需要 CARSI cookies）"""

    SOURCE_NAME = "sciencedirect"
    DISPLAY_NAME = "ScienceDirect"
    DEFAULT_ENABLED = True
    REQUIRES_COOKIES = True
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = ScienceDirectSearch(
            proxy=self.proxy,
            cookies=self.carsi_cookies,
        )

    def is_available(self):
        return bool(self.carsi_cookies)

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


@register_source
class ScopusSource(BaseSearchSource):
    """Scopus 数据源适配器（需要 CARSI cookies）"""

    SOURCE_NAME = "scopus"
    DISPLAY_NAME = "Scopus"
    DEFAULT_ENABLED = True
    REQUIRES_COOKIES = True
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = ScopusSearch(
            proxy=self.proxy,
            cookies=self.carsi_cookies,
        )

    def is_available(self):
        return bool(self.carsi_cookies)

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


@register_source
class JstorSource(BaseSearchSource):
    """JSTOR 数据源适配器（需要 CARSI cookies）"""

    SOURCE_NAME = "jstor"
    DISPLAY_NAME = "JSTOR"
    DEFAULT_ENABLED = True
    REQUIRES_COOKIES = True
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = JstorSearch(
            proxy=self.proxy,
            cookies=self.carsi_cookies,
        )

    def is_available(self):
        return bool(self.carsi_cookies)

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


@register_source
class UnpaywallSource(BaseSearchSource):
    """Unpaywall OA 全文链接适配器"""

    SOURCE_NAME = "unpaywall"
    DISPLAY_NAME = "Unpaywall"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = UnpaywallSearch(
            email=config.get("email", ""),
            proxy=self.proxy,
        )

    def is_available(self):
        return bool(self._impl.email)

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        # Unpaywall 是 OA 链接补充，不参与主搜索
        return []

    def enrich_papers(self, papers):
        return self._impl.enrich_papers(papers)


# ============================================================
# Cochrane Library 数据源（通过 PubMed 检索 Cochrane 系统综述）
# ============================================================


@register_source
class JstageSource(BaseSearchSource):
    """J-STAGE 日本学术论文数据源适配器"""

    SOURCE_NAME = "jstage"
    DISPLAY_NAME = "J-STAGE"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = JstageSearch(
            proxy=self.proxy,
        )

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


class CochraneSearch:
    """Cochrane 系统综述/Meta分析 检索（通过 PubMed E-utilities）

    Cochrane Library 本身无公开 REST API，但所有 Cochrane 系统综述
    均收录在 PubMed 中，可通过 publication type 过滤精确检索。

    检索范围：
    - Cochrane Database of Systematic Reviews (CDSR)
    - Cochrane 组发表的 Systematic Review
    """

    BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    # Cochrane 相关 publication type 标签
    COCHRANE_PT = [
        "Cochrane Database Syst Rev",
        "Systematic Review",
    ]

    def __init__(self, email="", api_key="", proxy=None):
        self.email = email
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "PaperLens/1.0"
        if proxy:
            self.session.proxies = proxy

    def search(
        self,
        query: str,
        year_from=2020,
        year_to=0,
        max_results=50,
        pub_type="",
        field="",
    ) -> list:
        """检索 Cochrane 系统综述，返回 Paper 列表

        Args:
            query: 检索词
            year_from: 起始年份
            year_to: 截止年份（0=当前年）
            max_results: 最大结果数
            pub_type: 额外文献类型过滤（如 "meta-analysis"）
            field: 搜索字段（"au" 表示作者搜索）
        """
        if not year_to:
            year_to = datetime.now().year

        # 构建 Cochrane 检索式：关键词 + publication type 过滤
        pt_terms = [f'"{pt}"[pt]' for pt in self.COCHRANE_PT]

        # 如果用户指定了额外文献类型（如 meta-analysis），也加入
        if pub_type:
            pt_terms.append(f'"{pub_type}"[pt]')

        # 用户关键词
        kw = query.strip()
        if not kw:
            return []

        # 检测是否是 DOI 查询
        doi_match = re.match(r"^(10\.\d{4,}/\S+)$", kw)
        if doi_match:
            term = f"{kw}[aid]"
        else:
            # 构建检索式：关键词 AND (Cochrane PT OR Systematic Review PT)
            pt_combined = " OR ".join(pt_terms)
            # 作者搜索：使用 [au] 标签
            if field == "au":
                author_query = f"{kw}[au]"
                term = f"({author_query}) AND ({pt_combined})"
            else:
                term = f"({kw}) AND ({pt_combined})"
            # 年份过滤
            if year_from > 0:
                term += f" AND {year_from}:{year_to}[pdat]"

        params = {
            "db": "pubmed",
            "term": term,
            "retmax": min(max_results, 200),
            "sort": "relevance",
            "retmode": "json",
        }
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key

        # 带重试的请求
        try:
            r = None
            for attempt in range(3):
                r = self.session.get(
                    f"{self.BASE}/esearch.fcgi", params=params, timeout=20
                )
                if r.status_code == 429:
                    wait = min(2**attempt, 5)
                    time.sleep(wait)
                    continue
                break
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"Cochrane search error: {e}")
            return []

        pmids = data.get("esearchresult", {}).get("idlist", [])
        if not pmids:
            return []

        # 获取详情
        return self._fetch_details(pmids)

    def _fetch_details(self, pmids: list) -> list:
        """批量获取文献详情（复用 PubMed XML 解析）"""
        papers = []
        for i in range(0, len(pmids), 100):
            batch = pmids[i : i + 100]
            params = {
                "db": "pubmed",
                "id": ",".join(batch),
                "retmode": "xml",
            }
            if self.email:
                params["email"] = self.email
            if self.api_key:
                params["api_key"] = self.api_key

            try:
                r = None
                for attempt in range(3):
                    r = self.session.get(
                        f"{self.BASE}/efetch.fcgi", params=params, timeout=30
                    )
                    if r.status_code == 429:
                        wait = min(2**attempt, 5)
                        time.sleep(wait)
                        continue
                    break
                r.raise_for_status()
                papers.extend(self._parse_xml(r.text))
            except Exception as e:
                print(f"Cochrane fetch error: {e}")

            if i + 100 < len(pmids):
                time.sleep(0.5)

        return papers

    def _parse_xml(self, xml_text: str) -> list:
        """解析 PubMed XML 为 Paper 对象"""
        papers = []
        try:
            try:
                parser = ET.XMLParser(resolve_entities=False)
            except TypeError:
                parser = ET.XMLParser()
            root = ET.fromstring(xml_text, parser=parser)
        except ET.ParseError:
            return papers

        for article in root.findall(".//PubmedArticle"):
            p = Paper(source="cochrane")

            pmid_el = article.find(".//PMID")
            if pmid_el is not None:
                p.pmid = pmid_el.text or ""

            title_el = article.find(".//ArticleTitle")
            if title_el is not None:
                p.title = self._get_text(title_el)

            for author in article.findall(".//Author"):
                last = author.find("LastName")
                first = author.find("ForeName")
                if last is not None and last.text:
                    name = last.text
                    if first is not None and first.text:
                        name += f", {first.text}"
                    p.authors.append(name)

            # 提取机构信息
            for aff_info in article.findall(".//AffiliationInfo"):
                aff_el = aff_info.find("Affiliation")
                if aff_el is not None and aff_el.text:
                    aff_text = aff_el.text.strip()
                    if aff_text and aff_text not in p.affiliations:
                        p.affiliations.append(aff_text)

            journal_el = article.find(".//Journal/Title")
            if journal_el is not None:
                p.journal = journal_el.text or ""

            year_el = article.find(".//PubDate/Year")
            if year_el is not None and year_el.text:
                try:
                    p.year = int(year_el.text)
                except ValueError:
                    pass

            abstract_el = article.find(".//Abstract")
            if abstract_el is not None:
                parts = []
                for at in abstract_el.findall(".//AbstractText"):
                    label = at.get("Label", "")
                    text = self._get_text(at)
                    if label:
                        parts.append(f"{label}: {text}")
                    else:
                        parts.append(text)
                p.abstract = " ".join(parts)

            # DOI
            for eid in article.findall(".//ArticleId"):
                if eid.get("IdType") == "doi":
                    p.doi = eid.text or ""
                    break

            # 卷/期/页码
            volume_el = article.find(".//JournalIssue/Volume")
            if volume_el is not None:
                p.volume = volume_el.text or ""
            issue_el = article.find(".//JournalIssue/Issue")
            if issue_el is not None:
                p.issue = issue_el.text or ""
            pages_el = article.find(".//Pagination/MedlinePgn")
            if pages_el is not None:
                p.pages = pages_el.text or ""

            if p.title:
                papers.append(p)

        return papers

    @staticmethod
    def _get_text(element) -> str:
        """安全获取 XML 元素文本"""
        if element is None:
            return ""
        parts = []
        if element.text:
            parts.append(element.text)
        for child in element:
            if child.text:
                parts.append(child.text)
            if child.tail:
                parts.append(child.tail)
        return "".join(parts).strip()


@register_source
class CochraneSource(BaseSearchSource):
    """Cochrane Library 数据源适配器（通过 PubMed 检索 Cochrane 系统综述/Meta分析）"""

    SOURCE_NAME = "cochrane"
    DISPLAY_NAME = "Cochrane"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._impl = CochraneSearch(
            email=config.get("email", ""),
            api_key=config.get("api_key", ""),
            proxy=self.proxy,
        )

    def is_available(self):
        return True  # PubMed E-utilities 无需 API key 即可使用

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            pub_type=kwargs.get("pub_type", ""),
            field=kwargs.get("field", ""),
        )


@register_source
class FrontiersSource(BaseSearchSource):
    """Frontiers 开放获取期刊搜索源 — 免费 REST API"""

    SOURCE_NAME = "frontiers"
    DISPLAY_NAME = "Frontiers"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 30
    BASE = "https://api.frontiersin.org/api/v2"

    def __init__(self, **config):
        super().__init__(**config)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "PaperLens/1.0"

    def search(
        self,
        query: str,
        year_from: int = 0,
        year_to: int = 0,
        max_results: int = 30,
        field="",
        **kwargs,
    ) -> list:
        try:
            # 作者搜索：使用 author: 前缀
            if field == "au":
                search_query = f"author:{query}"
            else:
                search_query = query
            params = {
                "q": search_query,
                "size": min(max_results, 50),
                "sort": "relevance",
            }
            r = self.session.get(
                f"{self.BASE}/articles/search", params=params, timeout=15
            )
            r.raise_for_status()
            data = r.json()
            papers = []
            for hit in data.get("hits", []):
                try:
                    p = Paper(source="frontiers")
                    p.title = hit.get("title", "") or ""
                    if not p.title:
                        continue
                    p.abstract = (hit.get("abstract") or "")[:5000]
                    p.doi = hit.get("doi", "") or ""
                    authors = hit.get("authors", [])
                    p.authors = [a.get("name", "") for a in authors if a.get("name")]
                    date = hit.get("publishedDate", "") or ""
                    if date:
                        try:
                            p.year = int(date[:4])
                        except ValueError:
                            pass
                    journal = hit.get("journal", {}) or {}
                    p.journal = journal.get("name", "") or "Frontiers in ..."
                    p.url = hit.get("url", "") or ""
                    papers.append(p)
                    if len(papers) >= max_results:
                        break
                except Exception:
                    continue
            return papers
        except Exception as e:
            print(f"Frontiers search error: {e}")
            return []


@register_source
class ACMSource(BaseSearchSource):
    """ACM Digital Library 搜索源 — CrossRef member filter"""

    SOURCE_NAME = "acm"
    DISPLAY_NAME = "ACM"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 30

    def search(
        self,
        query: str,
        year_from: int = 0,
        year_to: int = 0,
        max_results: int = 30,
        field="",
        **kwargs,
    ) -> list:
        try:
            # 作者搜索：使用 query.author 参数
            if field == "au":
                params = {
                    "query.author": query,
                    "rows": min(max_results, 50),
                    "filter": "member:320",
                }
            else:
                params = {
                    "query": query,
                    "rows": min(max_results, 50),
                    "filter": "member:320",
                }
            r = requests.get(
                "https://api.crossref.org/works", params=params, timeout=15
            )
            r.raise_for_status()
            data = r.json()
            papers = []
            for item in data.get("message", {}).get("items", []):
                try:
                    p = Paper(source="acm")
                    p.title = (item.get("title") or [""])[0]
                    if not p.title:
                        continue
                    p.abstract = (item.get("abstract") or "")[:5000]
                    p.doi = item.get("DOI", "") or ""
                    p.journal = (item.get("container-title") or [""])[0]
                    p.year = item.get("published-print", {}).get("date-parts", [[0]])[
                        0
                    ][0]
                    authors = item.get("author", [])
                    p.authors = [
                        f"{a.get('given', '')} {a.get('family', '')}".strip()
                        for a in authors
                    ]
                    p.url = item.get("URL", "") or ""
                    papers.append(p)
                    if len(papers) >= max_results:
                        break
                except Exception:
                    continue
            return papers
        except Exception as e:
            print(f"ACM search error: {e}")
            return []


# CrossRef 出版商适配器（按 member_id 区分）
class CrossRefPublisherSource(BaseSearchSource):
    """CrossRef 出版商搜索适配器基类"""

    DEFAULT_ENABLED = True
    MAX_RESULTS = 50
    _member_id = 0  # 子类通过类属性覆盖

    def __init__(self, **config):
        super().__init__(**config)
        member_id = getattr(self.__class__, "_member_id", 0)
        publisher_name = self.SOURCE_NAME
        self._impl = CrossRefPublisherSearch(
            member_id=member_id,
            source_name=publisher_name,
            email=config.get("email", ""),
            proxy=self.proxy,
        )

    def search(self, query, year_from, year_to, max_results=50, **kwargs):
        return self._impl.search(
            query,
            year_from,
            year_to,
            max_results=min(max_results, self.MAX_RESULTS),
            field=kwargs.get("field", ""),
        )


# 注册 CrossRef 出版商
_publisher_configs = {
    "acs": 316,
    "optica": 285,
    "iop": 266,
    "aip": 317,
    "rsc": 292,
    "springer": 297,
    "wiley": 311,
    "ieee": 263,
    "muse": 147,
    "jstor": 337,
    "frontiers": 1965,
    "acm": 320,
    "oup": 286,
    "cup": 56,
    "sage": 179,
    "taylor_francis": 301,
    "ebsco": 324,
}
_publisher_display = {
    "acs": "ACS",
    "optica": "Optica",
    "iop": "IOP",
    "aip": "AIP",
    "rsc": "RSC",
    "springer": "Springer",
    "wiley": "Wiley",
    "ieee": "IEEE",
    "muse": "MUSE",
    "jstor": "JSTOR",
    "frontiers": "Frontiers",
    "acm": "ACM",
    "oup": "Oxford Academic",
    "cup": "Cambridge Core",
    "sage": "SAGE",
    "taylor_francis": "Taylor & Francis",
    "ebsco": "EBSCO",
}
for _pub_name, _member_id in _publisher_configs.items():
    _pub_cls = type(
        f"CrossRef_{_pub_name.title()}Source",
        (CrossRefPublisherSource,),
        {
            "SOURCE_NAME": _pub_name,
            "DISPLAY_NAME": _publisher_display.get(_pub_name, _pub_name.upper()),
            "_member_id": _member_id,
        },
    )
    _SOURCE_REGISTRY[_pub_name] = _pub_cls


# --- CARSI 聚合器搜索源 ---


@register_source
class WoSOfScienceSource(BaseSearchSource):
    """Web of Science 搜索源 — 通过 CARSI 认证访问，HTML 爬取"""

    SOURCE_NAME = "wos"
    DISPLAY_NAME = "Web of Science"
    DEFAULT_ENABLED = False
    REQUIRES_COOKIES = True
    MAX_RESULTS = 30

    def is_available(self) -> bool:
        return hasattr(self, "_cookies") and bool(self._cookies)

    def search(
        self,
        query: str,
        year_from: int = 0,
        year_to: int = 0,
        max_results: int = 30,
        field="",
        **kwargs,
    ) -> list:
        if not self.is_available():
            return []
        # WoS 需要通过 CARSI 的 Playwright 浏览器进行搜索
        try:
            from access_proxy import CARSIAuth

            carsi = CARSIAuth()
            if not carsi.is_authenticated():
                return []
            papers = carsi.search_wos(
                query, year_from, year_to, max_results, field=field
            )
            return papers
        except Exception as e:
            print(f"WoS search error: {e}")
            return []


@register_source
class ProQuestSource(BaseSearchSource):
    """ProQuest 搜索源 — 学位论文 + 学术文献，通过 CARSI 认证访问"""

    SOURCE_NAME = "proquest"
    DISPLAY_NAME = "ProQuest"
    DEFAULT_ENABLED = False
    REQUIRES_COOKIES = True
    MAX_RESULTS = 20

    def is_available(self) -> bool:
        return hasattr(self, "_cookies") and bool(self._cookies)

    def search(
        self,
        query: str,
        year_from: int = 0,
        year_to: int = 0,
        max_results: int = 20,
        field="",
        **kwargs,
    ) -> list:
        if not self.is_available():
            return []
        try:
            from access_proxy import CARSIAuth

            carsi = CARSIAuth()
            if not carsi.is_authenticated():
                return []
            papers = carsi.search_proquest(
                query, year_from, year_to, max_results, field=field
            )
            return papers
        except Exception as e:
            print(f"ProQuest search error: {e}")
            return []


# --- 智能搜索源路由 ---

# 学科领域定义：关键词 -> (学科名, 权重)
# 权重越高，匹配越强。阈值 >= 2 视为匹配该学科。
_DISCIPLINE_KEYWORDS: dict = {
    # 计算机科学
    "cs": {
        "keywords": {
            "algorithm": 2,
            "machine learning": 3,
            "deep learning": 3,
            "neural network": 3,
            "artificial intelligence": 3,
            "natural language processing": 3,
            "computer vision": 3,
            "reinforcement learning": 2,
            "transformer": 2,
            "attention mechanism": 2,
            "convolutional neural": 2,
            "generative adversarial": 2,
            "graph neural": 2,
            "federated learning": 2,
            "software engineering": 2,
            "programming": 1,
            "database": 1,
            "network": 1,
            "security": 1,
            "distributed system": 2,
            "cloud computing": 2,
            "big data": 2,
            "data mining": 2,
            "information retrieval": 2,
            "recommender system": 2,
            "speech recognition": 2,
            "image segmentation": 2,
            "object detection": 2,
            "text classification": 2,
            "sentiment analysis": 2,
            "knowledge graph": 2,
            "semantic web": 2,
            "blockchain": 2,
            "internet of things": 2,
            "iot": 1,
            "cybersecurity": 2,
            "cryptography": 2,
            "operating system": 2,
            "compiler": 2,
            "robotics": 2,
        },
        "sources": {"dblp", "ieee", "acm", "arxiv", "springer", "core", "lens"},
    },
    # 医学 / 生物医学
    "medicine": {
        "keywords": {
            "clinical trial": 3,
            "patient": 2,
            "diagnosis": 2,
            "treatment": 2,
            "therapy": 2,
            "disease": 2,
            "cancer": 2,
            "tumor": 2,
            "carcinoma": 2,
            "cardiovascular": 2,
            "cardiac": 2,
            "neurodegenerative": 2,
            "alzheimer": 2,
            "parkinson": 2,
            "immunology": 2,
            "immune": 2,
            "antibody": 2,
            "pharmacology": 2,
            "drug": 2,
            "pharmaceutical": 2,
            "pathology": 2,
            "pathogen": 2,
            "infection": 2,
            "epidemiology": 2,
            "public health": 2,
            "surgery": 2,
            "surgical": 2,
            "radiology": 2,
            "mri": 1,
            "ct scan": 1,
            "biomarker": 2,
            "prognosis": 2,
            "randomized controlled": 3,
            "meta-analysis": 2,
            "systematic review": 2,
            "cohort study": 2,
            "case report": 1,
            "case series": 1,
            "nih": 1,
            "pubmed": 1,
            "mesh": 1,
            "oncology": 2,
            "hematology": 2,
            "gastroenterology": 2,
            "dermatology": 2,
            "ophthalmology": 2,
            "psychiatry": 2,
            "pediatrics": 2,
            "obstetrics": 2,
            "gynecology": 2,
            "anesthesiology": 2,
            "emergency medicine": 2,
        },
        "sources": {"pubmed", "europepmc", "scopus", "crossref", "core", "lens"},
    },
    # 化学
    "chemistry": {
        "keywords": {
            "synthesis": 1,
            "catalyst": 2,
            "catalysis": 2,
            "organic chemistry": 3,
            "inorganic chemistry": 3,
            "polymer": 2,
            "nanoparticle": 1,
            "nanostructure": 1,
            "spectroscopy": 2,
            "chromatography": 2,
            "crystal structure": 2,
            "x-ray diffraction": 2,
            "nuclear magnetic resonance": 3,
            "nmr": 1,
            "mass spectrometry": 2,
            "electrochemistry": 2,
            "photochemistry": 2,
            "electrolyte": 2,
            "functional group": 2,
            "reaction mechanism": 2,
            "stoichiometry": 2,
            "titration": 2,
            "coordination compound": 3,
            "metal-organic framework": 3,
            "mof": 1,
            "covalent organic framework": 3,
            "polymerization": 2,
            "copolymer": 2,
            "surface chemistry": 2,
            "colloid": 2,
            "supramolecular": 2,
            "self-assembly": 1,
            "green chemistry": 2,
            "catalytic": 2,
        },
        "sources": {
            "acs",
            "rsc",
            "sciencedirect",
            "crossref",
            "springer",
            "scopus",
            "lens",
        },
    },
    # 物理学
    "physics": {
        "keywords": {
            "quantum mechanics": 3,
            "quantum field": 3,
            "condensed matter": 3,
            "superconductor": 2,
            "semiconductor": 2,
            "photonics": 2,
            "optics": 2,
            "laser": 2,
            "optical": 1,
            "particle physics": 3,
            "hadron": 2,
            "boson": 2,
            "fermion": 2,
            "quark": 2,
            "higgs": 2,
            "astrophysics": 3,
            "cosmology": 3,
            "dark matter": 3,
            "dark energy": 3,
            "neutron star": 2,
            "black hole": 2,
            "gravitational wave": 3,
            "galaxy": 2,
            "thermodynamics": 2,
            "statistical mechanics": 3,
            "electrodynamics": 2,
            "electromagnetic": 1,
            "plasma physics": 3,
            "fluid dynamics": 2,
            "turbulence": 2,
            "magnetism": 2,
            "magnetic field": 1,
            "topological": 2,
            "spintronics": 2,
            "photovoltaic": 2,
            "solar cell": 2,
            "spectroscopy": 1,
            "diffract": 1,
        },
        "sources": {
            "iop",
            "aip",
            "arxiv",
            "springer",
            "sciencedirect",
            "crossref",
            "scopus",
            "lens",
        },
    },
    # 生物学
    "biology": {
        "keywords": {
            "genome": 2,
            "genomics": 3,
            "gene expression": 3,
            "transcriptomics": 3,
            "proteomics": 3,
            "metabolomics": 3,
            "crispr": 3,
            "gene editing": 3,
            "gene therapy": 3,
            "cell biology": 3,
            "cell signaling": 3,
            "apoptosis": 2,
            "autophagy": 2,
            "mitosis": 2,
            "evolution": 2,
            "phylogenetics": 3,
            "population genetics": 3,
            "ecology": 2,
            "biodiversity": 2,
            "conservation": 1,
            "microbiology": 3,
            "virology": 3,
            "bacteriology": 3,
            "immunology": 1,
            "vaccine": 2,
            "neuroscience": 2,
            "neuron": 2,
            "synapse": 2,
            "bioinformatics": 3,
            "sequence alignment": 3,
            "protein structure": 3,
            "molecular dynamics": 2,
            "enzyme": 2,
            "receptor": 2,
            "ligand": 1,
            "stem cell": 3,
            "organoid": 3,
            "metagenomics": 3,
            "microbiome": 3,
            "rna": 1,
            "mrna": 2,
            "lncrna": 2,
            "epigenetics": 3,
            "methylation": 2,
        },
        "sources": {
            "biorxiv",
            "pubmed",
            "europepmc",
            "sciencedirect",
            "crossref",
            "springer",
            "scopus",
            "lens",
        },
    },
    # 材料科学
    "materials": {
        "keywords": {
            "nanomaterial": 2,
            "nanoparticle": 2,
            "nanotube": 2,
            "nanowire": 2,
            "nanosheet": 2,
            "quantum dot": 2,
            "graphene": 3,
            "carbon nanotube": 3,
            "mxene": 3,
            "perovskite": 2,
            "thin film": 2,
            "coating": 1,
            "alloy": 2,
            "composite": 2,
            "polymer": 1,
            "ceramic": 2,
            "hydrogel": 2,
            "biomaterial": 2,
            "superconductor": 1,
            "semiconductor": 1,
            "photovoltaic": 2,
            "solar cell": 2,
            "battery": 2,
            "supercapacitor": 2,
            "energy storage": 2,
            "catalyst": 1,
            "electrocatalysis": 2,
            "photocatalysis": 2,
            "corrosion": 2,
            "wear": 1,
            "hardness": 1,
            "tensile strength": 2,
            "fatigue": 1,
            "fracture": 1,
            "x-ray diffraction": 2,
            "scanning electron microscope": 2,
            "transmission electron microscope": 3,
            "sem": 1,
            "tem": 1,
            "atomic force microscope": 3,
            "afm": 1,
            "chemical vapor deposition": 3,
            "cvd": 1,
            "sputtering": 2,
            "electrospinning": 2,
            "3d printing": 2,
            "additive manufacturing": 2,
            "shape memory": 2,
            "piezoelectric": 2,
            "thermoelectric": 2,
            "ferroelectric": 2,
            "magnetic material": 2,
            "optical material": 2,
        },
        "sources": {
            "acs",
            "rsc",
            "sciencedirect",
            "springer",
            "scopus",
            "crossref",
            "iop",
            "aip",
            "lens",
        },
    },
    # 农业科学
    "agriculture": {
        "keywords": {
            "agriculture": 3,
            "agronomy": 3,
            "crop": 2,
            "soil": 2,
            "fertilizer": 2,
            "irrigation": 2,
            "pesticide": 2,
            "herbicide": 2,
            "insecticide": 2,
            "plant breeding": 3,
            "plant pathology": 3,
            "food safety": 2,
            "food science": 3,
            "nutrition": 2,
            "livestock": 2,
            "animal science": 2,
            "veterinary": 2,
            "forestry": 2,
            "silviculture": 2,
            "aquaculture": 2,
            "fisheries": 2,
            "horticulture": 2,
            "viticulture": 2,
            "organic farming": 2,
            "sustainable agriculture": 3,
            "precision agriculture": 3,
            "remote sensing": 1,
            "yield": 1,
            "germplasm": 2,
            "cultivar": 2,
        },
        "sources": {
            "agris",
            "pubmed",
            "crossref",
            "sciencedirect",
            "springer",
            "scopus",
            "lens",
        },
    },
    # 工程学
    "engineering": {
        "keywords": {
            "control system": 3,
            "signal processing": 3,
            "power electronics": 3,
            "electric motor": 2,
            "power grid": 2,
            "renewable energy": 2,
            "wind energy": 2,
            "hydrogen": 1,
            "structural engineering": 3,
            "finite element": 3,
            "civil engineering": 3,
            "geotechnical": 3,
            "fluid mechanics": 2,
            "thermodynamics": 1,
            "manufacturing": 2,
            "automation": 2,
            "mechatronics": 3,
            "embedded system": 3,
            "vlsi": 3,
            "digital signal": 3,
            "telecommunication": 3,
            "5g": 2,
            "6g": 2,
            "antenna": 2,
            "microwave": 2,
            "radar": 2,
            "image processing": 2,
            "pattern recognition": 2,
            "control theory": 3,
            "pid controller": 3,
            "robotics": 1,
            "drone": 2,
            "uav": 2,
            "traffic": 1,
            "transportation": 2,
        },
        "sources": {
            "ieee",
            "springer",
            "sciencedirect",
            "arxiv",
            "crossref",
            "scopus",
            "iop",
            "aip",
            "lens",
        },
    },
    # 人文社科
    "humanities": {
        "keywords": {
            "philosophy": 3,
            "ethics": 2,
            "epistemology": 3,
            "aesthetics": 2,
            "metaphysics": 3,
            "history": 2,
            "historiography": 3,
            "archaeology": 3,
            "literature": 2,
            "literary": 2,
            "narrative": 1,
            "linguistics": 3,
            "syntax": 2,
            "semantics": 2,
            "sociology": 3,
            "anthropology": 3,
            "ethnography": 3,
            "political science": 3,
            "international relations": 3,
            "economics": 2,
            "econometrics": 3,
            "psychology": 2,
            "cognitive science": 3,
            "education": 2,
            "pedagogy": 3,
            "law": 2,
            "legal": 2,
            "jurisprudence": 3,
            "art": 1,
            "culture": 1,
            "religion": 2,
            "gender studies": 3,
            "postcolonial": 3,
            "media studies": 3,
            "communication": 2,
        },
        "sources": {"jstor", "muse", "crossref", "scopus", "core", "lens"},
    },
}

# 跨学科通用数据源（几乎所有学科都包含）
_UNIVERSAL_SOURCES = {"openalex", "semantic_scholar", "crossref", "core", "lens"}


class DisciplineRouter:
    """基于查询关键词的学科领域识别与数据源路由"""

    # 匹配阈值：关键词权重累加 >= 此值则认定为该学科
    THRESHOLD = 2

    @classmethod
    def detect_disciplines(cls, query: str) -> list:
        """识别查询所属的学科领域，返回按匹配度降序的 [(discipline, score), ...]"""
        if not query:
            return []

        query_lower = query.lower()
        # 提取查询中的有效词（去掉布尔运算符和停用词）
        stopwords = {
            "and",
            "or",
            "not",
            "the",
            "for",
            "with",
            "from",
            "in",
            "on",
            "at",
            "to",
            "of",
            "by",
            "is",
            "are",
            "was",
            "were",
            "a",
            "an",
            "this",
            "that",
            "these",
            "those",
            "it",
            "its",
        }
        words = set(
            w.strip("()'\"")
            for w in re.split(r"[\s+,;:]+", query_lower)
            if len(w.strip("()'\"")) > 1 and w.strip("()'\"") not in stopwords
        )

        scores = {}
        for disc, cfg in _DISCIPLINE_KEYWORDS.items():
            score = 0
            matched = []
            for kw, weight in cfg["keywords"].items():
                # 多词关键词：检查是否完整出现在查询中
                if " " in kw:
                    if kw in query_lower:
                        score += weight
                        matched.append(kw)
                else:
                    if kw in words:
                        score += weight
                        matched.append(kw)
            if score >= cls.THRESHOLD:
                scores[disc] = (score, matched)

        # 按分数降序排列
        result = sorted(scores.items(), key=lambda x: x[1][0], reverse=True)
        return [(disc, s) for disc, (s, _) in result]

    @classmethod
    def get_recommended_sources(cls, query: str) -> set:
        """根据查询推荐数据源集合"""
        disciplines = cls.detect_disciplines(query)
        if not disciplines:
            # 未识别到学科，返回通用源 + 全部多学科源
            return None  # None 表示不做过滤

        sources = set(_UNIVERSAL_SOURCES)
        for disc, score in disciplines:
            sources |= _DISCIPLINE_KEYWORDS[disc]["sources"]
        return sources

    @classmethod
    def filter_sources(cls, query: str, enabled_sources: set) -> set:
        """对用户选择的数据源集合进行学科过滤

        Args:
            query: 搜索查询
            enabled_sources: 用户启用的数据源集合

        Returns:
            过滤后的数据源集合。如果无法识别学科或过滤后为空，返回原始集合。
        """
        if not enabled_sources:
            return enabled_sources

        disciplines = cls.detect_disciplines(query)
        if not disciplines:
            return enabled_sources  # 无法识别，保持原样

        # 收集所有匹配学科的推荐源
        recommended = set(_UNIVERSAL_SOURCES)
        for disc, score in disciplines:
            recommended |= _DISCIPLINE_KEYWORDS[disc]["sources"]

        # 交集：只保留用户启用 + 学科推荐的源
        filtered = enabled_sources & recommended

        # 安全兜底：如果过滤后为空（罕见），返回原始集合
        if not filtered:
            print("[ROUTER] 过滤后为空，回退到原始源集合")
            return enabled_sources

        original_count = len(enabled_sources)
        filtered_count = len(filtered)
        disc_names = ", ".join(d for d, _ in disciplines)
        print(
            f"[ROUTER] 学科: {disc_names} | 源: {original_count} -> {filtered_count} "
            f"(跳过 {original_count - filtered_count} 个无关源)"
        )
        return filtered


class QueryUnderstanding:
    """基于规则的查询预理解层

    从自然语言查询中提取结构化信息：
    - 时间范围（年份）
    - 文献类型（review/clinical trial 等）
    - DOI
    - 作者名
    - 研究领域关键词

    纯正则+规则实现，无需 LLM 调用，作为 search() 的预处理步骤。

    示例：
        "最近三年的CRISPR综述"
        -> query="CRISPR", year_from=2024, year_to=2026, pub_type="review"

        "10.1038/s41586-024-07487-w"
        -> doi="10.1038/s41586-024-07487-w"

        "Smith J 关于 deep learning 的 meta-analysis since 2022"
        -> query="deep learning", author="Smith J", pub_type="meta-analysis",
           year_from=2022
    """

    # ---- 文献类型映射 ----
    DOC_TYPE_MAP = {
        # 英文
        "review": "review",
        "综述": "review",
        "meta-analysis": "meta-analysis",
        "meta analysis": "meta-analysis",
        "荟萃分析": "meta-analysis",
        "systematic review": "systematic review",
        "系统综述": "systematic review",
        "clinical trial": "clinical trial",
        "临床试验": "clinical trial",
        "randomized controlled trial": "randomized controlled trial",
        "rct": "randomized controlled trial",
        "RCT": "randomized controlled trial",
        "case report": "case report",
        "病例报告": "case report",
        "case study": "case report",
        "cohort study": "cohort study",
        "队列研究": "cohort study",
        "cross-sectional": "cross-sectional study",
        "横断面研究": "cross-sectional study",
        "preprint": "preprint",
        "预印本": "preprint",
        "meta analysis": "meta-analysis",
        "临床研究": "clinical trial",
        "随机对照": "randomized controlled trial",
        "前瞻性研究": "cohort study",
        "回顾性研究": "cohort study",
        "前瞻性": "cohort study",
        "回顾性": "cohort study",
    }

    # ---- 中文数字 -> 阿拉伯数字 ----
    _ZH_NUM_MAP = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
        "十一": 11,
        "十二": 12,
        "十三": 13,
        "十四": 14,
        "十五": 15,
        "二十": 20,
        "三十": 30,
        "四十": 40,
        "五十": 50,
    }

    @classmethod
    def _zh_num_to_int(cls, s: str) -> int:
        """将中文数字转换为整数，非中文数字原样返回"""
        s = s.strip()
        if s.isdigit():
            return int(s)
        return cls._ZH_NUM_MAP.get(s, 0)

    # ---- 时间关键词（中英文） ----
    _RECENT_PATTERNS = [
        # 中文：最近/过去/近 + 中文数字或阿拉伯数字 + 年
        re.compile(
            r"(?:最近|过去|近|最近的?|过去(?:的)?)\s*"
            r"([零〇一二两三四五六七八九十百千万\d]+)\s*(?:年|岁|个?年)",
            re.IGNORECASE,
        ),
        # 英文：last/past/recent + number + years
        re.compile(
            r"(?:last|past|recent(?:\s+few)?|latest)\s+"
            r"(\d+)\s*(?:years?|yrs?)",
            re.IGNORECASE,
        ),
    ]

    # 匹配 "最近一个月" "past month" "last 3 months"
    _RECENT_MONTH_PATTERNS = [
        re.compile(
            r"(?:最近|过去|近)\s*"
            r"(\d+)\s*个?月",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:last|past)\s+"
            r"(\d+)\s*months?",
            re.IGNORECASE,
        ),
    ]

    # 匹配 "since 2020" "自2020年以来" "从2020年起" "2020年后" "2020年以来"
    # 注意：不匹配单独的 "2024年"（那是独立年份模式）
    _SINCE_PATTERNS = [
        re.compile(
            r"(?:since|from|自|从|起始于?)\s*"
            r"(\d{4})\s*(?:年|以来|起|开始)?",
            re.IGNORECASE,
        ),
        re.compile(
            r"(\d{4})\s*(?:年(?:以来|以后|后|起|至今)|(?:以后|后|起|以来|至今))",
            re.IGNORECASE,
        ),
    ]

    # 匹配 "2020-2025" "2020~2025" "2020 to 2025"
    _RANGE_PATTERNS = [
        re.compile(
            r"(\d{4})\s*[-~—–至到]\s*(\d{4})\s*(?:年)?",
        ),
        re.compile(r"(\d{4})\s+to\s+(\d{4})", re.IGNORECASE),
    ]

    # 匹配独立年份 "2024年" "in 2024"
    _YEAR_PATTERNS = [
        re.compile(
            r"(?:in\s+|年份[:：]?\s*)?(\d{4})\s*(?:年|papers?|年份)?", re.IGNORECASE
        ),
    ]

    # ---- DOI 模式 ----
    DOI_PATTERN = re.compile(
        r'10\.\d{4,9}/[^\s,;)\]}"、。]+',
    )

    # ---- 作者模式 ----
    AUTHOR_PATTERNS = [
        # "作者:张三" "author:Smith J" "作者：李四"
        # 英文作者名（大小写敏感，1-3个名字部分，每部分后可选空格）
        # 使用 (?=\s+\S) 确保匹配在名字后、下一个词前停止
        re.compile(
            r"(?:作者|author)[：:]\s*((?:[A-Z][a-z]*\.?(?:\s+(?=[A-Z]))?){1,3})"
        ),
        # 中文作者名 after "作者:"（2-4个连续汉字）
        re.compile(r"(?:作者|author)[：:]\s*([一-鿿]{2,4})"),
        # "by Smith J" "by Zhang San"
        re.compile(r"\bby\s+([A-Z][a-z]+(?:\s+[A-Z]\.?)*)\b"),
    ]

    # 时间/学术相关词（用于过滤作者误匹配）
    _TIME_WORDS = {
        # 时间词
        "最近",
        "过去",
        "近",
        "去年",
        "前年",
        "明年",
        "今年",
        "上个月",
        "下个月",
        "本月",
        "全天",
        "每年",
        "每月",
        "近年",
        "近期",
        "先前",
        "今后",
        "此后",
        "以来",
        "近三年",
        "最近三年",
        "过去三年",
        "近五年",
        "最近五年",
        "过去五年",
        "近十年",
        "最近十年",
        "过去十年",
        "近三年的",
        "最近三年的",
        "过去三年的",
        # 常见学术词汇（不应被识别为作者）
        "纳米",
        "材料",
        "量子",
        "基因",
        "蛋白",
        "细胞",
        "分子",
        "催化",
        "电池",
        "能源",
        "环境",
        "临床",
        "医学",
        "生物",
        "化学",
        "物理",
        "数学",
        "计算机",
        "人工智能",
        "深度学习",
        "机器学习",
        "数据分析",
        "文献",
        "综述",
        "研究",
        "论文",
    }

    @classmethod
    def parse(cls, query: str, current_year: int = None) -> dict:
        """解析自然语言查询，返回结构化信息

        Args:
            query: 用户原始查询
            current_year: 当前年份（用于相对时间计算）

        Returns:
            dict 包含:
                query (str): 清洗后的查询词
                year_from (int|None): 起始年份
                year_to (int|None): 结束年份
                pub_type (str): 文献类型
                doi (str|None): DOI
                author (str|None): 作者名
                suggestions (list[str]): 模糊查询建议
        """
        if current_year is None:
            current_year = datetime.now().year

        result = {
            "query": query,
            "year_from": None,
            "year_to": None,
            "pub_type": "",
            "doi": None,
            "author": None,
            "suggestions": [],
        }

        remaining = query

        # 1. 提取 DOI
        doi_match = cls.DOI_PATTERN.search(remaining)
        if doi_match:
            result["doi"] = doi_match.group(0)
            remaining = remaining[: doi_match.start()] + remaining[doi_match.end() :]
            result["query"] = remaining.strip()
            return result  # DOI 查询无需进一步解析

        # 2. 提取作者（过滤时间表达式误匹配）
        author, author_end = cls._extract_author(remaining)
        if author and author_end > 0:
            result["author"] = author
            remaining = remaining[author_end:]

        # 3. 提取文献类型
        pub_type = cls._extract_doc_type(remaining)
        if pub_type:
            result["pub_type"] = pub_type
            remaining = cls._remove_doc_type_text(remaining, pub_type)

        # 4. 提取时间范围
        year_from, year_to, remaining = cls._extract_time_range(remaining, current_year)
        result["year_from"] = year_from
        result["year_to"] = year_to

        # 5. 清理残留连接词和多余空格
        remaining = cls._clean_query(remaining)

        result["query"] = remaining.strip()

        # 6. 生成建议（模糊查询场景）
        result["suggestions"] = cls._generate_suggestions(result, current_year)

        return result

    @classmethod
    def _extract_author(cls, text: str) -> tuple:
        """提取作者名，过滤时间表达式误匹配

        Returns:
            (author_name, end_position) 或 ("", 0)
        """
        for pattern in cls.AUTHOR_PATTERNS:
            m = pattern.search(text)
            if m:
                candidate = m.group(1).strip()
                # 过滤时间表达式（如 "近三年的" 中的 "近三年"）
                if candidate in cls._TIME_WORDS:
                    continue
                # 过滤单字（不太可能是作者名）
                if len(candidate) < 2:
                    continue
                return candidate, m.end()
        return "", 0

    @classmethod
    def _extract_doc_type(cls, text: str) -> str:
        """提取文献类型

        中文关键词使用直接子串匹配（\b 对中文无效），
        英文关键词使用单词边界匹配（避免 overview 匹配 review）。
        """
        text_lower = text.lower()
        # 按长度降序匹配（优先匹配长模式，如 "systematic review" 优先于 "review"）
        sorted_types = sorted(cls.DOC_TYPE_MAP.keys(), key=len, reverse=True)
        for keyword in sorted_types:
            # 判断是否包含中文字符
            has_chinese = bool(re.search(r"[一-鿿]", keyword))
            if has_chinese:
                # 中文关键词：直接子串匹配
                if keyword in text_lower:
                    return cls.DOC_TYPE_MAP[keyword]
            else:
                # 英文关键词：单词边界匹配
                pattern = re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
                if pattern.search(text_lower):
                    return cls.DOC_TYPE_MAP[keyword]
        return ""

    @classmethod
    def _remove_doc_type_text(cls, text: str, pub_type: str) -> str:
        """从查询文本中移除已识别的文献类型关键词"""
        for keyword, mapped in cls.DOC_TYPE_MAP.items():
            if mapped == pub_type:
                has_chinese = bool(re.search(r"[一-鿿]", keyword))
                if has_chinese:
                    text = text.replace(keyword, "")
                else:
                    pattern = re.compile(
                        r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE
                    )
                    text = pattern.sub("", text)
        # 移除中文文献类型关键词
        zh_types = {
            "review": ["综述", "系统综述"],
            "meta-analysis": ["荟萃分析", "meta分析", "meta 分析"],
            "clinical trial": ["临床试验", "临床研究", "随机对照"],
            "case report": ["病例报告", "病例分析"],
            "cohort study": ["队列研究", "前瞻性研究", "回顾性研究"],
            "cross-sectional study": ["横断面研究"],
            "preprint": ["预印本"],
        }
        for keyword in zh_types.get(pub_type, []):
            text = text.replace(keyword, "")
        return text

    @classmethod
    def _extract_time_range(cls, text: str, current_year: int) -> tuple:
        """提取时间范围，返回 (year_from, year_to, remaining_text)"""
        # 优先匹配范围模式 "2020-2025"
        for pattern in cls._RANGE_PATTERNS:
            m = pattern.search(text)
            if m:
                y1, y2 = int(m.group(1)), int(m.group(2))
                if 1900 <= y1 <= current_year + 1 and 1900 <= y2 <= current_year + 1:
                    text = text[: m.start()] + text[m.end() :]
                    return y1, y2, text

        # "since/from 2020" 模式
        for pattern in cls._SINCE_PATTERNS:
            m = pattern.search(text)
            if m:
                year = int(m.group(1))
                if 1900 <= year <= current_year + 1:
                    text = text[: m.start()] + text[m.end() :]
                    return year, current_year, text

        # "最近N年" 相对时间模式（支持中文数字和阿拉伯数字）
        for pattern in cls._RECENT_PATTERNS:
            m = pattern.search(text)
            if m:
                n = cls._zh_num_to_int(m.group(1))
                if 1 <= n <= 100:
                    text = text[: m.start()] + text[m.end() :]
                    return current_year - n + 1, current_year, text

        # "最近N个月" 模式（转为年份近似，支持中文数字）
        for pattern in cls._RECENT_MONTH_PATTERNS:
            m = pattern.search(text)
            if m:
                months = cls._zh_num_to_int(m.group(1))
                if 1 <= months <= 120:
                    year_from = current_year - (months // 12)
                    if months % 12 > 0:
                        year_from = current_year - (months // 12) - 1
                    text = text[: m.start()] + text[m.end() :]
                    return max(1900, year_from), current_year, text

        # 单独年份 "2024年"
        for pattern in cls._YEAR_PATTERNS:
            m = pattern.search(text)
            if m:
                year = int(m.group(1))
                if 1900 <= year <= current_year + 1:
                    text = text[: m.start()] + text[m.end() :]
                    return year, year, text

        return None, None, text

    @classmethod
    def _clean_query(cls, text: str) -> str:
        """清理查询文本中的残留连接词和多余空格"""
        cleanup_words = [
            "的",
            "关于",
            "研究",
            "论文",
            "文章",
            "发表在",
            "来自",
            "作者",
        ]
        for w in cleanup_words:
            text = text.replace(w, " ")
        text = re.sub(
            r"\b(?:about|on|of|for|the|a|an|papers?|articles?)\b",
            " ",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\s+", " ", text).strip()
        text = text.strip("，,。.、;；:：")
        return text

    @classmethod
    def _generate_suggestions(cls, parsed: dict, current_year: int) -> list:
        """基于解析结果生成查询建议"""
        suggestions = []
        if not parsed["year_from"] and not parsed["year_to"]:
            suggestions.append(
                f"尝试添加时间范围，如「最近3年」或「{current_year - 2}-{current_year}」"
            )
        if not parsed["pub_type"]:
            suggestions.append(
                "指定文献类型可缩小范围，如「review」「meta-analysis」「临床试验」"
            )
        if len(parsed["query"].split()) < 2:
            suggestions.append("查询词较少，建议添加更具体的关键词")
        return suggestions


class ZoteroSQLiteReader:
    """内置 Zotero SQLite 读取器 — 零依赖，直接读 Zotero 本地数据库。
    支持 Zotero 6/7，自动检测 profile 目录。"""

    ZOTERO_FIELDS = {
        1: "title",
        2: "abstractNote",
        3: "DOI",
        4: "url",
        5: "volume",
        6: "issue",
        7: "pages",
        8: "publicationTitle",
        9: "date",
        10: "series",
        11: "language",
        12: "ISBN",
        13: "ISSN",
        14: "shortTitle",
        15: "accessDate",
    }

    @staticmethod
    def find_profile_dir(custom_dir: str = "") -> str | None:
        """自动检测 Zotero profile 目录（支持 Zotero 6/7+ 及自定义数据目录）"""
        import os as _os
        import configparser as _cp

        home = _os.path.expanduser("~")

        # 0) 用户手动设置的路径优先
        if custom_dir and _os.path.isdir(custom_dir):
            db = _os.path.join(custom_dir, "zotero.sqlite")
            if _os.path.isfile(db):
                return custom_dir
            # 也可能 custom_dir 是 Profiles 的父目录
            for entry in _os.listdir(custom_dir):
                profile = _os.path.join(custom_dir, entry)
                if _os.path.isdir(profile):
                    db2 = _os.path.join(profile, "zotero.sqlite")
                    if _os.path.isfile(db2):
                        return profile

        # 1) 优先读取 profiles.ini（Zotero 标准方式）
        ini_candidates = []
        if sys.platform == "win32":
            appdata = _os.environ.get("APPDATA", home)
            ini_candidates.append(
                _os.path.join(appdata, "Zotero", "Zotero", "profiles.ini")
            )
        elif sys.platform == "darwin":
            ini_candidates.append(
                _os.path.join(
                    home, "Library", "Application Support", "Zotero", "profiles.ini"
                )
            )
        else:
            ini_candidates.append(
                _os.path.join(home, ".zotero", "zotero", "profiles.ini")
            )
            ini_candidates.append(
                _os.path.join(
                    home,
                    ".var",
                    "app",
                    "org.zotero.Zotero",
                    "data",
                    "zotero",
                    "zotero",
                    "profiles.ini",
                )
            )

        for ini_path in ini_candidates:
            if not _os.path.isfile(ini_path):
                continue
            try:
                cp = _cp.ConfigParser()
                cp.read(ini_path, encoding="utf-8")
                for section in cp.sections():
                    if not section.startswith("Profile"):
                        continue
                    is_relative = cp.get(section, "IsRelative", fallback="1")
                    path_val = cp.get(section, "Path", fallback="")
                    if not path_val:
                        continue
                    if is_relative == "1":
                        profile = _os.path.join(_os.path.dirname(ini_path), path_val)
                    else:
                        profile = path_val
                    db = _os.path.join(profile, "zotero.sqlite")
                    if _os.path.isfile(db):
                        return profile
            except Exception:
                pass

        # 2) 回退：直接扫描（含自定义数据目录）
        base_candidates = []
        if sys.platform == "win32":
            appdata = _os.environ.get("APPDATA", home)
            base_candidates.append(
                _os.path.join(appdata, "Zotero", "Zotero", "Profiles")
            )
            # Zotero 7+ 自定义数据目录常见位置（用户可在首选项中修改）
            base_candidates.append(_os.path.join(home, "Zotero"))
            base_candidates.append(_os.path.join(home, "Documents", "Zotero"))
            local = _os.environ.get("LOCALAPPDATA", "")
            if local:
                base_candidates.append(
                    _os.path.join(local, "Zotero", "Zotero", "Profiles")
                )
        elif sys.platform == "darwin":
            base_candidates.append(
                _os.path.join(
                    home, "Library", "Application Support", "Zotero", "Profiles"
                )
            )
            base_candidates.append(_os.path.join(home, "Zotero"))
        else:
            base_candidates.append(_os.path.join(home, ".zotero", "zotero", "default"))
            base_candidates.append(
                _os.path.join(
                    home,
                    ".var",
                    "app",
                    "org.zotero.Zotero",
                    "data",
                    "zotero",
                    "zotero",
                    "default",
                )
            )
            base_candidates.append(
                _os.path.join(
                    home, "snap", "zotero-snap", "common", "Zotero", "Profiles"
                )
            )
            base_candidates.append(_os.path.join(home, "Zotero"))

        for base in base_candidates:
            if not _os.path.isdir(base):
                continue
            # A) 先检查 base 目录本身是否直接有 zotero.sqlite（自定义数据目录模式）
            direct = _os.path.join(base, "zotero.sqlite")
            if _os.path.isfile(direct):
                return base
            # B) 再扫描子目录（标准 Profiles/xxx.default 模式）
            for entry in _os.listdir(base):
                profile = _os.path.join(base, entry)
                if not _os.path.isdir(profile):
                    continue
                db_path = _os.path.join(profile, "zotero.sqlite")
                if _os.path.isfile(db_path):
                    return profile
        return None

    def __init__(self, profile_dir: str = None):
        import sqlite3
        import os as _os

        self._profile = profile_dir or self.find_profile_dir()
        self._db_path = None
        if self._profile:
            self._db_path = _os.path.join(self._profile, "zotero.sqlite")
            self._conn = sqlite3.connect(
                f"file:{self._db_path}?mode=ro", uri=True, timeout=5
            )
            self._conn.row_factory = sqlite3.Row

    @property
    def available(self) -> bool:
        return self._db_path is not None

    @property
    def stats(self) -> dict:
        """返回 Zotero 库统计信息"""
        if not self.available:
            return {"items": 0, "tags": 0}
        try:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM items WHERE itemTypeID IN (SELECT itemTypeID FROM itemTypes WHERE typeName NOT IN ('attachment','note','annotation'))"
            )
            items = cur.fetchone()[0]
            cur = self._conn.execute("SELECT COUNT(*) FROM tags")
            tags = cur.fetchone()[0]
            return {"items": items, "tags": tags}
        except Exception:
            return {"items": 0, "tags": 0}

    def search(
        self, query: str, limit: int = 20, year_from: int = 0, year_to: int = 0
    ) -> list:
        """搜索 Zotero 库，返回 Paper 对象列表"""
        if not self.available:
            return []
        papers = []
        try:
            like_q = f"%{query}%"
            params = [like_q, like_q, limit]
            year_filter = ""
            if year_from > 0 and year_to > 0:
                year_filter = "AND EXISTS (SELECT 1 FROM itemData id2 JOIN itemDataValues idv2 ON id2.valueID=idv2.valueID JOIN fields f2 ON id2.fieldID=f2.fieldID WHERE id2.itemID=i.itemID AND f2.fieldName='date' AND idv2.value BETWEEN ? AND ?)"
                params.insert(-1, str(year_from))
                params.insert(-1, str(year_to))

            sql = f"""
                SELECT DISTINCT i.itemID, i.key
                FROM items i
                JOIN itemData id_t ON i.itemID = id_t.itemID
                JOIN itemDataValues idv_t ON id_t.valueID = idv_t.valueID
                JOIN fields f_t ON id_t.fieldID = f_t.fieldID AND f_t.fieldName = 'title'
                LEFT JOIN itemData id_a ON i.itemID = id_a.itemID
                JOIN itemDataValues idv_a ON id_a.valueID = idv_a.valueID
                JOIN fields f_a ON id_a.fieldID = f_a.fieldID AND f_a.fieldName = 'abstractNote'
                WHERE i.itemTypeID IN (SELECT itemTypeID FROM itemTypes WHERE typeName NOT IN ('attachment','note','annotation'))
                  AND (idv_t.value LIKE ? OR idv_a.value LIKE ?)
                  {year_filter}
                ORDER BY i.dateAdded DESC
                LIMIT ?
            """
            cur = self._conn.execute(sql, params)
            item_ids = [row["itemID"] for row in cur.fetchall()]
            if not item_ids:
                return []

            # 批量读取元数据
            papers = []
            for item_id in item_ids:
                try:
                    p = self._item_to_paper(item_id)
                    if p.title:
                        papers.append(p)
                except Exception:
                    continue
        except Exception as e:
            print(f"[Zotero SQLite] search error: {e}")
        return papers

    def _item_to_paper(self, item_id: int) -> Paper:
        p = Paper(source="zotero_local")
        # 批量读取所有字段
        cur = self._conn.execute(
            """
            SELECT f.fieldName, idv.value
            FROM itemData id JOIN itemDataValues idv ON id.valueID = idv.valueID
            JOIN fields f ON id.fieldID = f.fieldID
            WHERE id.itemID = ?
        """,
            (item_id,),
        )
        field_values = {row["fieldName"]: row["value"] for row in cur.fetchall()}

        p.title = field_values.get("title", "") or ""
        p.abstract = (field_values.get("abstractNote", "") or "")[:500]
        p.doi = field_values.get("DOI", "") or ""
        p.journal = field_values.get("publicationTitle", "") or ""
        p.volume = field_values.get("volume", "") or ""
        p.issue = field_values.get("issue", "") or ""
        p.pages = field_values.get("pages", "") or ""
        p.issn = field_values.get("ISSN", "") or ""
        p.oa_url = field_values.get("url", "") or ""
        date_str = field_values.get("date", "")
        if date_str:
            try:
                p.year = int(date_str[:4])
            except ValueError:
                pass

        # 作者
        cur = self._conn.execute(
            """
            SELECT cd.firstName, cd.lastName
            FROM creators c JOIN creatorData cd ON c.creatorID = cd.creatorID
            WHERE c.itemID = ? ORDER BY c.orderIndex
        """,
            (item_id,),
        )
        for row in cur.fetchall():
            name = f"{row['firstName'] or ''} {row['lastName'] or ''}".strip()
            if name:
                p.authors.append(name)

        # 标签
        cur = self._conn.execute(
            """
            SELECT t.name FROM tags t JOIN itemTags it ON t.tagID = it.tagID
            WHERE it.itemID = ?
        """,
            (item_id,),
        )
        p.keywords = [row["name"] for row in cur.fetchall()]

        return p


class ZoteroNativeClient:
    """Zotero 9 原生本地 API 客户端 — 优先后端。
    用户需在 Zotero 设置中开启「允许其他应用程序与 Zotero 通讯」。
    端口 23119，遵循 Zotero Web API 协议。"""

    def __init__(self, base_url="http://127.0.0.1:23119", timeout=15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "PaperLens/1.0"})
        self._user_id = "0"  # 0 = wildcard, resolves to current user

    def ping(self) -> bool:
        try:
            r = self._session.get(
                f"{self.base_url}/api/users/0/items/top?limit=1", timeout=5
            )
            return r.status_code == 200
        except Exception:
            return False

    def search(
        self, query: str, year_from: int = 0, year_to: int = 0, limit: int = 50
    ) -> list:
        """搜索 Zotero 库，返回 Paper 对象列表"""
        papers = []
        try:
            params = {"limit": min(limit, 100), "format": "json"}
            if year_from and year_to:
                params["q"] = query  # Zotero API 的 q 参数支持年份过滤
            url = f"{self.base_url}/api/users/{self._user_id}/items/top"
            r = self._session.get(url, params=params, timeout=self.timeout)
            if r.status_code != 200:
                return []
            items = r.json()
            for item in items:
                data = item.get("data", {})
                title = data.get("title", "") or ""
                if not title:
                    continue
                # 跳过附件和笔记
                if data.get("itemType") in ("attachment", "note", "annotation"):
                    continue
                p = Paper(source="zotero_native")
                p.title = title
                p.abstract = (data.get("abstractNote") or "")[:5000]
                p.doi = data.get("DOI", "") or ""
                p.url = data.get("url", "") or ""
                date_str = data.get("date", "") or ""
                if date_str:
                    try:
                        p.year = int(date_str[:4])
                    except ValueError:
                        pass
                # 作者
                creators = data.get("creators", [])
                p.authors = [
                    f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
                    for c in creators
                    if c.get("creatorType") == "author"
                ]
                # 标签
                tags = data.get("tags", [])
                p.keywords = [t.get("tag", "") for t in tags if t.get("tag")]
                # 期刊
                pub_title = (
                    data.get("publicationTitle", "")
                    or data.get("libraryCatalog", "")
                    or ""
                )
                if pub_title:
                    p.journal = pub_title
                papers.append(p)
                if len(papers) >= limit:
                    break
        except Exception as e:
            print(f"[Zotero Native] search error: {e}")
        return papers

    def get_tags(self) -> list:
        """获取所有标签及使用计数"""
        try:
            r = self._session.get(
                f"{self.base_url}/api/users/{self._user_id}/tags", timeout=self.timeout
            )
            if r.status_code != 200:
                return []
            tags = r.json()
            return [
                {
                    "name": t.get("tag", ""),
                    "count": t.get("meta", {}).get("numItems", 0),
                }
                for t in tags
            ]
        except Exception:
            return []

    def get_fulltext(self, item_key: str) -> str | None:
        """获取论文 PDF 全文（如果有附件）"""
        try:
            # 获取子项（附件+笔记）
            r = self._session.get(
                f"{self.base_url}/api/users/{self._user_id}/items/{item_key}/children",
                timeout=self.timeout,
            )
            if r.status_code != 200:
                return None
            for child in r.json():
                data = child.get("data", {})
                if data.get("itemType") != "attachment":
                    continue
                link = child.get("links", {}).get("self", {}).get("href", "")
                if not link:
                    continue
                # 本地 API 的附件是直接可下载的
                rr = self._session.get(link, timeout=30)
                if rr.status_code == 200 and b"PDF" in rr.content[:10]:
                    return rr.content.decode("latin-1")
            return None
        except Exception as e:
            print(f"[Zotero Native] fulltext error: {e}")
            return None

    def get_stats(self) -> dict:
        """获取库统计"""
        try:
            r = self._session.get(
                f"{self.base_url}/api/users/{self._user_id}/items/top?limit=1",
                timeout=5,
            )
            if r.status_code != 200:
                return {"items": 0, "tags": 0}
            tags = self.get_tags()
            return {"items": -1, "tags": len(tags)}  # -1 表示"未知但有数据"
        except Exception:
            return {"items": 0, "tags": 0}


class ZoteroMCPClient:
    """Zotero MCP JSON-RPC 2.0 客户端（可选高级功能：全文搜索+标签同步）"""

    def __init__(self, base_url="http://127.0.0.1:23120", timeout=15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._id = 0
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    def _next_id(self):
        self._id += 1
        return self._id

    def _call(self, method, params=None):
        r = self._session.post(
            f"{self.base_url}/mcp",
            json={
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": method,
                "params": params or {},
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise Exception(f"MCP Error: {data['error']}")
        return data.get("result", {})

    def ping(self):
        try:
            return (
                self._session.get(f"{self.base_url}/ping", timeout=3).status_code == 200
            )
        except:
            return False

    def call_tool(self, name, arguments=None):
        result = self._call("tools/call", {"name": name, "arguments": arguments or {}})
        content = result.get("content", [])
        return json.loads(content[0].get("text", "{}")) if content else {}

    def search(self, query, limit=20, year_from=0, year_to=0, tags=None):
        args = {"q": query, "limit": min(limit, 50), "mode": "preview"}
        if year_from > 0 and year_to > 0:
            args["yearRange"] = f"{year_from}-{year_to}"
        if tags:
            args["tags"] = tags
            args["tagMode"] = "any"
            args["tagMatch"] = "contains"
        return self.call_tool("search_library", args).get("results", [])

    def get_item(self, item_key, mode="standard"):
        return self.call_tool("get_item_details", {"itemKey": item_key, "mode": mode})


@register_source
class ZoteroMCPSource(BaseSearchSource):
    """Zotero 本地搜索源 — 三层后端：原生 API (Zotero 9+) > MCP 插件 > SQLite"""

    SOURCE_NAME = "zotero_mcp"
    DISPLAY_NAME = "Zotero Local"
    DEFAULT_ENABLED = False
    MAX_RESULTS = 50

    def __init__(self, **config):
        super().__init__(**config)
        self._native = None
        self._sqlite = None
        self._mcp_client = None
        self._backend = "none"
        # Tier 1: Zotero 9 原生 API (localhost:23119)
        self._native = ZoteroNativeClient()
        if self._native.ping():
            self._backend = "native"
            return
        # Tier 2: MCP 插件
        mcp_url = config.get("zotero_mcp_url", "http://127.0.0.1:23120")
        if mcp_url and not mcp_url.startswith("http"):
            mcp_url = f"http://127.0.0.1:{mcp_url}"
        try:
            r = requests.get(f"{mcp_url}/ping", timeout=2)
            if r.status_code == 200:
                self._mcp_client = (
                    ZoteroMCPClient(base_url=mcp_url)
                    if "ZoteroMCPClient" in globals()
                    else None
                )
                if self._mcp_client:
                    self._backend = "mcp"
                    return
        except Exception:
            pass
        # Tier 3: SQLite 直读
        custom_dir = config.get("data_dir", "") or ""
        profile = ZoteroSQLiteReader.find_profile_dir(custom_dir=custom_dir)
        self._sqlite = ZoteroSQLiteReader(profile_dir=profile)
        if self._sqlite.available:
            self._backend = "sqlite"

    def is_available(self) -> bool:
        return self._backend != "none"

    @property
    def backend_type(self) -> str:
        return self._backend

    def get_stats(self) -> dict:
        if self._backend == "native":
            return self._native.get_stats()
        if self._backend == "sqlite" and self._sqlite:
            s = self._sqlite.stats
            s["backend"] = "sqlite"
            return s
        return {"items": 0, "tags": 0, "backend": self._backend}

    def search(
        self,
        query: str,
        year_from: int = 0,
        year_to: int = 0,
        max_results: int = 50,
        **kwargs,
    ) -> list:
        if self._backend == "native":
            try:
                return self._native.search(query, year_from, year_to, max_results)
            except Exception as e:
                print(f"[Zotero Native] search failed: {e}")
                return []
        if self._backend == "mcp" and self._mcp_client:
            try:
                return self._search_mcp(query, year_from, year_to, max_results)
            except Exception as e:
                print(f"[Zotero MCP] search failed: {e}")
                return []
        if self._backend == "sqlite" and self._sqlite:
            return self._sqlite.search(
                query, limit=max_results, year_from=year_from, year_to=year_to
            )
        return []

    def _search_mcp(self, query, year_from, year_to, max_results):
        results = self._mcp_client.search(
            query, limit=max_results, year_from=year_from, year_to=year_to
        )
        papers = []
        for item in results:
            try:
                p = Paper(source="zotero_mcp")
                p.title = item.get("title", "") or ""
                if not p.title:
                    continue
                creators = item.get("creators", "")
                if creators:
                    p.authors = [a.strip() for a in creators.split(",") if a.strip()]
                date_str = item.get("date", "")
                if date_str:
                    try:
                        p.year = int(date_str[:4])
                    except ValueError:
                        pass
                matched_tags = item.get("matchedTags", [])
                if matched_tags:
                    p.keywords = list(matched_tags)
                papers.append(p)
            except Exception:
                continue
        # 补全详细信息（最多 10 篇）
        for p in papers[:10]:
            try:
                if not p.title:
                    continue
                r2 = self._mcp_client.search(p.title, limit=1)
                if not r2:
                    continue
                detail = self._mcp_client.get_item(
                    r2[0].get("key", ""), mode="standard"
                )
                if not detail:
                    continue
                if not p.doi:
                    p.doi = detail.get("DOI", "") or ""
                if not p.journal:
                    p.journal = detail.get("publicationTitle", "") or ""
                if not p.volume:
                    p.volume = str(detail.get("volume", "") or "")
                if not p.issue:
                    p.issue = str(detail.get("issue", "") or "")
                if not p.pages:
                    p.pages = str(detail.get("pages", "") or "")
                if not p.abstract:
                    p.abstract = (detail.get("abstractNote", "") or "")[:500]
                tags = detail.get("tags", [])
                if tags and not p.keywords:
                    p.keywords = [str(t) for t in tags[:10]]
                url = detail.get("url", "") or ""
                if url and not p.oa_url:
                    p.oa_url = url
            except Exception:
                continue
        return papers


@register_source
class ZenodoSource(BaseSearchSource):
    """Zenodo 搜索源 — 免费开放仓储，覆盖数据集/软件/预印本/报告等非期刊文献"""

    SOURCE_NAME = "zenodo"
    DISPLAY_NAME = "Zenodo"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 30
    BASE = "https://zenodo.org/api"

    def __init__(self, **config):
        super().__init__(**config)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "PaperLens/1.0"

    def search(
        self,
        query: str,
        year_from: int = 0,
        year_to: int = 0,
        max_results: int = 30,
        **kwargs,
    ) -> list:
        try:
            params = {"q": query, "size": min(max_results, 50), "page": 1}
            r = self.session.get(f"{self.BASE}/records", params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            papers = []
            for hit in data.get("hits", {}).get("hits", []):
                try:
                    meta = hit.get("metadata", {})
                    p = Paper(source="zenodo")
                    p.title = meta.get("title", "") or ""
                    if not p.title:
                        continue
                    p.abstract = (meta.get("description", "") or "")[:500]
                    p.doi = meta.get("doi", "") or ""
                    p.year = 0
                    pub = meta.get("publication_date", "")
                    if pub:
                        try:
                            p.year = int(pub[:4])
                        except ValueError:
                            pass
                    creators = meta.get("creators", [])
                    for c in creators[:10]:
                        name = c.get("name", "") or ""
                        if name:
                            p.authors.append(name)
                    journal = meta.get("journal", {}).get("title", "") or ""
                    p.journal = journal or "Zenodo"
                    keywords = meta.get("keywords", [])
                    if isinstance(keywords, list):
                        p.keywords = [str(k) for k in keywords[:10]]
                    p.oa_url = (
                        hit.get("links", {}).get("self_html", "")
                        or meta.get("doi_url", "")
                        or ""
                    )
                    papers.append(p)
                except Exception:
                    continue
            return papers
        except Exception as e:
            print(f"[Zenodo] search error: {e}")
            return []


@register_source
class DataCiteSource(BaseSearchSource):
    """DataCite 搜索源 — 全球 DOI 注册机构，覆盖数据集/软件/预印本/学位论文"""

    SOURCE_NAME = "datacite"
    DISPLAY_NAME = "DataCite"
    DEFAULT_ENABLED = True
    MAX_RESULTS = 30
    BASE = "https://api.datacite.org"

    def __init__(self, **config):
        super().__init__(**config)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "PaperLens/1.0 (mailto:vanthree31@gmail.com)"
        )

    def search(
        self,
        query: str,
        year_from: int = 0,
        year_to: int = 0,
        max_results: int = 30,
        **kwargs,
    ) -> list:
        try:
            params = {
                "query": query,
                "page[size]": min(max_results, 50),
                "sort": "relevance",
            }
            if year_from or year_to:
                yf = year_from or 1000
                yt = year_to or datetime.now().year
                params["query"] = f"{query} AND publicationYear:[{yf} TO {yt}]"
            r = self.session.get(f"{self.BASE}/dois", params=params, timeout=15)
            if r.status_code == 429:
                time.sleep(5)
                r = self.session.get(f"{self.BASE}/dois", params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            papers = []
            for item in data.get("data", []):
                try:
                    attrs = item.get("attributes", {})
                    p = Paper(source="datacite")
                    titles = attrs.get("titles", [{}])
                    p.title = (titles[0].get("title", "") if titles else "") or ""
                    if not p.title:
                        continue
                    descs = attrs.get("descriptions", [{}])
                    p.abstract = (descs[0].get("description", "") if descs else "")[
                        :500
                    ]
                    p.doi = attrs.get("doi", "") or ""
                    p.year = attrs.get("publicationYear", 0) or 0
                    creators = attrs.get("creators", [])
                    for c in creators[:10]:
                        name = c.get("name", "") or ""
                        if name:
                            p.authors.append(name)
                    pub = attrs.get("publisher", "") or ""
                    if pub:
                        p.journal = pub
                    subjects = attrs.get("subjects", [])
                    if subjects:
                        p.keywords = [
                            s.get("subject", "")
                            for s in subjects[:10]
                            if s.get("subject")
                        ]
                    if not p.oa_url:
                        p.oa_url = (
                            attrs.get("url", "") or f"https://doi.org/{p.doi}"
                            if p.doi
                            else ""
                        )
                    p.citation_count = attrs.get("citationCount", 0) or 0
                    papers.append(p)
                except Exception:
                    continue
            return papers
        except Exception as e:
            print(f"[DataCite] search error: {e}")
            return []


class SearchEngine:
    """聚合检索引擎"""

    def __init__(self, config: dict):
        proxy_cfg = config.get("proxy", {})
        proxy = {}
        if proxy_cfg.get("http"):
            proxy["http"] = proxy_cfg["http"]
        if proxy_cfg.get("https"):
            proxy["https"] = proxy_cfg["https"]
        proxy = proxy if proxy else None

        # EZproxy 配置
        ap_cfg = config.get("access_proxy", {})
        self.access_proxy = None
        if ap_cfg.get("mode") == "ezproxy" and ap_cfg.get("ezproxy_host"):
            self.access_proxy = EZproxyRewriter(ap_cfg["ezproxy_host"])

        # CARSI cookies 配置
        carsi_cookies = ap_cfg.get("carsi_cookies", {})
        self.carsi_cookies = carsi_cookies if carsi_cookies else None

        # ScraperAPI 配置
        scraperapi_key = config.get("scraperapi_key", "")
        self.scraperapi = ScraperAPIProxy(scraperapi_key) if scraperapi_key else None

        # --- 注册表驱动的数据源加载 ---
        sources_cfg = config.get("sources", {})
        pubmed_cfg = sources_cfg.get("pubmed", {})
        # 共享 email（多个数据源需要）
        shared_email = pubmed_cfg.get("email", "")

        # 注册表模式：从 _SOURCE_REGISTRY 动态加载数据源
        self._sources = {}  # source_name -> adapter instance
        for source_name, source_cls in _SOURCE_REGISTRY.items():
            src_cfg = sources_cfg.get(source_name, {})
            default_enabled = getattr(source_cls, "DEFAULT_ENABLED", True)
            if not src_cfg.get("enabled", default_enabled):
                continue
            try:
                # 构造配置，适配器通过 **config 接收所需参数
                build_config = {
                    "proxy": proxy,
                    "access_proxy": self.access_proxy,
                    "carsi_cookies": self.carsi_cookies,
                    "email": shared_email,
                }
                # 将源特定配置合并（排除 enabled 键）
                for k, v in src_cfg.items():
                    if k != "enabled":
                        build_config[k] = v
                instance = source_cls(**build_config)
                if instance.is_available():
                    self._sources[source_name] = instance
            except Exception as e:
                print(f"[WARN] Failed to initialize source {source_name}: {e}")

        # 保持向后兼容的属性引用
        self.pubmed = getattr(self._sources.get("pubmed"), "_impl", None)
        self.openalex = getattr(self._sources.get("openalex"), "_impl", None)
        self.google_scholar = getattr(
            self._sources.get("google_scholar"), "_impl", None
        )
        self.cnki = getattr(self._sources.get("cnki"), "_impl", None)
        self.wanfang = getattr(self._sources.get("wanfang"), "_impl", None)
        self.vip = getattr(self._sources.get("vip"), "_impl", None)
        self.bing_academic = getattr(self._sources.get("bing_academic"), "_impl", None)
        self.semantic_scholar = getattr(
            self._sources.get("semantic_scholar"), "_impl", None
        )
        self.crossref = getattr(self._sources.get("crossref"), "_impl", None)
        self.arxiv = getattr(self._sources.get("arxiv"), "_impl", None)
        self.dblp = getattr(self._sources.get("dblp"), "_impl", None)
        self.biorxiv = getattr(self._sources.get("biorxiv"), "_impl", None)
        self.agris = getattr(self._sources.get("agris"), "_impl", None)
        self.europepmc = getattr(self._sources.get("europepmc"), "_impl", None)
        self.core = getattr(self._sources.get("core"), "_impl", None)
        self.lens = getattr(self._sources.get("lens"), "_impl", None)
        self.unpaywall = getattr(self._sources.get("unpaywall"), "_impl", None)
        self.sciencedirect = getattr(self._sources.get("sciencedirect"), "_impl", None)
        self.scopus = getattr(self._sources.get("scopus"), "_impl", None)
        self.jstor = getattr(self._sources.get("jstor"), "_impl", None)
        self.acs = getattr(self._sources.get("acs"), "_impl", None)
        self.optica = getattr(self._sources.get("optica"), "_impl", None)
        self.iop = getattr(self._sources.get("iop"), "_impl", None)
        self.aip = getattr(self._sources.get("aip"), "_impl", None)
        self.rsc = getattr(self._sources.get("rsc"), "_impl", None)
        self.springer = getattr(self._sources.get("springer"), "_impl", None)
        self.wiley = getattr(self._sources.get("wiley"), "_impl", None)
        self.ieee = getattr(self._sources.get("ieee"), "_impl", None)
        self.muse = getattr(self._sources.get("muse"), "_impl", None)

        # 数据源健康监控
        self._health_monitor = SourceHealthMonitor()

        # [新增] 初始化混合翻译器
        # 翻译配置
        translation_cfg = config.get("translation", {})
        self.translation_enabled = translation_cfg.get("enabled", True)
        self.ai_translation_enabled = translation_cfg.get("ai_enabled", False)
        self.synonym_expansion_enabled = translation_cfg.get("synonym_expansion", True)

        # 缓存文件路径
        from pathlib import Path

        cache_dir = Path.home() / ".paperlens"
        cache_file = str(cache_dir / "translation_cache.json")

        # 创建翻译器实例（AI provider 由外部设置）
        self._translator = HybridTranslator(
            ai_provider=None,  # 由 set_ai_provider() 设置
            cache_file=cache_file,
        )

        # 设置全局翻译器
        _set_translator(self._translator)

        # 搜索结果缓存（LRU + TTL 30 分钟，最大 100 条）
        self._search_cache = _SearchResultCache(maxsize=100, ttl=300)  # 5分钟内存缓存

        # L2 持久化缓存（SQLite，7天过期，后台异步写入）
        self._persistent_cache = SQLiteSearchCache(ttl_days=1)  # 1天 SQLite 缓存
        self._search_cache.set_persistent_cache(self._persistent_cache)

        # BM25 相关性评分器
        self._bm25_scorer = BM25Scorer(k1=1.5, b=0.75)

    def set_ai_provider(self, ai_provider):
        """设置AI提供商用于翻译"""
        if self.ai_translation_enabled:
            self._translator._ai_provider = ai_provider
            print("[INFO] AI翻译已启用")

    def preprocess_query(
        self, query: str, year_from=None, year_to=0, pub_type="", author=""
    ) -> dict:
        """查询预处理：使用规则引擎提取结构化信息

        对用户输入进行预理解，提取时间范围、文献类型、DOI、作者等，
        并将结果合并到搜索参数中。规则引擎的提取结果作为下限，
        显式传入的参数优先级更高。

        Args:
            query: 用户原始查询
            year_from: 显式传入的起始年份（None 表示未指定）
            year_to: 显式传入的结束年份（0 表示未指定）
            pub_type: 显式传入的文献类型
            author: 显式传入的作者名

        Returns:
            dict:
                query (str): 清洗后的查询词
                year_from (int): 最终起始年份
                year_to (int): 最终结束年份
                pub_type (str): 最终文献类型
                doi (str|None): 提取的 DOI
                author (str): 最终作者名
                suggestions (list[str]): 查询建议
                parsed_info (dict): 预理解的完整解析结果
        """
        current_year = datetime.now().year

        # 默认年份
        if year_from is None:
            year_from = current_year - 10
        if not year_to:
            year_to = current_year

        # 调用 QueryUnderstanding 解析
        parsed = QueryUnderstanding.parse(query, current_year)

        # 合并结果：显式参数 > 规则提取 > 默认值
        # 查询词：使用清洗后的版本
        final_query = parsed["query"] if parsed["query"] else query

        # 年份：显式参数优先
        final_year_from = year_from
        final_year_to = year_to
        if parsed["year_from"] is not None and year_from == current_year - 10:
            # 显式参数是默认值，使用规则提取的值
            final_year_from = parsed["year_from"]
        if parsed["year_to"] is not None and year_to == current_year:
            # 显式参数是默认值，使用规则提取的值
            final_year_to = parsed["year_to"]

        # 文献类型：显式参数优先
        final_pub_type = pub_type if pub_type else parsed["pub_type"]

        # 作者：显式参数优先
        final_author = author if author else (parsed["author"] or "")

        # DOI：直接使用提取结果
        doi = parsed["doi"]

        # 如果提取到作者且不在查询词中，追加到查询
        if final_author and final_author not in final_query:
            final_query = f"{final_author} {final_query}".strip()

        # 日志
        if (
            parsed["year_from"]
            or parsed["pub_type"]
            or parsed["doi"]
            or parsed["author"]
        ):
            print(
                f"[QUERY UNDERSTAND] '{query}' -> "
                f"query='{final_query}' year={final_year_from}-{final_year_to} "
                f"pub_type='{final_pub_type}' doi={doi} author='{final_author}'"
            )

        return {
            "query": final_query,
            "year_from": final_year_from,
            "year_to": final_year_to,
            "pub_type": final_pub_type,
            "doi": doi,
            "author": final_author,
            "suggestions": parsed["suggestions"],
            "parsed_info": parsed,
        }

    @staticmethod
    def _compute_sources_hash(*sources_enabled: bool) -> str:
        """根据数据源启用状态生成哈希值，用于缓存 key

        支持两种调用方式：
        - _compute_sources_hash(True, False, True, ...) -- 旧接口，按位拼接
        - _compute_sources_hash({"pubmed", "openalex"}) -- 新接口，集合排序后拼接
        """
        if len(sources_enabled) == 1 and isinstance(sources_enabled[0], set):
            # 新接口：传入一个 set
            parts = sorted(sources_enabled[0])
        else:
            # 旧接口：按位拼接
            parts = ["1" if s else "0" for s in sources_enabled]
        return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]

    @staticmethod
    def _word_boundary_match(keyword: str, target: str) -> bool:
        """单词边界匹配 — 'nature' 匹配 'Nature Communications' 但不匹配 'Signature'"""
        import re

        pattern = r"(?<![a-z])" + re.escape(keyword) + r"(?![a-z])"
        return bool(re.search(pattern, target, re.IGNORECASE))

    def _match_journal(self, paper_journal: str, journals: list) -> bool:
        """检查论文期刊是否匹配筛选条件

        匹配优先级：
        1. ISSN 精确匹配（最可靠）
        2. 期刊组匹配
        3. 名称包含匹配（回退）

        Args:
            paper_journal: 论文的期刊名称
            journals: 用户指定的期刊列表（支持期刊组名）

        Returns:
            bool: 是否匹配
        """
        if not paper_journal:
            return False

        paper_journal_lower = paper_journal.lower().strip()

        # 获取论文期刊的 ISSN（如果有的话）
        paper_issn = _resolve_journal_issn(paper_journal)

        for j in journals:
            j_lower = j.lower().strip()

            # 1. 优先 ISSN 精确匹配
            if paper_issn:
                # 获取用户指定期刊的 ISSN
                user_issn = _resolve_journal_issn(j)
                if user_issn and paper_issn == user_issn:
                    return True

            # 2. 检查是否是期刊组名
            if j_lower in JOURNAL_GROUPS:
                group_journals = [name.lower() for name in JOURNAL_GROUPS[j_lower]]
                if any(
                    self._word_boundary_match(gj, paper_journal_lower)
                    for gj in group_journals
                ):
                    return True

            # 3. 单词边界匹配 — 避免 "nature" 误匹配 "signature" / "natural products"
            if self._word_boundary_match(j_lower, paper_journal_lower):
                return True

        return False

    def _title_matches_keywords(self, paper, keywords: set) -> bool:
        """检查论文标题是否包含至少一个搜索关键词（宁缺毋滥）

        用于过滤与查询完全不相关的论文。期刊过滤的论文始终保留
        （期刊筛选已保证相关性）。

        Args:
            paper: 论文对象
            keywords: 搜索关键词集合

        Returns:
            bool: 标题匹配或应保留
        """
        title = (paper.title or "").lower()
        if not title:
            return False  # 无标题 → 不保留，宁缺毋滥

        for kw in keywords:
            if self._word_boundary_match(kw.lower(), title):
                return True

        # 期刊筛选的论文保留（期刊已保证相关性）
        if getattr(paper, "_journal_matched", False):
            return True

        # DOI 匹配的保留（通过 DOI 直查或 rich 补全的论文）
        if paper.doi and any(kw.lower() in title for kw in keywords):
            return True

        return False

    def _score_relevance(self, paper, keywords: set) -> float:
        """计算论文与搜索关键词的相关性分数（BM25 算法）

        使用简化版 BM25：
        - IDF 权重：罕见词权重高，常见词权重低
        - TF 饱和：词频增长到一定程度后收益递减（k1 控制）
        - 文档长度归一化：长文档的词频被适度惩罚（b 控制）
        - 标题匹配权重 > 摘要匹配权重

        Fallback：如果 scorer 未就绪，回退到原始评分逻辑。
        """
        if not keywords:
            return 0.0

        title = (paper.title or "").lower()
        abstract = (paper.abstract or "").lower()

        scorer = getattr(self, "_bm25_scorer", None)

        # Fallback：scorer 未就绪时使用原始评分
        if not scorer or not scorer.is_ready():
            return self._score_relevance_legacy(paper, keywords)

        # BM25 参数
        k1 = scorer.k1
        b = scorer.b
        idf_cache = scorer.get_idf_cache()
        avg_title_len = max(scorer.avg_title_len, 1.0)
        avg_abstract_len = max(scorer.avg_abstract_len, 1.0)

        # 计算标题词频
        title_tokens = title.split() if title else []
        title_len = len(title_tokens)
        title_tf = {}
        for token in title_tokens:
            title_tf[token] = title_tf.get(token, 0) + 1

        # 计算摘要词频
        abstract_tokens = abstract.split() if abstract else []
        abstract_len = len(abstract_tokens)
        abstract_tf = {}
        for token in abstract_tokens:
            abstract_tf[token] = abstract_tf.get(token, 0) + 1

        score = 0.0
        for kw in keywords:
            kw_lower = kw.lower()

            # 获取 IDF 值
            idf = idf_cache.get(kw_lower, 0.5)

            # 标题匹配：BM25 TF
            tf_title = title_tf.get(kw_lower, 0)
            if tf_title > 0:
                norm_title = 1.0 - b + b * (title_len / avg_title_len)
                bm25_tf_title = (tf_title * (k1 + 1)) / (tf_title + k1 * norm_title)
                score += idf * bm25_tf_title * 3.0  # 标题权重系数 3.0

                # 标题开头匹配额外加分
                if title.startswith(kw_lower):
                    score += idf * 1.0

            # 摘要匹配：BM25 TF
            tf_abstract = abstract_tf.get(kw_lower, 0)
            if tf_abstract > 0:
                norm_abstract = 1.0 - b + b * (abstract_len / avg_abstract_len)
                bm25_tf_abstract = (tf_abstract * (k1 + 1)) / (
                    tf_abstract + k1 * norm_abstract
                )
                score += idf * bm25_tf_abstract * 1.0  # 摘要权重系数 1.0

        # 关键词密度加分（标题中关键词占比）
        if title and keywords:
            title_words = set(title_tokens)
            overlap = len(keywords & title_words)
            score += overlap * 0.5

        return score

    def _score_relevance_legacy(self, paper, keywords: set) -> float:
        """原始评分逻辑（BM25 不可用时的 fallback）"""
        title = (paper.title or "").lower()
        abstract = (paper.abstract or "").lower()

        score = 0.0
        for kw in keywords:
            kw_lower = kw.lower()
            if _contains_chinese(kw_lower):
                if kw_lower in title:
                    score += 3.0
            else:
                try:
                    if re.search(r"\b" + re.escape(kw_lower) + r"\b", title):
                        score += 3.0
                        if title.startswith(kw_lower):
                            score += 1.0
                    elif kw_lower in title:
                        score += 2.0
                except Exception:
                    if kw_lower in title:
                        score += 2.0
            if kw_lower in abstract:
                score += 1.0

        if title and keywords:
            title_words = set(title.split())
            overlap = len(keywords & title_words)
            score += overlap * 0.5

        return score

    def search(
        self,
        query: str,
        year_from=None,
        year_to=0,
        sort="relevance",
        max_results=50,
        enabled_sources=None,
        use_pubmed=True,
        use_openalex=True,
        use_google_scholar=False,
        use_cnki=True,
        use_wanfang=True,
        use_vip=True,
        use_bing_academic=False,
        use_semantic_scholar=True,
        use_crossref=True,
        use_arxiv=True,
        use_sciencedirect=True,
        use_scopus=True,
        use_jstor=True,
        use_dblp=True,
        use_biorxiv=True,
        use_agris=True,
        use_acs=True,
        use_optica=True,
        use_iop=True,
        use_aip=True,
        use_rsc=True,
        use_europepmc=True,
        use_springer=True,
        use_wiley=True,
        use_ieee=True,
        use_muse=True,
        use_core=True,
        use_lens=True,
        use_lens_patents=False,
        journal="",
        field="",
        mesh_term="",
        pub_type="",
        smart_routing=False,
        force_refresh=False,
        oa_only=False,
        affiliation="",
        query_zh="",
    ) -> tuple:
        """聚合检索（并发执行）

        Args:
            query: 检索词（可含 PubMed 字段标签）
            journal: 期刊过滤
            field: 默认字段标签（ti/tiab/au/tw）
            mesh_term: MeSH 主题词
            pub_type: 文献类型（review/clinical trial 等）
            enabled_sources: 数据源名称集合（如 {"pubmed", "openalex"}），
                传入时覆盖所有 use_xxx 参数。None 表示使用 use_xxx 参数。
            smart_routing: 启用智能学科路由，基于查询关键词自动筛选相关数据源，
                减少无关 API 调用。默认 False（向后兼容）。
            use_pubmed: [旧接口] 启用 PubMed
            use_openalex: [旧接口] 启用 OpenAlex
            ...其余 use_xxx 参数同理...
            query_zh: 中文查询（用于中文数据库），为空时自动从 query 中提取

        Returns:
            tuple: (papers, errors) — errors 为各数据源错误信息列表
        """
        # 解析 journal 参数：支持单值字符串、逗号分隔字符串和数组格式
        if isinstance(journal, list):
            journals = [j.strip() for j in journal if j.strip()]
        elif journal:
            # 支持逗号分隔的多期刊过滤
            journals = [j.strip() for j in journal.split(",") if j.strip()]
        else:
            journals = []

        # DOI 直查快速通道：检测到 DOI 格式时，先查 CrossRef 拿完整元数据
        doi_match = re.match(r"^(10\.\d{4,}/\S+)$", query.strip())
        if doi_match:
            doi = doi_match.group(1).strip().lower()
            try:
                r = requests.get(
                    f"https://api.crossref.org/works/{doi}",
                    timeout=10,
                    headers={"User-Agent": "PaperLens/1.0"},
                )
                if r.status_code == 200:
                    msg = r.json().get("message", {})
                    p = Paper(source="crossref")
                    titles = msg.get("title", [""])
                    p.title = (titles[0] if titles else "") or ""
                    p.doi = msg.get("DOI", "") or doi
                    p.abstract = (msg.get("abstract", "") or "")[:500]
                    p.journal = (
                        msg.get("container-title", [""])[0]
                        if msg.get("container-title")
                        else ""
                    ) or ""
                    p.volume = str(msg.get("volume", "") or "")
                    p.issue = str(msg.get("issue", "") or "")
                    p.pages = str(msg.get("page", "") or "")
                    issn_list = msg.get("ISSN", [])
                    if issn_list:
                        p.issn = str(issn_list[0])
                    pub = msg.get("published-print", msg.get("published-online", {}))
                    if pub and pub.get("date-parts"):
                        parts = pub["date-parts"][0]
                        if parts and parts[0]:
                            p.year = parts[0]
                    for a in (msg.get("author", []) or [])[:10]:
                        name = f"{a.get('given', '')} {a.get('family', '')}".strip()
                        if name:
                            p.authors.append(name)
                    p.citation_count = msg.get("is-referenced-by-count", 0)
                    link_list = msg.get("link", [])
                    if link_list:
                        p.oa_url = link_list[0].get("URL", "") or ""
                    if p.title:
                        print(
                            f"[DOI Lookup] Found: {p.title[:60]}... ({p.journal}, {p.year})"
                        )
                        self._last_timing_info = {
                            "crossref_doi": {"duration": 0.5, "status": "ok"}
                        }
                        return [p], []
            except Exception as e:
                print(f"[DOI Lookup] CrossRef error: {e}")

        # 动态获取当前年份和默认年份范围
        current_year = datetime.now().year
        if year_from is None:
            year_from = current_year - 10
        if not year_to:
            year_to = current_year

        # --- 查询预理解（规则引擎） ---
        # 从自然语言查询中提取时间范围、文献类型、DOI、作者等结构化信息
        # 显式传入的参数优先级高于规则提取
        parsed_query = self.preprocess_query(query, year_from, year_to, pub_type)
        query = parsed_query["query"]
        # 仅当显式参数是默认值时，使用规则提取的值
        if (
            year_from == current_year - 10
            and parsed_query["year_from"] != current_year - 10
        ):
            year_from = parsed_query["year_from"]
        if year_to == current_year and parsed_query["year_to"] != current_year:
            year_to = parsed_query["year_to"]
        if not pub_type and parsed_query["pub_type"]:
            pub_type = parsed_query["pub_type"]

        # --- 智能学科路由 ---
        if smart_routing and enabled_sources is not None:
            enabled_sources = DisciplineRouter.filter_sources(query, enabled_sources)

        # --- DOI 快速路由 ---
        # 如果预理解提取到 DOI，直接走 DOI 精确查询，跳过全文检索
        if parsed_query.get("doi"):
            doi = parsed_query["doi"]
            print(f"[QUERY UNDERSTAND] DOI detected: {doi}, routing to search_by_doi")
            paper = self.search_by_doi(doi)
            if paper:
                return [paper], []
            # DOI 查询失败，回退到常规搜索
            print("[QUERY UNDERSTAND] DOI lookup failed, falling back to full search")

        # --- 搜索结果缓存检查 ---
        # 注意：缓存 key 仅包含 query + year_from + year_to + sources_hash
        # journal/field/mesh_term/pub_type/sort/max_results 不参与缓存 key
        # 这些参数在前端通常固定，同一查询重复搜索时缓存有效
        sources_hash = self._compute_sources_hash(
            enabled_sources
            if enabled_sources is not None
            else (
                use_pubmed,
                use_openalex,
                use_google_scholar,
                use_cnki,
                use_wanfang,
                use_vip,
                use_bing_academic,
                use_semantic_scholar,
                use_crossref,
                use_arxiv,
                use_sciencedirect,
                use_scopus,
                use_jstor,
                use_dblp,
                use_biorxiv,
                use_agris,
                use_acs,
                use_optica,
                use_iop,
                use_aip,
                use_rsc,
                use_europepmc,
                use_springer,
                use_wiley,
                use_ieee,
                use_muse,
                use_core,
                use_lens,
            )
        )
        # 缓存 key 追加 journal/field/pub_type 过滤参数，避免不同筛选共用缓存
        filter_seed = hashlib.md5(f"{journal}|{field}|{pub_type}".encode()).hexdigest()[
            :8
        ]
        sources_hash = f"{sources_hash}_{filter_seed}"
        # force_refresh 时跳过缓存
        if not force_refresh:
            cached = self._search_cache.get(query, year_from, year_to, sources_hash)
            if cached is not None:
                stats = self._search_cache.stats()
                print(
                    f"[CACHE HIT] query='{query[:50]}' | 命中率 {stats['hit_rate']} "
                    f"({stats['hits']}hit/{stats['misses']}miss) 缓存 {stats['size']}/{stats['maxsize']}"
                )
                return cached, []
        else:
            print("[CACHE SKIP] force_refresh=True, 跳过缓存")

        # [Fix] 中文查询处理：检测中文并翻译为英文
        # 中文数据库（CNKI/Wanfang/VIP）使用原始中文查询
        # 英文数据库（PubMed/OpenAlex等）使用翻译后的英文查询
        is_chinese_query = _contains_chinese(query)
        # 如果外部传入了 query_zh，使用它；否则从 query 中提取
        if not query_zh:
            query_zh = query  # 原始中文查询

        # 清理查询：去掉自然语言部分（"找一下周金华发表的论文" → "周金华"）
        query = _clean_search_query(query)
        query_zh = _clean_search_query(query_zh)

        # 使用混合翻译器（字典+缓存+AI回退）
        if is_chinese_query and self.translation_enabled:
            query_en = self._translator.translate(query)
        else:
            query_en = query

        # 同义词扩展（对翻译后的英文查询，也对直接输入的英文查询生效）
        if self.synonym_expansion_enabled:
            query_en = _expand_synonyms(query_en)

        # 如果翻译后仍有中文（字典未覆盖），记录日志
        if is_chinese_query and _contains_chinese(query_en):
            print(f"[INFO] 中文查询部分翻译: '{query}' -> '{query_en}'")

        # 构建搜索任务列表
        tasks = self._build_search_tasks(
            query_en,
            query_zh,
            year_from,
            year_to,
            sort,
            max_results,
            journal,
            field,
            mesh_term,
            pub_type,
            enabled_sources=enabled_sources,
            use_pubmed=use_pubmed,
            use_openalex=use_openalex,
            use_google_scholar=use_google_scholar,
            use_cnki=use_cnki,
            use_wanfang=use_wanfang,
            use_vip=use_vip,
            use_bing_academic=use_bing_academic,
            use_semantic_scholar=use_semantic_scholar,
            use_crossref=use_crossref,
            use_arxiv=use_arxiv,
            use_sciencedirect=use_sciencedirect,
            use_scopus=use_scopus,
            use_jstor=use_jstor,
            use_dblp=use_dblp,
            use_biorxiv=use_biorxiv,
            use_agris=use_agris,
            use_acs=use_acs,
            use_optica=use_optica,
            use_iop=use_iop,
            use_aip=use_aip,
            use_rsc=use_rsc,
            use_europepmc=use_europepmc,
            use_springer=use_springer,
            use_wiley=use_wiley,
            use_ieee=use_ieee,
            use_muse=use_muse,
            use_core=use_core,
            use_lens=use_lens,
            use_lens_patents=use_lens_patents,
        )

        # 并发执行所有搜索任务
        all_papers, errors, source_status, timing_info = self._run_search_tasks(tasks)

        # 保存 timing 信息供 API 层读取
        self._last_timing_info = timing_info

        # 后处理
        unique, errors = self._post_process_results(
            all_papers,
            errors,
            query,
            query_en,
            is_chinese_query,
            year_from,
            year_to,
            sort,
            journals,
            field,
            pub_type,
            mesh_term,
            oa_only=oa_only,
            affiliation=affiliation,
            query_zh=query_zh,
        )

        # --- 写入搜索结果缓存 ---
        self._search_cache.put(query, year_from, year_to, sources_hash, unique)
        stats = self._search_cache.stats()
        print(
            f"[CACHE PUT] query='{query[:50]}' | 结果 {len(unique)} 条 | "
            f"命中率 {stats['hit_rate']} 缓存 {stats['size']}/{stats['maxsize']}"
        )

        return unique, errors

    # --- 流式搜索辅助方法 ---

    def _build_search_tasks(
        self,
        query_en,
        query_zh,
        year_from,
        year_to,
        sort,
        max_results,
        journal,
        field,
        mesh_term,
        pub_type,
        enabled_sources=None,
        use_pubmed=True,
        use_openalex=True,
        use_google_scholar=False,
        use_cnki=False,
        use_wanfang=False,
        use_vip=False,
        use_bing_academic=False,
        use_semantic_scholar=True,
        use_crossref=True,
        use_arxiv=True,
        use_sciencedirect=True,
        use_scopus=True,
        use_jstor=True,
        use_dblp=True,
        use_biorxiv=True,
        use_agris=True,
        use_acs=True,
        use_optica=True,
        use_iop=True,
        use_aip=True,
        use_rsc=True,
        use_europepmc=True,
        use_springer=True,
        use_wiley=True,
        use_ieee=True,
        use_muse=True,
        use_core=True,
        use_lens=True,
        use_lens_patents=False,
    ):
        """构建搜索任务列表（search() 和 search_stream() 共用）

        当 enabled_sources 不为 None 时，使用注册表驱动模式（新接口）。
        否则，使用 use_xxx 参数模式（旧接口，向后兼容）。
        """
        tasks = []

        if enabled_sources is not None:
            # === 新接口：注册表驱动 ===
            return self._build_tasks_from_registry(
                query_en,
                query_zh,
                year_from,
                year_to,
                sort,
                max_results,
                journal,
                field,
                mesh_term,
                pub_type,
                enabled_sources,
            )

        # === 旧接口：use_xxx 参数（向后兼容） ===
        if use_pubmed and self.pubmed:
            tasks.append(
                (
                    "PubMed",
                    lambda: self._search_pubmed(
                        query_en,
                        year_from,
                        year_to,
                        sort,
                        max_results,
                        journal,
                        field,
                        mesh_term,
                        pub_type,
                    ),
                )
            )

        if use_openalex and self.openalex:
            tasks.append(
                (
                    "OpenAlex",
                    lambda: self.openalex.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results,
                        journal=journal,
                        field=field,
                    ),
                )
            )

        if use_google_scholar and self.google_scholar:
            tasks.append(
                (
                    "Google Scholar",
                    lambda: self.google_scholar.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 20),
                        field=field,
                    ),
                )
            )

        # 中文数据库使用原始中文查询
        if use_cnki and self.cnki:
            tasks.append(
                (
                    "CNKI",
                    lambda: self.cnki.search(
                        query_zh,
                        year_from,
                        year_to,
                        max_results=min(max_results, 20),
                        field=field,
                    ),
                )
            )

        if use_wanfang and self.wanfang:
            tasks.append(
                (
                    "万方",
                    lambda: self.wanfang.search(
                        query_zh,
                        year_from,
                        year_to,
                        max_results=min(max_results, 20),
                        field=field,
                    ),
                )
            )

        if use_vip and self.vip:
            tasks.append(
                (
                    "维普",
                    lambda: self.vip.search(
                        query_zh,
                        year_from,
                        year_to,
                        max_results=min(max_results, 20),
                        field=field,
                    ),
                )
            )

        if use_bing_academic and self.bing_academic:
            tasks.append(
                (
                    "Bing Academic",
                    lambda: self.bing_academic.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 20),
                        field=field,
                    ),
                )
            )

        # 英文数据库使用翻译后的英文查询
        if use_semantic_scholar and self.semantic_scholar:
            tasks.append(
                (
                    "Semantic Scholar",
                    lambda: self.semantic_scholar.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        if use_crossref and self.crossref:
            tasks.append(
                (
                    "CrossRef",
                    lambda: self.crossref.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        if use_arxiv and self.arxiv:
            tasks.append(
                (
                    "arXiv",
                    lambda: self.arxiv.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        # 免费 API 数据源（英文）
        if use_dblp and self.dblp:
            tasks.append(
                (
                    "DBLP",
                    lambda: self.dblp.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        if use_biorxiv and self.biorxiv:
            tasks.append(
                (
                    "bioRxiv",
                    lambda: self.biorxiv.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        if use_agris and self.agris:
            tasks.append(
                (
                    "AGRIS",
                    lambda: self.agris.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        # CrossRef 出版商过滤（免费 API，英文）
        if use_acs and self.acs:
            tasks.append(
                (
                    "ACS",
                    lambda: self.acs.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        if use_optica and self.optica:
            tasks.append(
                (
                    "Optica",
                    lambda: self.optica.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        if use_iop and self.iop:
            tasks.append(
                (
                    "IOP",
                    lambda: self.iop.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        if use_aip and self.aip:
            tasks.append(
                (
                    "AIP",
                    lambda: self.aip.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        if use_rsc and self.rsc:
            tasks.append(
                (
                    "RSC",
                    lambda: self.rsc.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        if use_europepmc and self.europepmc:
            tasks.append(
                (
                    "Europe PMC",
                    lambda: self.europepmc.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        # CORE 和 Lens.org 数据源
        if use_core and self.core:
            tasks.append(
                (
                    "CORE",
                    lambda: self.core.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        if use_lens and self.lens:
            tasks.append(
                (
                    "Lens",
                    lambda: self.lens.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        if use_lens_patents and self.lens:
            tasks.append(
                (
                    "Lens Patent",
                    lambda: self.lens.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        patent_mode=True,
                        field=field,
                    ),
                )
            )

        if use_springer and self.springer:
            tasks.append(
                (
                    "Springer",
                    lambda: self.springer.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        if use_wiley and self.wiley:
            tasks.append(
                (
                    "Wiley",
                    lambda: self.wiley.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        if use_ieee and self.ieee:
            tasks.append(
                (
                    "IEEE",
                    lambda: self.ieee.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        if use_muse and self.muse:
            tasks.append(
                (
                    "MUSE",
                    lambda: self.muse.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        # CARSI 认证数据库（英文查询）
        if use_sciencedirect and self.sciencedirect:
            tasks.append(
                (
                    "ScienceDirect",
                    lambda: self.sciencedirect.search(
                        query_en,
                        year_from,
                        year_to,
                        max_results=min(max_results, 50),
                        field=field,
                    ),
                )
            )

        if use_scopus and self.scopus:
            tasks.append(
                (
                    "Scopus",
                    lambda: self.scopus.search(
                        query_en, year_from, year_to, max_results=min(max_results, 50)
                    ),
                )
            )

        if use_jstor and self.jstor:
            tasks.append(
                (
                    "JSTOR",
                    lambda: self.jstor.search(
                        query_en, year_from, year_to, max_results=min(max_results, 50)
                    ),
                )
            )

        return tasks

    def _build_tasks_from_registry(
        self,
        query_en,
        query_zh,
        year_from,
        year_to,
        sort,
        max_results,
        journal,
        field,
        mesh_term,
        pub_type,
        enabled_sources,
    ):
        """注册表驱动的任务构建（新接口）

        Args:
            enabled_sources: 要启用的数据源名称集合
        """
        tasks = []
        # 构造搜索参数，供适配器的 search() 使用
        extra_kwargs = {
            "sort": sort,
            "journal": journal,
            "field": field,
            "mesh_term": mesh_term,
            "pub_type": pub_type,
        }

        for source_name in enabled_sources:
            if source_name not in self._sources:
                continue
            adapter = self._sources[source_name]
            source_cls = _SOURCE_REGISTRY.get(source_name)
            is_chinese = (
                getattr(source_cls, "IS_CHINESE", False) if source_cls else False
            )
            max_r = getattr(source_cls, "MAX_RESULTS", 50) if source_cls else 50
            effective_max = min(max_results, max_r)
            # 中文数据源使用中文查询，其他使用英文查询
            query_for_source = query_zh if is_chinese else query_en
            display_name = (
                getattr(source_cls, "DISPLAY_NAME", source_name)
                if source_cls
                else source_name
            )

            # 使用默认参数捕获，避免闭包陷阱
            _src = adapter
            _q = query_for_source
            _yf, _yt = year_from, year_to
            _mr = effective_max
            _kw = {k: v for k, v in extra_kwargs.items() if v}
            # CNKI 降级补缺：延迟 5 秒启动，让万方/维普等快速源先返回
            _need_delay = source_name == "cnki"
            tasks.append(
                (
                    display_name,
                    lambda s=_src, q=_q, yf=_yf, yt=_yt, mr=_mr, kw=_kw, d=_need_delay: (
                        (time.sleep(5) if d else None, s.search(q, yf, yt, mr, **kw))[1]
                    ),
                )
            )

        return tasks

    @staticmethod
    def _calc_completeness(p) -> int:
        """计算论文元数据完整性评分 (0-100)"""
        score = 0
        if p.title:
            score += 12
        if p.authors:
            score += 10
        if p.journal:
            score += 8
        if p.year:
            score += 7
        if p.doi:
            score += 8
        if p.abstract:
            score += 18
        if p.volume:
            score += 5
        if p.issue:
            score += 4
        if p.pages:
            score += 5
        if p.issn:
            score += 3
        if p.keywords:
            score += 6
        if p.citation_count:
            score += 5
        if p.oa_url:
            score += 4
        if p.funding:
            score += 3
        if p.article_type:
            score += 2
        return min(score, 100)

    def _post_process_results(
        self,
        all_papers,
        errors,
        query,
        query_en,
        is_chinese_query,
        year_from,
        year_to,
        sort,
        journals,
        field,
        pub_type="",
        mesh_term="",
        oa_only=False,
        affiliation="",
        query_zh="",
    ):
        """后处理搜索结果：去重、年份过滤、期刊过滤、pub_type/mesh_term过滤、引用补充、相关性评分、排序"""
        # 跨源合并去重：DOI/标题匹配 + 字段级非空覆盖空 + 预印本版本检测
        unique = deduplicate_papers(all_papers)
        # 垃圾过滤：缺标题+缺摘要+缺DOI 的论文直接丢弃（宁缺毋滥）
        before = len(unique)
        unique = [p for p in unique if p.title or p.abstract or p.doi]
        dropped = before - len(unique)
        if dropped > 0:
            print(f"[INFO] 过滤掉 {dropped} 篇无元数据的垃圾论文")

        # 全局 DOI 补全：对所有有 DOI 的论文用 CrossRef 补全缺失字段
        needs_enrich = [p for p in unique if p.doi]
        if needs_enrich:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _enrich_one(p):
                try:
                    r = requests.get(
                        f"https://api.crossref.org/works/{p.doi}",
                        headers={"User-Agent": "PaperLens/1.0"},
                        timeout=8,
                    )
                    if r.status_code != 200:
                        return False
                    msg = r.json().get("message", {})
                    enriched = False
                    # 标题
                    if not p.title or len(p.title) < 10:
                        titles = msg.get("title") or []
                        if titles:
                            p.title = titles[0]
                            enriched = True
                    # 摘要
                    if not p.abstract:
                        abstract = msg.get("abstract") or ""
                        if abstract:
                            p.abstract = abstract[:5000]
                            enriched = True
                    # 期刊
                    if not p.journal:
                        containers = msg.get("container-title") or []
                        if containers:
                            p.journal = containers[0]
                            enriched = True
                    # 年份
                    if not p.year:
                        dp = msg.get("published-print") or msg.get("created") or {}
                        dates = dp.get("date-parts", [[0]])[0]
                        if dates[0]:
                            p.year = dates[0]
                            enriched = True
                    # 作者
                    if not p.authors:
                        authors = msg.get("author") or []
                        p.authors = [
                            f"{a.get('given', '')} {a.get('family', '')}".strip()
                            for a in authors
                        ]
                        if p.authors:
                            enriched = True
                    # 卷/期/页
                    if not p.volume:
                        p.volume = str(msg.get("volume") or "")
                        if p.volume:
                            enriched = True
                    if not p.issue:
                        p.issue = str(msg.get("issue") or "")
                        if p.issue:
                            enriched = True
                    if not p.pages:
                        p.pages = str(msg.get("page") or "")
                        if p.pages:
                            enriched = True
                    # 出版商 + ISSN
                    publisher = msg.get("publisher") or ""
                    if publisher and not getattr(p, "publisher", ""):
                        p.publisher = publisher
                        enriched = True
                    issn_list = msg.get("ISSN") or []
                    if issn_list and not getattr(p, "issn", ""):
                        p.issn = issn_list[0]
                        enriched = True
                    return enriched
                except Exception:
                    return False

            # 并发补全（最多 10 并发，避免被 CrossRef 限流）
            enriched = 0
            batch = needs_enrich[:500]  # 最多 500 篇，10 并发约 15s
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {executor.submit(_enrich_one, p): p for p in batch}
                for f in as_completed(futures):
                    if f.result():
                        enriched += 1
            if enriched > 0:
                print(f"[INFO] 全局 DOI 补全: {enriched}/{len(batch)} 篇")
        # 计算元数据完整性评分
        for p in unique:
            p.completeness_score = self._calc_completeness(p)

        # 年份过滤
        if year_from or year_to:
            filtered = []
            for p in unique:
                if not p.year:
                    filtered.append(p)
                    continue
                if year_from and p.year < year_from:
                    continue
                if year_to and p.year > year_to:
                    continue
                filtered.append(p)
            unique = filtered

        # 统一期刊过滤（宁缺毋滥）
        if journals:
            filtered = []
            for p in unique:
                journal = getattr(p, "journal", "") or getattr(p, "source", "") or ""
                if journal and self._match_journal(journal, journals):
                    p._journal_matched = True
                    filtered.append(p)
                # 无 journal 字段的论文直接丢弃
            unique = filtered

        # 跨源 pub_type 过滤（PubMed 已内部过滤，此步骤确保非 PubMed 源结果一致）
        if pub_type and pub_type != "any":
            filtered = []
            for p in unique:
                pt = (getattr(p, "article_type", "") or "").lower()
                if not pt or pub_type.lower() in pt:
                    filtered.append(p)
            unique = filtered

        # 跨源 mesh_term 过滤（基于标题和关键词匹配）
        if mesh_term:
            mesh_lower = mesh_term.lower()
            filtered = []
            for p in unique:
                kw_text = " ".join(p.keywords or []).lower()
                title_text = (p.title or "").lower()
                if mesh_lower in kw_text or mesh_lower in title_text:
                    filtered.append(p)
            unique = filtered

        # 补充引用次数
        if self.openalex:
            unique = self.openalex.enrich_with_citations(unique)

        # 补充 OA 全文链接（Unpaywall）
        if self.unpaywall:
            unique = self.unpaywall.enrich_papers(unique)

        # OA 过滤：只保留有 OA 链接的论文
        if oa_only:
            before_count = len(unique)
            unique = [p for p in unique if p.oa_url]
            filtered_count = before_count - len(unique)
            if filtered_count > 0:
                print(f"[INFO] OA 过滤：移除 {filtered_count} 篇无 OA 链接的论文")

        # 机构/学校过滤
        if affiliation:
            aff_lower = affiliation.lower()
            before_count = len(unique)
            unique = [
                p for p in unique if any(aff_lower in a.lower() for a in p.affiliations)
            ]
            filtered_count = before_count - len(unique)
            if filtered_count > 0:
                print(
                    f"[INFO] 机构过滤：移除 {filtered_count} 篇不匹配 '{affiliation}' 的论文"
                )

        # 作者名过滤：当 field=="au" 时，只保留作者名匹配的论文
        if field == "au":
            # 提取搜索词中的完整作者名（按 OR 分割）
            author_names = []
            for part in re.split(r"\s+OR\s+", query_en, flags=re.IGNORECASE):
                part = part.strip()
                if part:
                    author_names.append(part.lower())
            if query_zh:
                for part in re.split(r"\s+OR\s+", query_zh, flags=re.IGNORECASE):
                    part = part.strip()
                    if part:
                        author_names.append(part.lower())

            if author_names:
                before_count = len(unique)
                filtered = []
                # 非作者名的噪音词
                noise_words = {
                    "et",
                    "al",
                    "al.",
                    "and",
                    "others",
                    "等",
                    "et al",
                    "et al.",
                }

                for p in unique:
                    if not p.authors:
                        continue
                    # 过滤掉 "et al." 等噪音
                    authors_clean = [
                        a.lower().strip()
                        for a in p.authors
                        if a.strip().lower() not in noise_words and len(a.strip()) > 1
                    ]
                    if not authors_clean:
                        continue

                    # 检查是否有作者名匹配（逐个作者对比）
                    matched = False
                    for target in author_names:
                        for author in authors_clean:
                            # 跳过空作者
                            if not author:
                                continue
                            # 完整匹配："jinhua zhou" in "jinhua zhou"
                            if target in author or author in target:
                                matched = True
                                break
                            # 姓+首字母匹配："zhou j" matches "zhou jh"
                            parts = target.split()
                            if len(parts) >= 2:
                                family = parts[-1]
                                given_init = "".join(p[0] for p in parts[:-1] if p)
                                short = f"{family} {given_init}".lower()
                                # 只检查 short in author（避免 "j" 匹配所有含 j 的作者）
                                if short and short in author:
                                    matched = True
                                    break
                        if matched:
                            break
                    if matched:
                        filtered.append(p)
                # 过滤后保留结果（不再因太少而跳过）
                if filtered:
                    unique = filtered
                    filtered_count = before_count - len(unique)
                    if filtered_count > 0:
                        print(
                            f"[INFO] 作者过滤：保留 {len(unique)}/{before_count} 篇作者匹配的论文"
                        )

        # 相关性评分（BM25 + 源质量加权）
        keywords = set()
        if self.openalex and self.openalex._last_keywords:
            keywords = self.openalex._last_keywords
        elif query:
            for w in re.split(r"\s+", query_en):
                w = w.strip("()\"' ")
                if len(w) > 2 and w.lower() not in (
                    "and",
                    "or",
                    "not",
                    "the",
                    "for",
                    "with",
                ):
                    keywords.add(w.lower())
        if keywords:
            self._bm25_scorer.build_from_papers(unique, keywords)
            for p in unique:
                p._relevance_score = self._score_relevance(p, keywords)
            if not journals and field != "au" and not is_chinese_query:
                unique = [
                    p for p in unique if self._title_matches_keywords(p, keywords)
                ]
            if sort == "relevance":
                # RRF 源质量加权：被多个高质量源收录的论文提权
                SOURCE_WEIGHTS = {
                    "pubmed": 1.0,
                    "semantic_scholar": 0.9,
                    "openalex": 0.85,
                    "scopus": 0.85,
                    "sciencedirect": 0.85,
                    "europepmc": 0.8,
                    "crossref": 0.7,
                    "core": 0.7,
                    "lens": 0.7,
                    "arxiv": 0.5,
                    "biorxiv": 0.5,
                    "dblp": 0.5,
                    "google_scholar": 0.6,
                    "bing_academic": 0.5,
                    "cnki": 0.7,
                    "wanfang": 0.7,
                    "vip": 0.65,
                    "jstor": 0.75,
                    "springer": 0.7,
                    "wiley": 0.7,
                    "ieee": 0.7,
                    "acs": 0.75,
                    "optica": 0.75,
                    "iop": 0.75,
                    "aip": 0.75,
                    "rsc": 0.75,
                    "muse": 0.7,
                    "agris": 0.6,
                    "zotero_mcp": 0.8,
                    "zotero_local": 0.8,
                }
                for p in unique:
                    src_list = (
                        p.sources if p.sources else ([p.source] if p.source else [])
                    )
                    # 源质量分：收录源的加权平均
                    weights = [SOURCE_WEIGHTS.get(s, 0.5) for s in src_list]
                    src_quality = (
                        sum(weights) / max(len(weights), 1) if weights else 0.5
                    )
                    # 多源收录加分
                    diversity_bonus = min(len(src_list) - 1, 3) * 0.05
                    bm25 = getattr(p, "_relevance_score", 0)
                    p._final_score = (
                        bm25 * 0.7 + (src_quality + diversity_bonus) * 30 * 0.3
                    )
                unique.sort(key=lambda x: getattr(x, "_final_score", 0), reverse=True)

        # 排序
        if sort == "date":
            unique.sort(key=lambda p: (bool(p.year), p.year or 0), reverse=True)
        elif sort == "citations":
            unique.sort(key=lambda p: p.citation_count, reverse=True)
        elif sort == "recent_impact":
            # 近期影响力：引用数 / 论文年龄（年份越新、引用越多，影响力越高）
            # 无年份论文排到最后
            _current_year = datetime.now().year

            def _impact_key(p):
                _age = max(1, _current_year - p.year) if p.year and p.year > 0 else 9999
                return (p.citation_count or 0) / _age

            unique.sort(key=_impact_key, reverse=True)

        return unique, errors

    def _run_search_tasks(self, tasks):
        """并发执行搜索任务，返回 (all_papers, errors, source_status, timing_info)

        分赛道执行：快源(API类) 8 workers/12s 超时，慢源(Playwright类) 3 workers/40s 超时。
        避免 Playwright 源占满线程槽位拖累 API 源响应。
        """
        all_papers = []
        errors = []
        source_status = {}
        timing_info = {}
        # 快/慢源分类（基于已知特征）
        SLOW_SOURCES = {"Google Scholar", "CNKI", "万方", "维普", "Bing Academic"}
        fast_tasks, slow_tasks = [], []
        for name, fn in tasks:
            if self._health_monitor.is_enabled(name):
                if name in SLOW_SOURCES:
                    slow_tasks.append((name, fn))
                else:
                    fast_tasks.append((name, fn))
                source_status[name] = self._health_monitor.get_status(name)
            else:
                source_status[name] = "disabled"
                timing_info[name] = {"duration": 0, "status": "disabled"}
                print(f"[HEALTH] Skipping disabled source: {name}")

        def _execute_pool(task_list, max_workers, timeout_val, stagger_ms=50):
            if not task_list:
                return
            import random

            with ThreadPoolExecutor(
                max_workers=min(len(task_list), max_workers)
            ) as executor:
                future_to_name = {}
                future_start_time = {}
                for i, (name, fn) in enumerate(task_list):
                    # 错峰启动 + 自动重试（失败后等 2s 重试一次）
                    def _staggered(
                        fn=fn,
                        delay=i * (stagger_ms / 1000.0)
                        + random.random() * (stagger_ms / 1000.0),
                    ):
                        time.sleep(delay)
                        try:
                            return fn()
                        except Exception:
                            time.sleep(2)
                            try:
                                return fn()
                            except Exception:
                                raise

                    future = executor.submit(_staggered)
                    future_to_name[future] = name
                    future_start_time[future] = time.time()
                for future in as_completed(future_to_name):
                    name = future_to_name[future]
                    start_time = future_start_time[future]
                    response_time = time.time() - start_time
                    try:
                        result = future.result(timeout=timeout_val)
                        self._health_monitor.record(name, True, response_time)
                        source_status[name] = self._health_monitor.get_status(name)
                        timing_info[name] = {
                            "duration": round(response_time, 2),
                            "status": "ok",
                        }
                        if name == "PubMed" and isinstance(result, tuple):
                            papers, exact_doi = result
                            if exact_doi:
                                papers = [
                                    p
                                    for p in papers
                                    if p.doi and p.doi.lower() == exact_doi
                                ]
                            all_papers.extend(papers)
                        else:
                            all_papers.extend(result)
                    except FuturesTimeoutError:
                        self._health_monitor.record(name, False, timeout_val)
                        source_status[name] = self._health_monitor.get_status(name)
                        timing_info[name] = {
                            "duration": round(timeout_val, 2),
                            "status": "timeout",
                        }
                        errors.append(f"{name}: 搜索超时（{timeout_val}秒）")
                        print(f"[WARN] {name} search timed out after {timeout_val}s")
                    except Exception as e:
                        self._health_monitor.record(name, False, response_time)
                        source_status[name] = self._health_monitor.get_status(name)
                        timing_info[name] = {
                            "duration": round(response_time, 2),
                            "status": "error",
                        }
                        errors.append(f"{name}: {e}")

        # 快源和慢源并行执行（快源 8 workers/12s，慢源 3 workers/40s）
        import concurrent.futures as _cf

        with _cf.ThreadPoolExecutor(max_workers=2) as meta:
            meta.submit(_execute_pool, fast_tasks, 8, 12)
            meta.submit(_execute_pool, slow_tasks, 3, 40)
            # 等待两个 pool 都完成（ThreadPoolExecutor context manager 自动等待）

        return all_papers, errors, source_status, timing_info

    def search_stream(
        self,
        query: str,
        year_from=None,
        year_to=0,
        sort="relevance",
        max_results=50,
        enabled_sources=None,
        use_pubmed=True,
        use_openalex=True,
        use_google_scholar=False,
        use_cnki=True,
        use_wanfang=True,
        use_vip=True,
        use_bing_academic=False,
        use_semantic_scholar=True,
        use_crossref=True,
        use_arxiv=True,
        use_sciencedirect=True,
        use_scopus=True,
        use_jstor=True,
        use_dblp=True,
        use_biorxiv=True,
        use_agris=True,
        use_acs=True,
        use_optica=True,
        use_iop=True,
        use_aip=True,
        use_rsc=True,
        use_europepmc=True,
        use_springer=True,
        use_wiley=True,
        use_ieee=True,
        use_muse=True,
        use_core=True,
        use_lens=True,
        use_lens_patents=False,
        journal="",
        field="",
        mesh_term="",
        pub_type="",
        smart_routing=False,
        force_refresh=False,
        oa_only=False,
        affiliation="",
        query_zh="",
    ):
        """流式聚合检索（逐源推送结果）

        Args:
            enabled_sources: 数据源名称集合（如 {"pubmed", "openalex"}），
                传入时覆盖所有 use_xxx 参数。None 表示使用 use_xxx 参数。
            smart_routing: 启用智能学科路由，基于查询关键词自动筛选相关数据源。

        Yields:
            dict: 事件对象，type 字段区分事件类型
                - "source_done": 数据源完成 {"source": str, "count": int, "completed": int, "total": int}
                - "source_error": 数据源失败 {"source": str, "error": str, "completed": int, "total": int}
                - "source_disabled": 数据源被健康监控禁用 {"source": str, "completed": int, "total": int}
                - "result": 最终结果 {"papers": list, "errors": list, "total": int, ...}
        """
        # 解析 journal 参数
        if isinstance(journal, list):
            journals = [j.strip() for j in journal if j.strip()]
        elif journal:
            journals = [j.strip() for j in journal.split(",") if j.strip()]
        else:
            journals = []

        current_year = datetime.now().year
        if year_from is None:
            year_from = current_year - 10
        if not year_to:
            year_to = current_year

        # --- 查询预理解（规则引擎） ---
        parsed_query = self.preprocess_query(query, year_from, year_to, pub_type)
        query = parsed_query["query"]
        if (
            year_from == current_year - 10
            and parsed_query["year_from"] != current_year - 10
        ):
            year_from = parsed_query["year_from"]
        if year_to == current_year and parsed_query["year_to"] != current_year:
            year_to = parsed_query["year_to"]
        if not pub_type and parsed_query["pub_type"]:
            pub_type = parsed_query["pub_type"]

        # --- 智能学科路由 ---
        if smart_routing and enabled_sources is not None:
            enabled_sources = DisciplineRouter.filter_sources(query, enabled_sources)

        # 中文查询处理
        is_chinese_query = _contains_chinese(query)
        # 如果外部传入了 query_zh，使用它；否则从 query 中提取
        if not query_zh:
            query_zh = query

        # 清理查询：去掉自然语言部分
        query = _clean_search_query(query)
        query_zh = _clean_search_query(query_zh)

        if is_chinese_query and self.translation_enabled:
            query_en = self._translator.translate(query)
        else:
            query_en = query

        # 同义词扩展（对翻译后的英文查询，也对直接输入的英文查询生效）
        if self.synonym_expansion_enabled:
            query_en = _expand_synonyms(query_en)

        if is_chinese_query and _contains_chinese(query_en):
            print(f"[INFO] 中文查询部分翻译: '{query}' -> '{query_en}'")

        # 构建任务列表
        tasks = self._build_search_tasks(
            query_en,
            query_zh,
            year_from,
            year_to,
            sort,
            max_results,
            journal,
            field,
            mesh_term,
            pub_type,
            enabled_sources=enabled_sources,
            use_pubmed=use_pubmed,
            use_openalex=use_openalex,
            use_google_scholar=use_google_scholar,
            use_cnki=use_cnki,
            use_wanfang=use_wanfang,
            use_vip=use_vip,
            use_bing_academic=use_bing_academic,
            use_semantic_scholar=use_semantic_scholar,
            use_crossref=use_crossref,
            use_arxiv=use_arxiv,
            use_sciencedirect=use_sciencedirect,
            use_scopus=use_scopus,
            use_jstor=use_jstor,
            use_dblp=use_dblp,
            use_biorxiv=use_biorxiv,
            use_agris=use_agris,
            use_acs=use_acs,
            use_optica=use_optica,
            use_iop=use_iop,
            use_aip=use_aip,
            use_rsc=use_rsc,
            use_europepmc=use_europepmc,
            use_springer=use_springer,
            use_wiley=use_wiley,
            use_ieee=use_ieee,
            use_muse=use_muse,
            use_core=use_core,
            use_lens=use_lens,
            use_lens_patents=use_lens_patents,
        )

        # 过滤被健康监控禁用的源，统计总数
        enabled_tasks = []
        total_sources = 0
        for name, fn in tasks:
            if self._health_monitor.is_enabled(name):
                enabled_tasks.append((name, fn))
                total_sources += 1
            else:
                # 跳过的源先通知前端
                pass

        all_papers = []
        errors = []
        completed = 0
        SOURCE_TIMEOUT = 45

        if enabled_tasks:
            with ThreadPoolExecutor(max_workers=min(len(enabled_tasks), 6)) as executor:
                future_to_name = {}
                future_start_time = {}
                for name, fn in enabled_tasks:
                    future = executor.submit(fn)
                    future_to_name[future] = name
                    future_start_time[future] = time.time()

                for future in as_completed(future_to_name):
                    name = future_to_name[future]
                    start_time = future_start_time[future]
                    response_time = time.time() - start_time
                    completed += 1
                    try:
                        result = future.result(timeout=SOURCE_TIMEOUT)
                        self._health_monitor.record(name, True, response_time)
                        if name == "PubMed" and isinstance(result, tuple):
                            papers, exact_doi = result
                            if exact_doi:
                                papers = [
                                    p
                                    for p in papers
                                    if p.doi and p.doi.lower() == exact_doi
                                ]
                            all_papers.extend(papers)
                        else:
                            all_papers.extend(result)
                        paper_count = (
                            len(result)
                            if not isinstance(result, tuple)
                            else len(result[0])
                        )
                        yield {
                            "type": "source_done",
                            "source": name,
                            "count": paper_count,
                            "completed": completed,
                            "total": total_sources,
                            "duration": round(response_time, 2),
                        }
                    except FuturesTimeoutError:
                        self._health_monitor.record(name, False, SOURCE_TIMEOUT)
                        errors.append(f"{name}: 搜索超时（{SOURCE_TIMEOUT}秒）")
                        print(f"[WARN] {name} search timed out after {SOURCE_TIMEOUT}s")
                        yield {
                            "type": "source_error",
                            "source": name,
                            "error": f"搜索超时（{SOURCE_TIMEOUT}秒）",
                            "completed": completed,
                            "total": total_sources,
                            "duration": round(SOURCE_TIMEOUT, 2),
                        }
                    except Exception as e:
                        self._health_monitor.record(name, False, response_time)
                        errors.append(f"{name}: {e}")
                        yield {
                            "type": "source_error",
                            "source": name,
                            "error": str(e),
                            "completed": completed,
                            "total": total_sources,
                            "duration": round(response_time, 2),
                        }

        # 后处理
        unique, errors = self._post_process_results(
            all_papers,
            errors,
            query,
            query_en,
            is_chinese_query,
            year_from,
            year_to,
            sort,
            journals,
            field,
            pub_type,
            mesh_term,
            oa_only=oa_only,
            affiliation=affiliation,
            query_zh=query_zh,
        )

        # 写入缓存
        sources_hash = self._compute_sources_hash(
            enabled_sources
            if enabled_sources is not None
            else (
                use_pubmed,
                use_openalex,
                use_google_scholar,
                use_cnki,
                use_wanfang,
                use_vip,
                use_bing_academic,
                use_semantic_scholar,
                use_crossref,
                use_arxiv,
                use_sciencedirect,
                use_scopus,
                use_jstor,
                use_dblp,
                use_biorxiv,
                use_agris,
                use_acs,
                use_optica,
                use_iop,
                use_aip,
                use_rsc,
                use_europepmc,
                use_springer,
                use_wiley,
                use_ieee,
                use_muse,
                use_core,
                use_lens,
            )
        )
        filter_seed = hashlib.md5(f"{journal}|{field}|{pub_type}".encode()).hexdigest()[
            :8
        ]
        sources_hash = f"{sources_hash}_{filter_seed}"
        self._search_cache.put(query, year_from, year_to, sources_hash, unique)
        stats = self._search_cache.stats()
        print(
            f"[CACHE PUT stream] query='{query[:50]}' | 结果 {len(unique)} 条 | "
            f"命中率 {stats['hit_rate']} 缓存 {stats['size']}/{stats['maxsize']}"
        )

        yield {
            "type": "result",
            "papers": unique,
            "errors": errors,
            "total": len(unique),
            "query": query,
            "query_en": query_en,
            "query_zh": query_zh,
        }

    def get_source_health(self) -> dict:
        """获取所有数据源的健康状态"""
        return self._health_monitor.get_all_status()

    def toggle_source(self, source_name: str, enabled: bool):
        """手动启用/禁用数据源

        Args:
            source_name: 数据源名称
            enabled: True 启用，False 禁用
        """
        if enabled:
            self._health_monitor.enable(source_name)
        else:
            self._health_monitor.disable(source_name)

    def reset_source_health(self, source_name: str = None):
        """重置数据源健康状态

        Args:
            source_name: 指定源名，None 则重置全部
        """
        self._health_monitor.reset(source_name)

    def _search_pubmed(
        self,
        query,
        year_from,
        year_to,
        sort,
        max_results,
        journal,
        field,
        mesh_term,
        pub_type,
    ):
        """PubMed 搜索（返回 papers 列表）"""
        pmids, exact_doi = self.pubmed.search(
            query,
            year_from,
            year_to,
            sort,
            max_results,
            journal=journal,
            field=field,
            mesh_term=mesh_term,
            pub_type=pub_type,
        )
        papers = []
        if pmids:
            papers = self.pubmed.fetch_details(pmids)
        return papers, exact_doi

    def search_by_doi(self, doi: str):
        """通过 DOI 精确查询"""
        if self.pubmed:
            pmids, _ = self.pubmed.search(doi, max_results=1)
            if pmids:
                papers = self.pubmed.fetch_details(pmids)
                if papers:
                    return papers[0]
        if self.openalex:
            papers = self.openalex.search(doi, max_results=1)
            if papers:
                return papers[0]
        return None

    def close(self):
        """关闭所有搜索源的 Session"""
        # 通过注册表关闭所有数据源的 session
        if hasattr(self, "_sources"):
            for source in self._sources.values():
                if source and hasattr(source, "session"):
                    try:
                        source.session.close()
                    except Exception:
                        pass
        # 兼容旧版属性式的数据源
        for source in [
            self.pubmed,
            self.openalex,
            self.google_scholar,
            self.cnki,
            self.wanfang,
            self.vip,
            self.bing_academic,
            self.semantic_scholar,
            self.crossref,
            self.arxiv,
            self.sciencedirect,
            self.scopus,
            self.jstor,
            self.unpaywall,
        ]:
            if source and hasattr(source, "session"):
                try:
                    source.session.close()
                except Exception:
                    pass
        # 关闭 Playwright 浏览器
        try:
            PlaywrightBrowser.get_instance().close()
        except Exception:
            pass
