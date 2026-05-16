from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.models.organization import OrganizationMember

membership_bp = Blueprint('membership', __name__)



def _resolve_membership(user_id, requested_org_id=None):
    """Resolve membership with a safe demo fallback."""
    if requested_org_id:
        member = OrganizationMember.query.filter_by(
            organization_id=requested_org_id,
            user_id=user_id,
        ).first()
        if member:
            return member
        return None

    member = (
        OrganizationMember.query
        .filter_by(user_id=user_id)
        .order_by(OrganizationMember.joined_at.asc(), OrganizationMember.id.asc())
        .first()
    )
    if member:
        return member

    return None


@membership_bp.route('/current', methods=['GET'])
@jwt_required()
def current_membership():
    user_id = get_jwt_identity()
    org_id = request.args.get('organization_id', type=int)
    member = _resolve_membership(user_id, org_id)
    if not member:
        return jsonify({
            'status': 'error',
            'error': {'message': 'Membership not found.'},
        }), 404

    org = member.organization
    if not org:
        return jsonify({
            'status': 'error',
            'error': {'message': 'Organization not found for membership.'},
        }), 404

    payload = {
        'organization_id': org.id,
        'organization_name': org.name,
        'resource_limit': org.max_resources,
        'member_role': member.role,
    }
    return jsonify({
        'status': 'success',
        'data': payload,
        **payload,
    }), 200


@membership_bp.route('/me', methods=['GET'])
@jwt_required()
def membership_me():
    """Return current user membership safely for demo flows."""
    user_id = get_jwt_identity()
    member = _resolve_membership(user_id)

    if not member:
        return jsonify({
            'status': 'error',
            'error': {'message': 'Membership not found.'},
        }), 404

    return jsonify({
        'status': 'success',
        'data': {
            'user_id': member.user_id,
            'organization_id': member.organization_id,
            'role': member.role or 'owner',
        },
    }), 200
