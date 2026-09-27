"""Switch 卡带价格统计 — Flask 应用包。"""

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from . import config, database

__version__ = "1.3.0"


def create_app() -> Flask:
    """应用工厂：初始化数据库、注册蓝图与全局错误处理。"""
    database.init_db()

    app = Flask(
        __name__,
        template_folder=str(config.TEMPLATE_DIR),
        static_folder=str(config.STATIC_DIR),
    )

    from .routes import bp

    app.register_blueprint(bp)

    @app.errorhandler(HTTPException)
    def handle_http_error(e: HTTPException):
        """API 路径下的 HTTP 错误统一返回 JSON，其余保持默认页面。"""
        if request.path.startswith("/api/"):
            message = {404: "接口不存在", 405: "请求方法不允许"}.get(e.code, e.description)
            return jsonify({"success": False, "message": message}), e.code
        return e

    @app.errorhandler(Exception)
    def handle_unexpected_error(e: Exception):
        app.logger.exception("未处理的异常")
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "message": "服务器内部错误"}), 500
        return "服务器内部错误", 500

    return app
