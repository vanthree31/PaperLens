"""PaperLens - AI-Powered Research Assistant"""

import sys
import os
import threading
import time

if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from server import create_app


def main():
    app = create_app()

    port = 51234
    server_thread = threading.Thread(
        target=lambda: app.run(
            host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True
        ),
        daemon=True,
    )
    server_thread.start()
    time.sleep(1.5)

    try:
        import webview

        kwargs = {
            "title": "PaperLens",
            "url": f"http://127.0.0.1:{port}",
            "width": 1200,
            "height": 800,
            "min_size": (800, 600),
            "resizable": True,
            "text_select": True,
        }
        webview.create_window(**kwargs)
        webview.start(gui="edgechromium", debug=False)
    except ImportError:
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{port}")
        print(f"已在浏览器中打开: http://127.0.0.1:{port}")
        print("按 Ctrl+C 退出")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
