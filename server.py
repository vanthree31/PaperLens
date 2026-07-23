"""Flask 后端 - API 路由入口"""

import os
from flask import Flask, send_from_directory
from core.state import AppState


def create_app():
    app = Flask(__name__, static_folder="static", static_url_path="/static")

    # Phase 5a: 启动时自动迁移用户数据 schema
    try:
        from schema_migrate import migrate_all
        from core.config import _get_app_data_dir

        migrate_all(_get_app_data_dir())
    except Exception as e:
        print(f"[WARN] Schema migration failed: {e}")

    # 初始化共享状态
    state = AppState()
    app.config["APP_STATE"] = state

    # 注册路由蓝图
    from routes.search import search_bp
    from routes.ai import ai_bp
    from routes.collections import collections_bp
    from routes.graph import graph_bp
    from routes.history import history_bp
    from routes.export import export_bp
    from routes.system import system_bp
    from routes.zotero import zotero_bp
    from routes.carsi import carsi_bp
    from routes.wanfang import wanfang_bp
    from routes.tags import tags_bp

    for bp in [
        search_bp,
        ai_bp,
        collections_bp,
        graph_bp,
        history_bp,
        export_bp,
        system_bp,
        zotero_bp,
        carsi_bp,
        wanfang_bp,
        tags_bp,
    ]:
        app.register_blueprint(bp)

    # 安全响应头
    @app.after_request
    def add_security_headers(response):
        # Content-Security-Policy: 限制脚本/样式来源，防止 XSS
        # 'unsafe-inline' 用于兼容现有内联 onclick/style，后续迁移后可收紧
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://d3js.org; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self' https:; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    # 首页路由
    @app.route("/")
    def index():
        return send_from_directory("static", "index.html")

    return app


if __name__ == "__main__":
    app = create_app()
    app.secret_key = os.urandom(24)
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="127.0.0.1", port=5000, debug=debug, threaded=True)
