import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv

# Load .env for local development
load_dotenv()

from config import config_map

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
bcrypt = Bcrypt()

login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'


def create_app(config_name: str = None) -> Flask:
    # Auto-detect environment from FLASK_ENV
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__, instance_relative_config=True)
    cfg = config_map.get(config_name, config_map['default'])
    app.config.from_object(cfg)

    # Only create instance folder in non-serverless environments
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    bcrypt.init_app(app)

    with app.app_context():
        from app import models  # noqa: F401
        from app.utils.listeners import register_listeners
        register_listeners(app, db)

        # Register Blueprints
        from app.modules.auth import auth_bp
        from app.modules.dashboard import dashboard_bp
        from app.modules.crm import crm_bp
        from app.modules.scm import scm_bp
        from app.modules.inventory import inventory_bp
        from app.modules.purchases import purchases_bp
        from app.modules.sales import sales_bp
        from app.modules.manufacturing import manufacturing_bp
        from app.modules.accounting import accounting_bp
        from app.modules.reports import reports_bp
        from app.modules.banking import banking_bp
        from app.modules.finance import finance_bp
        from app.modules.settings import settings_bp
        from app.modules.security import security_bp

        app.register_blueprint(auth_bp)
        app.register_blueprint(dashboard_bp)
        app.register_blueprint(crm_bp)
        app.register_blueprint(scm_bp)
        app.register_blueprint(inventory_bp)
        app.register_blueprint(purchases_bp)
        app.register_blueprint(sales_bp)
        app.register_blueprint(manufacturing_bp)
        app.register_blueprint(accounting_bp)
        app.register_blueprint(reports_bp)
        app.register_blueprint(banking_bp, url_prefix='/banking')
        app.register_blueprint(finance_bp, url_prefix='/finance')
        app.register_blueprint(settings_bp, url_prefix='/settings')
        app.register_blueprint(security_bp, url_prefix='/security')

        # Tables are managed via Flask-Migrate / init_db.py
        # Do NOT call db.create_all() here — it causes Vercel cold-start timeouts

    # ── Global template context ──────────────────────────────
    @app.context_processor
    def inject_globals():
        from datetime import datetime
        return {
            'company_name': 'SIKKA GROUPS OF INDUSTRIES',
            'company_full': 'SIKKA GROUPS OF INDUSTRIES',

            'current_year': datetime.utcnow().year,
        }

    # ── Error handlers ───────────────────────────────────────
    @app.errorhandler(403)
    def forbidden(e):
        from flask import render_template
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(e):
        from flask import render_template
        import traceback
        app.logger.error(f'Internal Server Error: {e}\n{traceback.format_exc()}')
        db.session.rollback()  # Rollback any failed transaction
        return render_template('errors/500.html'), 500

    # Log startup info for debugging
    app.logger.info(f'Sikka ERP started with config: {config_name}')
    app.logger.info(f'Database URI prefix: {app.config.get("SQLALCHEMY_DATABASE_URI", "NOT SET")[:30]}...')

    return app