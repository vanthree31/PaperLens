"""Application state management for PaperLens"""

import threading
from core.config import load_config
from search_engine import SearchEngine
from ai_assistant import SearchAI, AnalysisAI, create_lightweight_assistant


class AppState:
    """Shared application state across all Blueprints"""

    def __init__(self):
        self.config = load_config()
        self.engine = SearchEngine(self.config)
        self.search_ai = SearchAI(self.config)
        self.analysis_ai = AnalysisAI(self.config)
        self.lightweight_ai = create_lightweight_assistant(self.config)

        # [新增] 设置AI提供商到搜索引擎的翻译器
        self._setup_translator_ai()

        self.cached_papers = {"papers": [], "query": ""}
        self.last_ai_search_result = {"resp": None}
        self.ai_cache = {}
        self.citation_cache = {}

        # Locks
        self.cache_lock = threading.Lock()
        self.citation_lock = threading.Lock()
        self.collections_lock = threading.Lock()
        self.history_lock = threading.Lock()
        self.preferences_lock = threading.Lock()
        self.tags_lock = threading.Lock()
        self.disk_cache_lock = threading.Lock()

    def _setup_translator_ai(self):
        """设置AI提供商到搜索引擎的翻译器"""
        try:
            # 检查翻译配置
            translation_cfg = self.config.get("translation", {})
            if not translation_cfg.get("ai_enabled", False):
                return

            # 检查AI搜索配置
            ai_cfg = self.config.get("ai_search", {})
            if not ai_cfg.get("enabled", False):
                return

            # 获取AI提供商实例
            # SearchAI 内部已经有 AIAssistant 实例
            if hasattr(self.search_ai, "assistant") and self.search_ai.assistant:
                self.engine.set_ai_provider(self.search_ai.assistant)
                print("[INFO] 翻译器已连接到AI提供商")
        except Exception as e:
            print(f"[WARN] 设置翻译器AI提供商失败: {e}")

    def replace_instances(self, cfg):
        """Thread-safe instance replacement (replaces nonlocal pattern)"""
        old_instances = []
        with self.cache_lock:
            new_engine = SearchEngine(cfg)
            new_search_ai = SearchAI(cfg)
            new_analysis_ai = AnalysisAI(cfg)
            new_lightweight_ai = create_lightweight_assistant(cfg)

            if self.engine:
                old_instances.append(("engine", self.engine))
            if self.search_ai:
                old_instances.append(("search_ai", self.search_ai))
            if self.analysis_ai:
                old_instances.append(("analysis_ai", self.analysis_ai))
            if self.lightweight_ai:
                old_instances.append(("lightweight_ai", self.lightweight_ai))

            self.engine = new_engine
            self.search_ai = new_search_ai
            self.analysis_ai = new_analysis_ai
            self.lightweight_ai = new_lightweight_ai
            self.config = cfg

        # Close old instances outside lock to avoid blocking
        for name, instance in old_instances:
            try:
                instance.close()
            except Exception:
                pass

        # [新增] 重新设置AI提供商到翻译器
        self._setup_translator_ai()

    def replace_engine_only(self, cfg):
        """Replace only engine (for CARSI/Wanfang)"""
        old_engine = None
        with self.cache_lock:
            new_engine = SearchEngine(cfg)
            if self.engine:
                old_engine = self.engine
            self.engine = new_engine
            self.config = cfg
        self._setup_translator_ai()

        if old_engine:
            try:
                old_engine.close()
            except Exception:
                pass
