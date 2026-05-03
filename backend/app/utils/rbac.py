from functools import wraps

ROLE_HIERARCHY = {'viewer': 0, 'member': 1, 'admin': 2, 'owner': 3}


def get_user_role_in_org(user_id, org_id):
    from app.models.organization import OrganizationMember
    m = OrganizationMember.query.filter_by(
        user_id=user_id,
        organization_id=org_id
    ).first()
    return m.role if m else None


def require_org_role(min_role='member'):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            from flask import request, jsonify
            from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
            verify_jwt_in_request()
            user_id = int(get_jwt_identity())
            data = request.get_json(silent=True) or {}
            org_id = (
                data.get('organization_id')
                or data.get('org_id')
                or request.args.get('organization_id')
                or request.args.get('org_id')
                or (request.view_args or {}).get('org_id')
            )
            if not org_id:
                return jsonify({'error': 'organization_id required'}), 400
            role = get_user_role_in_org(user_id, int(org_id))
            if not role:
                return jsonify({'error': 'Not a member'}), 403
            if ROLE_HIERARCHY.get(role, -1) < ROLE_HIERARCHY[min_role]:
                return jsonify({'error': f'Requires {min_role} role'}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator
