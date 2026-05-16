from flask import Flask
from flask import jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_mail import Mail
from flask_socketio import SocketIO, join_room
from werkzeug.exceptions import HTTPException
from app.config import config
# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()
mail = Mail()
socketio = SocketIO(cors_allowed_origins="*", async_mode='eventlet', cors_credentials=True, ping_timeout=60, ping_interval=25)

# Import simulation_engine after socketio to avoid circular imports
from app.services.simulation_engine import SimulationEngine
from flask_socketio import join_room, leave_room, rooms

simulation_engine = SimulationEngine()


@socketio.on('join_room', namespace='/metrics')
def handle_join_room(data):
    """Allow clients to join an org-scoped room on the /metrics namespace and leave previous ones."""
    if isinstance(data, dict):
        org_id = data.get('org_id')
        try:
            org_id = int(org_id)
        except (TypeError, ValueError):
            org_id = None

        if org_id is not None:
            room = f'org_{org_id}'
            # Leave previous org rooms to prevent duplicate events and cross-org leakage
            for r in rooms():
                if r.startswith('org_') and r != room:
                    leave_room(r)
            join_room(room)


def _json_error(message, status_code=500, code='internal_error'):
    return jsonify({
        'status': 'error',
        'error': {
            'message': message,
        },
    }), status_code


def create_app(config_name='default'):
    """Application factory pattern."""
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    mail.init_app(app)
    socketio.init_app(app)
    from app.services.resource_simulator import ResourceSimulator
    app.simulator = ResourceSimulator()
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    from app.utils.dataset_loader import load_dataset

    load_dataset()

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return _json_error(
            error.description or error.name,
            status_code=error.code or 500,
            code=error.name.lower().replace(' ', '_'),
        )

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.exception('Unhandled application error')
        return _json_error('Internal server error', status_code=500, code='internal_error')

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.organization import org_bp
    from app.routes.resources import resource_bp
    from app.routes.governance import governance_bp
    from app.routes.security import security_bp
    from app.routes.cost import cost_bp
    from app.routes.reports import reports_bp
    from app.routes.settings import settings_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.assistant import assistant_bp
    from app.routes.learning import learning_bp
    from app.routes.scenarios import scenarios_bp
    from app.routes.membership import membership_bp
    from app.routes.progress import progress_bp
    from app.routes.admin import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(org_bp, url_prefix='/api/org')
    from app.routes.organization import simple_invite
    app.add_url_rule('/api/invite', view_func=simple_invite, methods=['POST'])
    app.register_blueprint(resource_bp, url_prefix='/api/resources')
    app.register_blueprint(governance_bp, url_prefix='/api/governance')
    app.register_blueprint(security_bp, url_prefix='/api/security')
    app.register_blueprint(cost_bp, url_prefix='/api/cost')
    app.register_blueprint(reports_bp, url_prefix='/api/reports')
    app.register_blueprint(settings_bp, url_prefix='/api/settings')
    app.register_blueprint(dashboard_bp, url_prefix='/api/dashboard')
    app.register_blueprint(assistant_bp, url_prefix='/api/assistant')
    app.register_blueprint(learning_bp, url_prefix='/api/learning')
    app.register_blueprint(scenarios_bp, url_prefix='/api/scenarios')
    app.register_blueprint(membership_bp, url_prefix='/api/membership')
    app.register_blueprint(progress_bp, url_prefix='/api/progress')
    from app.routes.learning_timeline import timeline_bp
    app.register_blueprint(timeline_bp, url_prefix='/api/learning')

    # Create database tables
    with app.app_context():
        db.create_all()

        if not app.config.get('TESTING'):
            # ── Control-plane snapshot cache (2-second refresh) ───────────────
            # Provides fast dashboard reads without blocking HTTP request threads
            # on heavy simulation computation.
            from app.services.control_plane import start_control_plane_loop
            start_control_plane_loop()

        if app.config.get('ENABLE_REALTIME_METRICS') and not app.config.get('TESTING'):
            from app.services.metrics_streamer import metrics_streamer
            metrics_streamer.start()

        # ResourceSimulator — handles DES telemetry, ML security analysis,
        # per-VM RPS history, and autoscaling.  This is the primary simulation
        # thread; control_plane.py provides the MAPE loop and snapshot cache.
        if app.config.get('ENABLE_SIMULATION_THREADS') and not app.config.get('TESTING'):
            app.simulator.start(app)

    return app
