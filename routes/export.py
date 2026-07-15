"""Export routes for PaperLens"""

import os
import re
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from core.config import load_config
from core.utils import _check_url_safety, _escape_paper
from exporters import export_ris, export_bibtex, export_csv, export_endnote_xml

export_bp = Blueprint('export', __name__)


def _state():
    return current_app.config["APP_STATE"]


@export_bp.route("/api/export", methods=["POST"])
def export():
    state = _state()
    data = request.json or {}
    fmt = data.get("format", "ris")
    save_to_disk = data.get("save_to_disk", False)

    # 支持直接传入 papers 列表（用于单篇导出），或通过 indices 从缓存选取
    direct_papers = data.get("papers")
    if isinstance(direct_papers, list) and len(direct_papers) > 0:
        # 前端传入的是 dict，需要转换为 Paper 对象以兼容导出函数
        from search_engine import Paper
        _paper_fields = set(Paper.__dataclass_fields__.keys())
        selected = [
            Paper(**{k: v for k, v in p.items() if k in _paper_fields})
            if isinstance(p, dict) else p
            for p in direct_papers
        ]
        query = selected[0].title if selected else ""
    else:
        indices = data.get("indices", [])
        if not isinstance(indices, list):
            return jsonify({"error": "invalid_indices"}), 400
        # [Fix #14] 强制 int 转换，过滤无效索引
        try:
            indices = [int(i) for i in indices]
        except (ValueError, TypeError):
            return jsonify({"error": "invalid_indices"}), 400
        with state.cache_lock:
            papers = list(state.cached_papers["papers"])
            query = state.cached_papers["query"]
        if not papers:
            return jsonify({"error": "no_export_data"}), 400
        selected = [papers[i] for i in indices if 0 <= i < len(papers)] if indices else papers

    # 文件名：用第一篇论文标题，多篇时加"等N篇"
    first_title = ""
    _first = selected[0] if selected else None
    _title = _first.get("title") if isinstance(_first, dict) else getattr(_first, "title", None)
    if _title:
        first_title = re.sub(r'[^\w\-]', '_', _title[:50]).strip('_')
    safe_name = first_title or re.sub(r'[^\w\-]', '_', query[:40]).strip('_') or "papers"
    # [Fix #20] 额外路径穿越防护：确保文件名不含路径分隔符
    safe_name = re.sub(r'[/\\..]', '_', safe_name)
    if len(selected) > 1:
        safe_name += f"_等{len(selected)}篇"
    # 添加时间戳避免文件名重复
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if fmt == "ris":
        content, filename, mime = export_ris(selected), f"{safe_name}_{timestamp}.ris", "application/x-research-info-systems"
    elif fmt == "bibtex":
        content, filename, mime = export_bibtex(selected), f"{safe_name}_{timestamp}.bib", "application/x-bibtex"
    elif fmt == "csv":
        content, filename, mime = export_csv(selected), f"{safe_name}_{timestamp}.csv", "text/csv"
    elif fmt == "endnotexml":
        content, filename, mime = export_endnote_xml(selected), f"{safe_name}_{timestamp}.xml", "application/xml"
    elif fmt in ("apa", "mla", "gb7714", "chicago", "vancouver"):
        from citation_formatter import format_citations_batch
        content = format_citations_batch(selected, fmt)
        filename = f"{safe_name}_{fmt}_{timestamp}.txt"
        mime = "text/plain"
    else:
        return jsonify({"error": "unsupported_format", "format": fmt}), 400

    if save_to_disk:
        export_dir = load_config().get("export_path", "") or os.path.join(os.path.expanduser("~"), "PaperLens_Exports")
        try:
            # 子文件夹分类：pdf/ris/bibtex/csv/citation
            sub_map = {"ris": "RIS", "bibtex": "BibTeX", "csv": "CSV", "endnotexml": "EndNote"}
            sub = sub_map.get(fmt, "Citations" if fmt in ("apa","mla","gb7714","chicago","vancouver") else "Other")
            target_dir = os.path.join(export_dir, sub)
            os.makedirs(target_dir, exist_ok=True)
            filepath = os.path.join(target_dir, filename)
            # 路径穿越防护：确保解析后的路径在 export_dir 内
            real_dir = os.path.realpath(export_dir)
            real_file = os.path.realpath(filepath)
            if not real_file.startswith(real_dir + os.sep) and real_file != real_dir:
                return jsonify({"error": "invalid_path"}), 400
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return jsonify({"ok": True, "path": filepath, "filename": filename})
        except Exception as e:
            print(f"[ERROR] Operation failed: {e}")
            return jsonify({"error": "operation_failed", "content": content, "filename": filename, "mime": mime}), 500

    return jsonify({"content": content, "filename": filename, "mime": mime})


