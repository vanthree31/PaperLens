"""Search routes for PaperLens"""

import time
import json
import copy
import threading
from datetime import datetime
from flask import Blueprint, request, jsonify, Response, current_app
from core.utils import _escape_paper
from dedup import deduplicate_papers

search_bp = Blueprint('search', __name__)


def _state():
    return current_app.config["APP_STATE"]


@search_bp.route("/api/ai-search/result", methods=["GET"])
def ai_search_result():
    """Fallback: 流式传输截断时，前端通过此端点获取完整搜索结果"""
    state = _state()
    with state.cache_lock:
        resp = state.last_ai_search_result.get("resp")
        if resp:
            print(f"[INFO] Fallback: returning cached AI search result ({resp.get('total', 0)} papers)")
            # [Fix #2] fallback 返回后清空缓存，避免重复使用旧结果
            state.last_ai_search_result["resp"] = None
            # [Fix #10] 返回副本而非引用，防止并发修改
            return jsonify(copy.deepcopy(resp))
    return jsonify({"error": "no_result"}), 404


@search_bp.route("/api/search", methods=["POST"])
def search():
    state = _state()
    data = request.json or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "no_query"}), 400
    current_year = datetime.now().year
    try:
        max_results = min(int(data.get("max_results", 50)), 200)
        year_from = max(1900, min(int(data.get("year_from", current_year - 10)), current_year))
        year_to = max(year_from, min(int(data.get("year_to", current_year)), current_year))
    except (ValueError, TypeError):
        max_results, year_from, year_to = 50, current_year - 10, current_year
    try:
        # 从前端 use_xxx 参数构建 enabled_sources 集合（插件架构）
        from search_engine import get_source_names
        _all_source_names = get_source_names()
        enabled_sources = {name for name in _all_source_names
                           if data.get(f"use_{name}", None)}
        papers, search_errors = state.engine.search(
            query=query, year_from=year_from, year_to=year_to,
            sort=data.get("sort", "relevance"), max_results=max_results,
            enabled_sources=enabled_sources,
            journal=data.get("journal", "").strip(), field=data.get("field", "").strip(),
            mesh_term=data.get("mesh_term", "").strip(), pub_type=data.get("pub_type", "").strip(),
            smart_routing=data.get("smart_routing", False),
        )
    except Exception as e:
        print(f"[ERROR] Search failed: {e}")
        return jsonify({"error": "search_failed"}), 500
    # Phase 5a: 跨源 DOI 去重
    try:
        papers = deduplicate_papers(papers)
    except Exception as e:
        print(f"[WARN] Dedup failed: {e}")
    with state.cache_lock:
        state.cached_papers["papers"] = papers
        state.cached_papers["query"] = query
    results = [_escape_paper(p) for p in papers]
    resp = {"total": len(results), "query": query, "papers": results}
    if search_errors:
        resp["errors"] = search_errors
    # 添加 timing 信息
    if hasattr(state.engine, '_last_timing_info') and state.engine._last_timing_info:
        resp["timing"] = state.engine._last_timing_info
    return jsonify(resp)


