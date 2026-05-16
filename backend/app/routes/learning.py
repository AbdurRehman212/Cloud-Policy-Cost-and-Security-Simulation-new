from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app import db
from app.data.learning_content import LEARNING_CONTENT
from app.models.organization import OrganizationMember
from app.models.settings import UserSettings
from app.models.progress import UserProgress
from app.models.user import User
from app.services.learning_engine import SCENARIO_MAP, build_learning_profile, normalize_learning_level
from app.models.scenarios import ScenarioProgress

learning_bp = Blueprint('learning', __name__)


def _get_or_create_settings(user_id):
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if not settings:
        settings = UserSettings(user_id=user_id)
        db.session.add(settings)
        db.session.commit()
    return settings


def _selected_track_for_user(user_id, progress=None, selected_level=None):
    settings = _get_or_create_settings(user_id)
    dashboard_layout = settings.dashboard_layout if isinstance(settings.dashboard_layout, dict) else {}
    stored_level = dashboard_layout.get('learning_level')
    return normalize_learning_level(selected_level or stored_level or getattr(progress, 'learning_stage', None))


def _progress_timeline(user_id, org_id):
    entries = (
        ScenarioProgress.query
        .filter_by(user_id=user_id, org_id=org_id)
        .order_by(ScenarioProgress.started_at.asc(), ScenarioProgress.id.asc())
        .all()
    )
    timeline = []
    for entry in entries:
        timeline.append({
            'scenario_id': entry.scenario_id,
            'scenario_title': SCENARIO_MAP.get(entry.scenario_id, {}).get('title', f'Scenario {entry.scenario_id}'),
            'points_earned': entry.points_earned,
            'current_step': entry.current_step,
            'completed': entry.completed,
            'completed_at': entry.completed_at.isoformat() if entry.completed_at else None,
            'started_at': entry.started_at.isoformat() if entry.started_at else None,
        })
    return timeline


@learning_bp.route('/content/<action_key>', methods=['GET'])
def get_learning_content(action_key):
    content = LEARNING_CONTENT.get((action_key or '').strip().lower())
    if not content:
        return jsonify({'error': {'message': 'Learning content not found'}}), 404
    return jsonify({
        'status': 'success',
        'data': {
            'action_key': action_key,
            **content,
        },
    }), 200


@learning_bp.route('/profile', methods=['GET'])
@jwt_required()
def get_learning_profile():
    user_id = get_jwt_identity()
    org_id = request.args.get('organization_id', type=int)
    if not org_id:
        return jsonify({'error': {'message': 'organization_id required'}}), 400

    user = User.query.get(user_id)
    member = OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()
    progress = UserProgress.query.filter_by(user_id=user_id, org_id=org_id).first()
    selected_level = request.args.get('level')
    track = _selected_track_for_user(user_id, progress=progress, selected_level=selected_level)
    profile = build_learning_profile(user=user, membership=member, progress=progress, level=track)
    return jsonify({
        'status': 'success',
        'data': {
            **profile,
            'progress': progress.to_dict() if progress else None,
            'selected_level': track,
            'progress_timeline': _progress_timeline(user_id, org_id),
        },
    }), 200


@learning_bp.route('/experience', methods=['GET'])
@jwt_required()
def get_learning_experience():
    user_id = get_jwt_identity()
    org_id = request.args.get('organization_id', type=int)
    if not org_id:
        return jsonify({'error': {'message': 'organization_id required'}}), 400

    user = User.query.get(user_id)
    member = OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()
    progress = UserProgress.query.filter_by(user_id=user_id, org_id=org_id).first()
    selected_level = request.args.get('level')
    track = _selected_track_for_user(user_id, progress=progress, selected_level=selected_level)
    profile = build_learning_profile(user=user, membership=member, progress=progress, level=track)
    return jsonify({
        'status': 'success',
        'data': {
            **profile,
            'progress': progress.to_dict() if progress else None,
            'selected_level': track,
            'progress_timeline': _progress_timeline(user_id, org_id),
        },
    }), 200


@learning_bp.route('/level', methods=['POST'])
@jwt_required()
def set_learning_level():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    org_id = data.get('organization_id') or data.get('org_id')
    if not org_id:
        return jsonify({'error': {'message': 'organization_id required'}}), 400

    track = normalize_learning_level(data.get('level'))
    settings = _get_or_create_settings(user_id)
    dashboard_layout = settings.dashboard_layout if isinstance(settings.dashboard_layout, dict) else {}
    dashboard_layout.update({
        'learning_level': track,
        'learning_mode': 'guided',
    })
    settings.dashboard_layout = dashboard_layout
    db.session.commit()

    user = User.query.get(user_id)
    member = OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()
    progress = UserProgress.query.filter_by(user_id=user_id, org_id=org_id).first()
    profile = build_learning_profile(user=user, membership=member, progress=progress, level=track)
    return jsonify({
        'status': 'success',
        'data': {
            **profile,
            'selected_level': track,
            'progress': progress.to_dict() if progress else None,
            'progress_timeline': _progress_timeline(user_id, org_id),
        },
    }), 200
