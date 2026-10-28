from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

assistant_bp = Blueprint('assistant', __name__)


def _contains_any(text, keywords):
    return any(keyword in text for keyword in keywords)


def build_assistant_reply(message):
    """Return a deterministic assistant reply for the local P1 mid build."""
    text = (message or '').strip().lower()
    if not text:
        return (
            "Ask me about the project modules, APIs, deployment, datasets, "
            "policies, membership plans, or how to run the app locally."
        )

    if _contains_any(text, ['api', 'endpoints', 'backend route', 'rest']):
        return (
            "This project uses internal Flask REST APIs, not external public APIs. "
            "The main routes are auth, dashboard, resources, security, cost, governance, "
            "settings, organization, reports, and this assistant route."
        )

    if _contains_any(text, ['dataset', 'data set', 'training data', 'csv', 'sample data']):
        return (
            "This version is configured around real public datasets only. "
            "Use Alibaba Cluster Trace v2018 for FinOps and utilization, CICIDS2017 for security, "
            "and place staged exports under backend/data/finops and backend/data/security. "
            "Governance remains rules-based and does not use free-text parsing."
        )

    if _contains_any(text, ['deploy', 'production', 'host', 'release']):
        return (
            "For real deployment, use PostgreSQL instead of SQLite, run the backend with "
            "Gunicorn or another production WSGI server, place the React build behind Nginx "
            "or a static host, move secrets to environment variables, and configure mail/redis "
            "services properly. The current build is local-development friendly, not production-hardened."
        )

    if _contains_any(text, ['policy', 'policies', 'governance']):
        return (
            "The governance module is rules-based. Policies are written as explicit key=value rules such as "
            "resource_type=database; encryption=required; public_access=deny. "
            "The compiler lives in backend/app/ai_models/policy_engine.py and the API lives in "
            "backend/app/routes/governance.py."
        )

    if _contains_any(text, ['membership', 'plan', 'subscription', 'tier']):
        return (
            "Membership can be added as a future-facing module without changing the simulator core. "
            "A good structure is Starter, Pro, and Enterprise plans, where the simulation still works fully "
            "but each plan can highlight limits, advanced tools, and coming-soon features."
        )

    if _contains_any(text, ['localhost', 'run', 'start', 'how do i use', 'how to use']):
        return (
            "Run the backend from backend/ with PORT=5000 /home/abdur/cloud-simulator-fyp/backend/.venv/bin/python run.py, "
            "then run the frontend from frontend/ with DANGEROUSLY_DISABLE_HOST_CHECK=true HOST=localhost PORT=3001 npm start. "
            "If port 3001 is busy, CRA will offer the next available port."
        )

    if _contains_any(text, ['login', 'credential', 'credentials', 'password']):
        return (
            "The local demo account is admin@cloud.local with password Admin1234. "
            "The earlier test@gmail.com text on the login form was only an example placeholder, not a seeded account."
        )

    if _contains_any(text, ['resource', 'vm', 'database', 'security', 'cost', 'dashboard']):
        return (
            "The app modules are Dashboard, Resources, Security, Cost Management, Governance, Settings, "
            "Organization, Reports, Authentication, and the new Membership page. "
            "Use the sidebar to move between them after logging in."
        )

    return (
        "I can help with the project architecture, APIs, datasets, deployment, policies, membership plans, "
        "and how to run the app locally. Try asking a specific question about one of those topics."
    )


@assistant_bp.route('/chat', methods=['POST'])
@jwt_required(optional=True)
def chat():
    """Simple local assistant for the project demo."""
    data = request.get_json(silent=True) or {}
    message = data.get('message', '')
    if not isinstance(message, str) or len(message) > 1000:
        return jsonify({'error': 'message must be text of at most 1000 characters'}), 400
    reply = build_assistant_reply(message)
    return jsonify({
        'reply': reply,
        'suggested_actions': [
            'Show the APIs used',
            'Explain deployment',
            'Explain datasets',
            'Show membership plans',
            'How to run locally',
        ],
    }), 200