@search_bp.route("/api/search/stream", methods=["POST"])
def search_stream():
    """流式搜索端点：每个数据源完成时立即推送结果（SSE）"""
    state = _state()
    data = request.json or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "no_query"}), 400

    current_year = datetime.now().year
    try:
        max_results = min(int(data.get("max_results", 50)), 200)
        year_from = max(1900, min(int(data.get("year_from", current_year - 10)), current_year))
        year_to = max(year_from, min(int(data.get("year_to", current_year)), current_year))
    except (ValueError, TypeError):
        max_results, year_from, year_to = 50, current_year - 10, current_year

    def generate():
        import queue
        # 后台线程运行搜索生成器，主线程负责输出 + SSE 心跳（防代理超时）
        event_queue = queue.Queue()
        search_done = threading.Event()
        def _run_search():
            try:
                from search_engine import get_source_names
                _all_source_names = get_source_names()
                enabled_sources = {name for name in _all_source_names
                                   if data.get(f"use_{name}", None)}
                for event in state.engine.search_stream(
                    query=query, year_from=year_from, year_to=year_to,
                    sort=data.get("sort", "relevance"), max_results=max_results,
                    enabled_sources=enabled_sources,
                    journal=data.get("journal", "").strip(),
                    field=data.get("field", "").strip(),
                    mesh_term=data.get("mesh_term", "").strip(),
                    pub_type=data.get("pub_type", "").strip(),
                    smart_routing=data.get("smart_routing", False),
                ):
                    event_queue.put(("event", event))
                event_queue.put(("done", None))
            except Exception as e:
                print(f"[ERROR] search_stream failed: {e}")
                event_queue.put(("error", str(e)))
            finally:
                search_done.set()
        threading.Thread(target=_run_search, daemon=True).start()
        try:
            while not search_done.is_set() or not event_queue.empty():
                try:
                    kind, event = event_queue.get(timeout=15)
                    if kind == "event":
                        # 源完成/错误事件直接推送给前端（进度反馈）
                        if event.get("type") in ("source_done", "source_error"):
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                        elif event.get("type") == "result":
                            original_papers = list(event["papers"])
                            total = event["total"]
                            query_val = event.get("query", query)
                            errors_val = event.get("errors", [])
                            timing_val = event.get("timing", {})
                            with state.cache_lock:
                                state.cached_papers["papers"] = original_papers
                                state.cached_papers["query"] = query_val
                            batch_size = 20
                            escaped_papers = [_escape_paper(p) for p in original_papers]
                            total_batches = (len(escaped_papers) + batch_size - 1) // batch_size
                            for i in range(0, len(escaped_papers), batch_size):
                                batch = escaped_papers[i:i + batch_size]
                                batch_event = {
                                    "type": "result_batch",
                                    "batch": i // batch_size,
                                    "total_batches": max(total_batches, 1),
                                    "papers": batch,
                                    "total": total,
                                    "query": query_val,
                                }
                                batch_json = json.dumps(batch_event, ensure_ascii=False)
                                print(f"[INFO] Yielding result batch {i // batch_size + 1}/{max(total_batches, 1)}: {len(batch)} papers, {len(batch_json)} bytes")
                                yield f"data: {batch_json}\n\n"
                            done_event = {
                                "type": "result",
                                "total": total,
                                "query": query_val,
                                "errors": errors_val,
                                "timing": timing_val,
                                "papers": [],
                            }
                            yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"
                        else:
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    elif kind == "error":
                        yield f"data: {json.dumps({'type': 'error', 'error': event}, ensure_ascii=False)}\n\n"
                    elif kind == "done":
                        break
                except queue.Empty:
                    yield ": heartbeat\n\n"
        except Exception as e:
            print(f"[ERROR] search_stream failed: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@search_bp.route("/api/ai-search", methods=["POST"])
def ai_search():
    state = _state()
    if not state.search_ai.is_available():
        return jsonify({"error": "ai_search_not_enabled"}), 400
    data = request.json or {}
    user_input = data.get("query", "").strip()
    if not user_input:
        return jsonify({"error": "no_query"}), 400

    use_stream = data.get("stream", False)
    lang = data.get("lang", "zh")

    def do_search(analysis):
        """根据 AI 分析结果执行搜索"""
        current_year = datetime.now().year
        try:
            max_results = min(int(data.get("max_results", 50)), 200)
        except (ValueError, TypeError):
            max_results = 50
        # AI 搜索：优先使用前端传递的年份参数，其次使用 AI 返回的年份
        frontend_yf = data.get("year_from")
        frontend_yt = data.get("year_to")
        if frontend_yf is not None and frontend_yt is not None:
            # 前端明确指定了年份，使用前端值
            try:
                year_from = max(1900, min(int(frontend_yf), current_year))
                year_to = max(year_from, min(int(frontend_yt), current_year))
            except (ValueError, TypeError):
                year_from, year_to = current_year - 10, current_year
        else:
            # 前端未指定，使用 AI 返回的年份，0表示不限制
            ai_year_from = analysis.get("year_from", current_year - 10)
            ai_year_to = analysis.get("year_to", current_year)
            try:
                ai_year_from = int(ai_year_from)
                ai_year_to = int(ai_year_to)
                # 0表示不限制，保持0
                if ai_year_from == 0:
                    year_from = 0
                else:
                    year_from = max(1900, min(ai_year_from, current_year))
                if ai_year_to == 0:
                    year_to = 0
                else:
                    year_to = max(year_from if year_from else 1900, min(ai_year_to, current_year))
            except (ValueError, TypeError):
                year_from, year_to = current_year - 10, current_year

        # AI 搜索：AI 未指定数据源时默认搜索全部（不受前端复选框限制）
        ai_sources = analysis.get("data_sources", [])
        if ai_sources:
            enabled_sources = set(ai_sources)
        else:
            # AI 没指定 → 搜索全部源，不受前端勾选影响
            enabled_sources = None

        # [Fix] 支持双语言查询：query_en 用于英文数据库，query_zh 用于中文数据库
        # 优先使用 AI 返回的 query_en/query_zh，兼容旧格式的 query 字段
        query_en = analysis.get("query_en", "")
        query_zh = analysis.get("query_zh", "")
        # 兼容旧格式：如果只有 query 字段，根据内容判断语言
        if not query_en and not query_zh:
            old_query = analysis.get("query", user_input)
            from search_engine import _contains_chinese, _translate_zh_to_en
            if _contains_chinese(old_query):
                query_en = _translate_zh_to_en(old_query)
                query_zh = old_query
            else:
                query_en = old_query
                query_zh = old_query

        # 使用 query_en 作为主查询（SearchEngine 内部会根据数据库类型选择语言）
        papers, search_errors = state.engine.search(
            query=query_en,
            year_from=year_from, year_to=year_to,
            sort="relevance", max_results=max_results,
            enabled_sources=enabled_sources,
            # [Fix] 优先使用AI返回的期刊/字段，回退到前端传递的值
            journal=analysis.get("journal", "") or data.get("journal", ""),
            field=analysis.get("field", "") or data.get("field", ""),
            pub_type=analysis.get("pub_type", "") or data.get("pub_type", ""),
        )
        return papers, search_errors

    if use_stream:
        def generate():
            search_thread = None
            try:
                analysis = None
                for item in state.search_ai.analyze_query_stream(user_input, lang=lang):
                    if isinstance(item, dict):
                        # 最后一个是分析结果
                        analysis = item
                    else:
                        # 流式 chunk
                        yield item

                if analysis is None:
                    yield "\nAI_ERROR:analysis_failed"
                    return

                # 在后台线程启动搜索，避免阻塞流式响应
                search_state = {"papers": None, "errors": None, "error": None}

                def _run_search():
                    try:
                        print(f"[INFO] Starting search with query: {analysis.get('query', '')[:50]}")
                        papers, search_errors = do_search(analysis)
                        search_state["papers"] = papers
                        search_state["errors"] = search_errors
                        print(f"[INFO] Search completed: {len(papers)} papers, {len(search_errors)} errors")
                    except Exception as e:
                        import traceback
                        print(f"[ERROR] AI search failed: {e}")
                        traceback.print_exc()
                        search_state["error"] = str(e)

                search_thread = threading.Thread(target=_run_search, daemon=True)
                search_thread.start()
                search_done = threading.Event()

                # 通知前端搜索已开始
                yield "\n\n" + ("🔍 Searching databases..." if lang == 'en' else "🔍 正在检索数据库...")

                # 非阻塞等待搜索完成（最多90秒，每2秒检查一次）
                MAX_WAIT = 90
                waited = 0
                last_yield_time = time.time()
                while waited < MAX_WAIT:
                    # 检查搜索是否完成
                    if not search_thread.is_alive():
                        search_done.set()
                        break
                    # 使用短超时的join，避免长时间阻塞
                    search_thread.join(timeout=0.1)
                    waited += 0.1
                    # 每10秒输出一次等待状态（使用时间差避免阻塞影响输出）
                    current_time = time.time()
                    if current_time - last_yield_time >= 10:
                        yield f"\n" + (f"⏳ Waited {int(waited)}s..." if lang == 'en' else f"⏳ 已等待 {int(waited)}秒...")
                        last_yield_time = current_time

                # 确保 happens-before：join() 保证线程写入对主线程可见
                search_thread.join(timeout=0)
                # 搜索完成，无论成功失败都返回结果
                if search_thread.is_alive():
                    print("[WARN] Search thread still alive after timeout")
                    yield "\nAI_ERROR:search_timeout"
                    return

                # 即使有错误，也尝试返回部分结果
                if search_state["error"]:
                    print(f"[WARN] Search had error: {search_state['error']}, but returning partial results")

                try:
                    papers = search_state["papers"] or []
                    # [Fix #13] 确保 search_errors 始终是 list，避免 tuple 导致 append 失败
                    search_errors = list(search_state["errors"] or [])
                    if search_state["error"]:
                        search_errors.append(("Search error: " if lang == 'en' else "搜索异常: ") + search_state['error'])
                    # Phase 5a: 跨源 DOI 去重
                    try:
                        papers = deduplicate_papers(papers)
                    except Exception as e:
                        print(f"[WARN] Dedup failed in ai-search (stream): {e}")

                    with state.cache_lock:
                        state.cached_papers["papers"] = papers
                        # [Fix] 使用 query_en 作为缓存的查询（用于后续引用图谱等操作）
                        state.cached_papers["query"] = analysis.get("query_en", analysis.get("query", user_input))
                    results = [_escape_paper(p) for p in papers]
                    # 构建完整的 resp 对象用于 fallback 缓存
                    resp = {
                        "total": len(results),
                        "query": analysis.get("query_en", analysis.get("query", "")),
                        "query_zh": analysis.get("query_zh", ""),
                        "explanation": analysis.get("explanation", ""), "analysis": analysis, "papers": results,
                    }
                    if search_errors:
                        resp["errors"] = search_errors
                    if hasattr(state.engine, '_last_timing_info') and state.engine._last_timing_info:
                        resp["timing"] = state.engine._last_timing_info
                    with state.cache_lock:
                        state.last_ai_search_result["resp"] = resp
                    # 分批发送论文（每批 20 篇），避免大 JSON 被 Werkzeug 缓冲区截断
                    batch_size = 20
                    total_batches = (len(results) + batch_size - 1) // batch_size
                    for i in range(0, len(results), batch_size):
                        batch = results[i:i + batch_size]
                        batch_event = {
                            "batch": i // batch_size,
                            "total_batches": max(total_batches, 1),
                            "papers": batch,
                            "total": len(results),
                        }
                        batch_json = json.dumps(batch_event, ensure_ascii=False)
                        batch_payload = "\n__RESULT_BATCH__" + batch_json
                        print(f"[INFO] Yielding result batch {i // batch_size + 1}/{max(total_batches, 1)}: {len(batch)} papers, payload size: {len(batch_payload)} bytes")
                        yield batch_payload
                    # 最终结果（不含 papers，只含元数据）
                    meta_event = {
                        "total": len(results),
                        "query": analysis.get("query_en", analysis.get("query", "")),
                        "query_zh": analysis.get("query_zh", ""),
                        "explanation": analysis.get("explanation", ""),
                        "analysis": analysis,
                        "errors": search_errors,
                        "timing": resp.get("timing", {}),
                    }
                    meta_json = json.dumps(meta_event, ensure_ascii=False)
                    result_payload = "\n__SEARCH_RESULT__" + meta_json
                    print(f"[INFO] Yielding search result meta: payload size: {len(result_payload)} bytes")
                    yield result_payload
                    print(f"[INFO] Yield completed successfully")
                except Exception as build_err:
                    import traceback
                    print(f"[ERROR] Failed to build search results: {build_err}")
                    traceback.print_exc()
                    # 即使构建失败，也返回一个空结果，避免前端永远等待
                    error_resp = {
                        "total": 0,
                        "query": analysis.get("query", user_input) if analysis else user_input,
                        "explanation": "",
                        "papers": [],
                        "errors": [("Result build failed: " if lang == 'en' else "结果构建失败: ") + str(build_err)],
                    }
                    yield "\n__SEARCH_RESULT__" + json.dumps(error_resp, ensure_ascii=False)

                print(f"[INFO] generate() generator finished normally")
            finally:
                # 确保客户端断连时清理后台搜索线程并写入 fallback 缓存
                if search_thread and search_thread.is_alive():
                    print("[INFO] Client disconnected, search thread still running")
                # 即使客户端断连，也尝试设置 fallback 结果
                try:
                    _analysis = analysis
                    _search_state = search_state
                except NameError:
                    _analysis = None
                    _search_state = {}
                if _analysis is not None and _search_state.get("papers"):
                    with state.cache_lock:
                        if state.last_ai_search_result.get("resp") is None:
                            try:
                                papers = _search_state["papers"] or []
                                results = [_escape_paper(p) for p in papers]
                                state.last_ai_search_result["resp"] = {
                                    "total": len(results),
                                    "query": _analysis.get("query_en", _analysis.get("query", user_input)),
                                    "query_zh": _analysis.get("query_zh", ""),
                                    "explanation": _analysis.get("explanation", ""),
                                    "analysis": _analysis,
                                    "papers": results,
                                }
                                state.cached_papers["papers"] = papers
                            except Exception:
                                pass

        return Response(generate(), mimetype="text/plain; charset=utf-8",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # 非流式模式
    try:
        analysis = state.search_ai.analyze_query(user_input, lang=lang)
        papers, search_errors = do_search(analysis)
    except Exception as e:
        print(f"[ERROR] AI search failed: {e}")
        return jsonify({"error": "ai_search_failed"}), 500
    # Phase 5a: 跨源 DOI 去重
    try:
        papers = deduplicate_papers(papers)
    except Exception as e:
        print(f"[WARN] Dedup failed in ai-search (non-stream): {e}")
    with state.cache_lock:
        state.cached_papers["papers"] = papers
        # [Fix] 使用 query_en 作为缓存的查询
        state.cached_papers["query"] = analysis.get("query_en", analysis.get("query", user_input))
    results = [_escape_paper(p) for p in papers]
    resp = {
        "total": len(results),
        "query": analysis.get("query_en", analysis.get("query", "")),
        "query_zh": analysis.get("query_zh", ""),
        "explanation": analysis.get("explanation", ""), "analysis": analysis, "papers": results,
    }
    if search_errors:
        resp["errors"] = search_errors
    # 添加 timing 信息
    if hasattr(state.engine, '_last_timing_info') and state.engine._last_timing_info:
        resp["timing"] = state.engine._last_timing_info
    return jsonify(resp)


@search_bp.route("/api/batch-doi", methods=["POST"])
def batch_doi():
    """批量 DOI 查询"""
    state = _state()
    data = request.json or {}
    dois = data.get("dois", [])
    if not dois:
        return jsonify({"error": "no_doi_list"}), 400

    found_papers = []
    found_escaped = []
    valid_count = 0
    for doi in dois[:50]:
        doi = doi.strip()
        if not doi:
            continue
        valid_count += 1
        paper = state.engine.search_by_doi(doi)
        if paper:
            found_papers.append(paper)
            found_escaped.append(_escape_paper(paper))

    # 合并到 cached_papers（确保后续导出/AI分析可用）
    with state.cache_lock:
        existing_dois = {p.doi.lower() for p in state.cached_papers["papers"] if p.doi}
        for p in found_papers:
            if p.doi and p.doi.lower() not in existing_dois:
                state.cached_papers["papers"].append(p)
                existing_dois.add(p.doi.lower())

    return jsonify({"total": len(found_escaped), "papers": found_escaped, "not_found": valid_count - len(found_escaped)})


@search_bp.route("/api/paper-by-doi", methods=["POST"])
def paper_by_doi():
    """通过 DOI 获取单篇论文详情"""
    state = _state()
    data = request.json or {}
    doi = data.get("doi", "").strip()
    if not doi:
        return jsonify({"error": "no_doi"}), 400

    paper = state.engine.search_by_doi(doi)
    if not paper:
        return jsonify({"error": "paper_not_found"}), 404

    # 添加到缓存（避免重复）
    with state.cache_lock:
        existing_dois = {p.doi.lower() for p in state.cached_papers["papers"] if p.doi}
        if paper.doi and paper.doi.lower() not in existing_dois:
            state.cached_papers["papers"].append(paper)

    return jsonify({"paper": _escape_paper(paper)})


# [新增] 翻译缓存管理 API
@search_bp.route("/api/translation/cache-size", methods=["GET"])
def translation_cache_size():
    """获取翻译缓存大小"""
    state = _state()
    try:
        size = state.engine._translator.get_cache_size() if hasattr(state.engine, '_translator') else 0
        return jsonify({"size": size})
    except Exception as e:
        return jsonify({"size": 0, "error": str(e)})


@search_bp.route("/api/translation/cache", methods=["DELETE"])
def clear_translation_cache():
    """清除翻译缓存"""
    state = _state()
    try:
        if hasattr(state.engine, '_translator') and state.engine._translator._cache:
            with state.engine._translator._cache._lock:
                state.engine._translator._cache._cache = {}
                state.engine._translator._cache._save_cache()
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "翻译器未初始化"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# === 数据源健康监控 API ===

@search_bp.route("/api/source-health", methods=["GET"])
def get_source_health():
    """获取所有数据源的健康状态"""
    state = _state()
    try:
        health = state.engine.get_source_health()
        return jsonify({"sources": health})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@search_bp.route("/api/source-health/toggle", methods=["POST"])
def toggle_source_health():
    """手动启用/禁用数据源"""
    state = _state()
    data = request.json or {}
    source_name = data.get("source")
    enabled = data.get("enabled", True)

    if not source_name:
        return jsonify({"error": "missing_source"}), 400

    try:
        state.engine.toggle_source(source_name, enabled)
        new_status = state.engine.get_source_health().get(source_name, {})
        return jsonify({"success": True, "status": new_status})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@search_bp.route("/api/source-health/reset", methods=["POST"])
def reset_source_health():
    """重置数据源健康状态"""
    state = _state()
    data = request.json or {}
    source_name = data.get("source")  # None 则重置全部

    try:
        state.engine.reset_source_health(source_name)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
