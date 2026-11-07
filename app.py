import os
from flask import Flask, g, render_template

from config import Config
import db as db_module
from utils import load_logged_in_user, unread_notification_count


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db_module.init_app(app)

    # Auto-create the database on first run so `python app.py` just works.
    if not os.path.exists(app.config["DATABASE"]):
        with app.app_context():
            db_module.init_db()
            from seed import seed_admin
            seed_admin()

    @app.before_request
    def before_request():
        load_logged_in_user()
        g.notif_count = unread_notification_count(g.user["id"]) if g.user else 0

    @app.context_processor
    def inject_globals():
        return {"current_user": g.get("user"), "notif_count": g.get("notif_count", 0)}

    # ---- Blueprints ----
    from blueprints.auth import bp as auth_bp
    from blueprints.main import bp as main_bp
    from blueprints.items import bp as items_bp
    from blueprints.search import bp as search_bp
    from blueprints.claims import bp as claims_bp
    from blueprints.admin import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(items_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(413)
    def too_large(e):
        from flask import flash, redirect, request
        flash("File too large. Please upload an image under 8 MB.", "danger")
        return redirect(request.referrer or "/")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