@export_bp.route("/api/download-pdf", methods=["POST"])
def download_pdf():
    """验证 OA 论文 PDF 链接并下载到指定目录"""
    import requests as req_lib
    data = request.json or {}
    url = data.get("url", "").strip()
    title = data.get("title", "paper")[:50]
    save_to_disk = data.get("save_to_disk", False)

    if not url:
        return jsonify({"error": "no_download_link"}), 400

    safe, err = _check_url_safety(url)
    if not safe:
        return jsonify({"error": err}), 403 if err == "blocked_internal_url" else 400

    safe_title = re.sub(r'[^\w\-]', '_', title).strip('_') or "paper"
    filename = f"{safe_title}.pdf"

    try:
        # 使用 requests 库，禁用自动重定向以手动验证重定向目标
        resp = req_lib.get(url, headers={"User-Agent": "Mozilla/5.0"},
                          timeout=15, stream=True, allow_redirects=False)
        # 手动处理重定向，检查每个重定向目标（含 307/308）
        redirect_count = 0
        current_url = url
        while resp.status_code in (301, 302, 303, 307, 308) and redirect_count < 5:
            redirect_url = resp.headers.get("Location", "")
            if not redirect_url:
                break
            # 相对路径转绝对路径
            if redirect_url.startswith("/"):
                from urllib.parse import urljoin
                redirect_url = urljoin(current_url, redirect_url)
            safe, err = _check_url_safety(redirect_url)
            if not safe:
                resp.close()
                return jsonify({"error": err}), 403 if err == "blocked_internal_url" else 400
            current_url = redirect_url
            resp.close()  # 关闭旧 response stream，避免连接泄漏
            resp = req_lib.get(redirect_url, headers={"User-Agent": "Mozilla/5.0"},
                              timeout=15, stream=True, allow_redirects=False)
            redirect_count += 1

        # 验证 PDF 头（只读第一个 chunk，避免将整个响应读入内存）
        first_chunk = next(resp.iter_content(chunk_size=8192), b"")
        if not first_chunk.startswith(b'%PDF'):
            return jsonify({"error": "not_pdf"}), 400

        # 检查文件大小限制（100MB）
        content_length = resp.headers.get("Content-Length")
        try:
            if content_length and int(content_length) > 100 * 1024 * 1024:
                return jsonify({"error": "file_too_large"}), 400
        except (ValueError, TypeError):
            pass  # Content-Length 无效时忽略，继续下载

        if save_to_disk:
            export_dir = load_config().get("export_path", "") or os.path.join(os.path.expanduser("~"), "PaperLens_Exports")
            try:
                pdf_dir = os.path.join(export_dir, "PDF")
                os.makedirs(pdf_dir, exist_ok=True)
                filepath = os.path.join(pdf_dir, filename)
                # 验证路径安全
                real_export = os.path.realpath(export_dir)
                real_filepath = os.path.realpath(filepath)
                if not (real_filepath.startswith(real_export + os.sep) or real_filepath == real_export):
                    return jsonify({"error": "invalid_path"}), 400
                # 流式写入，限制大小
                total_size = 0
                max_size = 100 * 1024 * 1024  # 100MB
                with open(filepath, "wb") as f:
                    f.write(first_chunk)
                    total_size += len(first_chunk)
                    for chunk in resp.iter_content(chunk_size=8192):
                        total_size += len(chunk)
                        if total_size > max_size:
                            f.close()
                            os.remove(filepath)
                            return jsonify({"error": "file_too_large"}), 400
                        f.write(chunk)
                return jsonify({"ok": True, "path": filepath, "filename": filename})
            except Exception as e:
                print(f"[ERROR] PDF download failed: {e}")
                return jsonify({"error": "download_failed"}), 500

        return jsonify({"filename": filename, "url": url})
    except Exception as e:
        print(f"[ERROR] PDF link verify failed: {e}")
        return jsonify({"error": "link_verify_failed"}), 500
