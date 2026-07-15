"""AI analysis routes for PaperLens"""

import copy
from flask import Blueprint, request, jsonify, Response, current_app
from core.config import load_config
from core.utils import _build_paper_prompt, _check_url_safety
from core.cache import _load_ai_analysis_cache, _save_ai_analysis_cache, _is_paper_in_collections

ai_bp = Blueprint('ai', __name__)


def _state():
    return current_app.config["APP_STATE"]


@ai_bp.route("/api/ai/analyze-papers", methods=["POST"])
def ai_analyze_papers():
    state = _state()
    if not state.analysis_ai.is_available():
        return jsonify({"error": "ai_analysis_not_enabled"}), 400

    data = request.json or {}
    indices = data.get("indices", [])
    if not isinstance(indices, list):
        return jsonify({"error": "invalid_indices"}), 400
    indices = sorted(set(indices))
    mode = data.get("mode", "summary")
    if mode not in ("summary", "detail", "compare", "novelty"):
        mode = "summary"
    force_refresh = data.get("force_refresh", False)
    use_stream = data.get("stream", False)
    lang = data.get("lang", "zh")

    with state.cache_lock:
        papers = list(state.cached_papers["papers"])
    if not papers:
        return jsonify({"error": "no_papers"}), 400
    if not indices:
        return jsonify({"error": "no_selection"}), 400

    selected = [papers[i] for i in indices if 0 <= i < len(papers)]
    if not selected:
        return jsonify({"error": "invalid_selection"}), 400

    paper_ids = "_".join(sorted(set(
        p.doi or p.pmid or f"t{hash(p.title or '')}"
        for i, p in zip(indices, selected)
    )))
    cache_key = f"{mode}_{lang}_{paper_ids}"

    # 检查内存缓存
    with state.cache_lock:
        if not force_refresh and cache_key in state.ai_cache and state.ai_cache[cache_key]:
            return jsonify({"response": state.ai_cache[cache_key], "count": len(selected), "mode": mode, "cached": True})

    # 检查磁盘缓存（收藏夹论文的分析结果）
    if not force_refresh:
        disk_cache = _load_ai_analysis_cache()
        if cache_key in disk_cache:
            result = disk_cache[cache_key]
            # 同时加载到内存缓存
            with state.cache_lock:
                state.ai_cache[cache_key] = result
            return jsonify({"response": result, "count": len(selected), "mode": mode, "cached": True})

    prompt = _build_paper_prompt(selected, mode, lang)
    if lang == "en":
        context = "You are a senior academic paper analysis expert. Provide precise, insightful, and concise paper analysis for fellow researchers. Automatically identify the research field and use domain-appropriate professional language."
    else:
        context = "你是一位资深学术论文分析专家，擅长用中文为同行学者提供精准、深刻、不啰嗦的论文分析。根据论文内容自动判断所属领域，用该领域的专业语言进行分析。"

    if use_stream:
        # [Fix #19] 在 generate 开始时复制 papers，避免流式传输期间被并发修改
        selected_copy = copy.deepcopy(selected)

        def generate():
            full_response = []
            try:
                for chunk in state.analysis_ai.chat_stream(prompt, context, mode=mode):
                    full_response.append(chunk)
                    yield chunk
            finally:
                # finally 确保客户端断开连接（GeneratorExit）也能写入缓存
                result = "".join(full_response)
                if result and not result.startswith("AI_ERROR:"):
                    with state.cache_lock:
                        state.ai_cache[cache_key] = result
                        if len(state.ai_cache) > 50:
                            for k in list(state.ai_cache.keys())[:len(state.ai_cache) - 50]:
                                del state.ai_cache[k]
                    # 如果论文在收藏夹中，持久化到磁盘
                    if any(_is_paper_in_collections(p.doi, state.collections_lock) for p in selected_copy if p.doi):
                        with state.disk_cache_lock:
                            disk_cache = _load_ai_analysis_cache()
                            disk_cache[cache_key] = result
                            if len(disk_cache) > 100:
                                keys = list(disk_cache.keys())
                                for k in keys[:len(disk_cache) - 100]:
                                    del disk_cache[k]
                            _save_ai_analysis_cache(disk_cache)

        return Response(generate(), mimetype="text/plain; charset=utf-8",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    result = state.analysis_ai.chat(prompt, context, mode=mode)
    if result and not result.startswith("AI_ERROR:"):
        with state.cache_lock:
            state.ai_cache[cache_key] = result
            if len(state.ai_cache) > 50:
                for k in list(state.ai_cache.keys())[:len(state.ai_cache) - 50]:
                    del state.ai_cache[k]
        # 如果论文在收藏夹中，持久化到磁盘
        if any(_is_paper_in_collections(p.doi, state.collections_lock) for p in selected if p.doi):
            with state.disk_cache_lock:  # [Fix #8] 保护磁盘缓存读写
                disk_cache = _load_ai_analysis_cache()
                disk_cache[cache_key] = result
                if len(disk_cache) > 100:
                    keys = list(disk_cache.keys())
                    for k in keys[:len(disk_cache) - 100]:
                        del disk_cache[k]
                _save_ai_analysis_cache(disk_cache)
    return jsonify({"response": result, "count": len(selected), "mode": mode, "cached": False})


@ai_bp.route("/api/ai/chat", methods=["POST"])
def ai_chat():
    state = _state()
    if not state.analysis_ai.is_available():
        return jsonify({"error": "ai_analysis_not_enabled"}), 400
    data = request.json or {}
    try:
        return jsonify({"response": state.analysis_ai.chat(data.get("message", ""), data.get("context", ""))})
    except Exception as e:
        print(f"[ERROR] AI chat failed: {e}")
        return jsonify({"error": "request_failed"}), 500


@ai_bp.route("/api/ai/summarize", methods=["POST"])
def ai_summarize():
    state = _state()
    if not state.analysis_ai.is_available():
        return jsonify({"error": "ai_analysis_not_enabled"}), 400
    data = request.json or {}
    lang = data.get("lang", "zh")
    with state.cache_lock:
        papers = list(state.cached_papers["papers"])
    if not papers:
        return jsonify({"error": "no_papers"}), 400
    try:
        return jsonify({"response": state.analysis_ai.summarize(papers, lang=lang)})
    except Exception as e:
        print(f"[ERROR] AI summarize failed: {e}")
        return jsonify({"error": "request_failed"}), 500


@ai_bp.route("/api/ai/test", methods=["POST"])
def ai_test_connection():
    """测试 AI 连接"""
    data = request.json or {}
    provider = data.get("provider", "")
    api_key = data.get("api_key", "")
    base_url = data.get("base_url", "")
    model = data.get("model", "")

    if not provider:
        return jsonify({"ok": False, "error": "missing_provider"})

    # 脱敏值回退到存储的真实配置
    if "****" in api_key or not api_key:
        cfg = load_config()
        section_name = data.get("section", "").lower()
        # 优先从 ai_providers 中获取对应提供商的配置
        provider_key = f"{section_name}_{provider}" if section_name else ""
        stored_from_providers = cfg.get("ai_providers", {}).get(provider_key, {})
        api_key = stored_from_providers.get("api_key", "")
        # 如果 ai_providers 中没有，从 ai_search/ai_analysis 获取
        if not api_key or "****" in api_key:
            section_cfg = cfg.get(f"ai_{section_name}", {})
            api_key = section_cfg.get("api_key", "")

    # SSRF 防护：检查 base_url（Ollama 允许 loopback）
    if base_url:
        safe, err = _check_url_safety(base_url, allow_loopback=(provider == "ollama"))
        if not safe:
            return jsonify({"ok": False, "error": err})

    try:
        import requests as req
        # 根据提供商构造请求
        if provider == "ollama":
            # 使用 OpenAI 兼容端点，与 AIAssistant 保持一致
            url = (base_url or "http://localhost:11434").rstrip("/") + "/v1/chat/completions"
            headers = {"Content-Type": "application/json"}
            payload = {"model": model or "qwen3.5:9b", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 5}
            resp = req.post(url, json=payload, headers=headers, timeout=30)
        elif provider == "deepseek":
            url = (base_url or "https://api.deepseek.com") + "/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"model": model or "deepseek-chat", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 5}
            resp = req.post(url, json=payload, headers=headers, timeout=30)
        elif provider == "openai":
            url = (base_url or "https://api.openai.com") + "/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"model": model or "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 5}
            resp = req.post(url, json=payload, headers=headers, timeout=30)
        elif provider == "anthropic":
            url = (base_url or "https://api.anthropic.com") + "/v1/messages"
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
            payload = {"model": model or "claude-sonnet-4-20250514", "max_tokens": 5, "messages": [{"role": "user", "content": "Hi"}]}
            resp = req.post(url, json=payload, headers=headers, timeout=30)
        else:
            # 自定义提供商
            if not base_url:
                return jsonify({"ok": False, "error": "missing_base_url"})
            url = base_url.rstrip("/") + "/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"model": model, "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 5}
            resp = req.post(url, json=payload, headers=headers, timeout=30)

        if resp.ok:
            return jsonify({"ok": True, "message": f"HTTP {resp.status_code}"})
        else:
            err = resp.text[:200]
            return jsonify({"ok": False, "error": f"HTTP {resp.status_code}: {err}"})
    except req.exceptions.ConnectionError:
        return jsonify({"ok": False, "error": "connection_failed"})
    except req.exceptions.Timeout:
        return jsonify({"ok": False, "error": "connection_timeout"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@ai_bp.route("/api/ollama/models", methods=["GET"])
def ollama_models():
    """检测本地 Ollama 已安装的模型"""
    import requests as req
    # 默认 Ollama 端口
    base_url = request.args.get("url", "http://localhost:11434").rstrip("/")
    # SSRF 防护：Ollama 是本地服务，允许 loopback
    safe, err = _check_url_safety(base_url, allow_loopback=True)
    if not safe:
        return jsonify({"ok": False, "models": [], "error": err})
    try:
        resp = req.get(f"{base_url}/api/tags", timeout=5)
        if not resp.ok:
            return jsonify({"ok": False, "models": [], "error": f"Ollama returned {resp.status_code}"})
        data = resp.json()
        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            size_bytes = m.get("size", 0)
            size_gb = round(size_bytes / (1024**3), 1) if size_bytes else 0
            models.append({
                "name": name,
                "size": f"{size_gb}GB" if size_gb else "",
                "modified": m.get("modified_at", ""),
            })
        return jsonify({"ok": True, "models": models, "base_url": base_url})
    except req.exceptions.ConnectionError:
        return jsonify({"ok": False, "models": [], "error": "ollama_not_running"})
    except Exception as e:
        return jsonify({"ok": False, "models": [], "error": str(e)})


@ai_bp.route("/api/test-key", methods=["POST"])
def test_api_key():
    """测试数据源 API Key（使用后端存储的真实值）"""
    import requests as req
    data = request.json or {}
    source = data.get("source", "")
    api_key = data.get("api_key", "").strip()
    email = data.get("email", "").strip()

    # 如果前端传的是脱敏值，从配置文件中读取真实值
    if not api_key or "****" in api_key:
        cfg = load_config()
        src_cfg = cfg.get("sources", {}).get(source, {})
        api_key = src_cfg.get("api_key", "")
        email = email or src_cfg.get("email", "")
        # 存储的 key 也是脱敏值，说明从未保存过真实 key
        if "****" in api_key:
            return jsonify({"ok": False, "error": "key_not_saved"}), 400

    if source == "pubmed":
        if not api_key:
            return jsonify({"ok": False, "error": "no_key"})
        try:
            url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=test&retmax=1&api_key={api_key}"
            if email:
                url += f"&email={email}"
            r = req.get(url, timeout=10)
            if r.ok and "<Count>" in r.text:
                return jsonify({"ok": True})
            return jsonify({"ok": False, "error": f"HTTP {r.status_code}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    elif source == "openalex":
        if not api_key:
            return jsonify({"ok": False, "error": "no_key"})
        try:
            params = {"per_page": 1, "api_key": api_key}
            if email:
                params["mailto"] = email
            r = req.get("https://api.openalex.org/works", params=params, timeout=10)
            if r.ok:
                return jsonify({"ok": True})
            return jsonify({"ok": False, "error": f"HTTP {r.status_code}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    elif source == "semantic_scholar":
        if not api_key:
            return jsonify({"ok": False, "error": "no_key"})
        try:
            r = req.get("https://api.semanticscholar.org/graph/v1/paper/search?query=test&limit=1",
                       headers={"x-api-key": api_key}, timeout=10)
            if r.ok:
                return jsonify({"ok": True})
            return jsonify({"ok": False, "error": f"HTTP {r.status_code}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    elif source == "core":
        # CORE API Key 测试 (core.ac.uk)
        if not api_key:
            return jsonify({"ok": False, "error": "no_key"})
        try:
            r = req.get("https://api.core.ac.uk/v3/search/works",
                       params={"q": "test", "limit": 1},
                       headers={"Authorization": f"Bearer {api_key}"},
                       timeout=10)
            if r.ok:
                return jsonify({"ok": True})
            return jsonify({"ok": False, "error": f"HTTP {r.status_code}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    elif source == "lens":
        # Lens API Token 测试 (lens.org)
        if not api_key:
            return jsonify({"ok": False, "error": "no_key"})
        try:
            payload = {
                "query": {"match_all": {}},
                "size": 1
            }
            r = req.post("https://api.lens.org/scholarly/search",
                        json=payload,
                        headers={"Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json"},
                        timeout=10)
            if r.ok:
                return jsonify({"ok": True})
            return jsonify({"ok": False, "error": f"HTTP {r.status_code}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    return jsonify({"ok": False, "error": "unsupported_source"})
