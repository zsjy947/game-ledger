"""WSGI 入口（供 waitress/gunicorn 等生产服务器使用）。

本地使用无需关心本文件；日常启动请用「启动.bat」或 python run.py。
"""

from game_ledger import create_app

app = create_app()
