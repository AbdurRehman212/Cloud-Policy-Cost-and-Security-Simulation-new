from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import text
from app import db
from flask import current_app
from app.services.control_plane import clear_snapshot_cache

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/reset-system', methods=['POST'])
@jwt_required()
def reset_system():
    """Cleanly reset the entire system state to a small baseline (1 VM)."""
    try:
        # Task 2: Wrap in transaction (db.session acts as one, we'll explicitly use a transaction)
        
        # Task 1 & 3: Safe bulk delete of VMs and related tables
        db.session.execute(text("DELETE FROM cost_records;"))
        db.session.execute(text("DELETE FROM audit_logs;"))
        db.session.execute(text("DELETE FROM threat_detections;"))
        db.session.execute(text("DELETE FROM security_logs;"))
        db.session.execute(text("DELETE FROM virtual_machines;"))
        db.session.execute(text("DELETE FROM databases;"))
        
        # Task 5: Create clean baseline
        # Let's find an active org to assign the new VM
        from app.models.organization import Organization
        from app.models.resources import VirtualMachine, ResourceStatus
        import random, string, datetime
        
        org = Organization.query.first()
        if org:
            suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=17))
            vm = VirtualMachine(
                organization_id=org.id,
                name=f"baseline-vm-1",
                instance_id=f"i-{suffix}",
                instance_type="t2.medium",
                status=ResourceStatus.RUNNING,
                vcpu=2,
                memory_gb=4.0,
                storage_gb=8,
                private_ip=f"10.0.1.10",
                cpu_utilization=10.0,
                memory_utilization=20.0,
                hourly_rate=0.0464,
                total_runtime_hours=0.0,
                requests_per_second=50,
                workload_pattern="steady",
                launched_at=datetime.datetime.utcnow(),
            )
            db.session.add(vm)
            
        db.session.commit()
        
        # Task 4: Reset simulator state
        sim = getattr(current_app, 'simulator', None)
        if sim:
            if hasattr(sim, '_history_by_org'):
                sim._history_by_org.clear()
            if hasattr(sim, '_activity_by_org'):
                sim._activity_by_org.clear()
            if hasattr(sim, 'org_metric_history'):
                sim.org_metric_history.clear()
            if hasattr(sim, '_vm_des'):
                sim._vm_des.clear()

        # Also clear control_plane cache
        clear_snapshot_cache()
        try:
            from app.services.control_plane import _state_store
            _state_store.clear()
        except ImportError:
            pass

        return jsonify({'status': 'success', 'message': 'System safely reset to 1 VM.'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'error': {'message': str(e)}}), 500

@admin_bp.route('/analytics/organization/<int:org_id>', methods=['GET'])
@jwt_required()
def get_org_analytics(org_id):
    """Organization-level analytics for admins to view student performance."""
    from app.models.progress import UserProgress
    from app.models.organization import OrganizationMember
    from app.models.user import User

    # Only accessible by organization admins/owners
    from flask_jwt_extended import get_jwt_identity
    user_id = get_jwt_identity()
    member = OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()
    if not member or member.role not in ['admin', 'owner']:
        return jsonify({'error': 'Access denied'}), 403

    students_progress = UserProgress.query.filter_by(org_id=org_id).all()
    
    analytics = []
    for p in students_progress:
        user = User.query.get(p.user_id)
        if not user:
            continue
        analytics.append({
            'user_id': user.id,
            'name': f"{user.first_name} {user.last_name}",
            'email': user.email,
            'level': p.level,
            'level_title': p.level_title,
            'total_points': p.total_points,
            'badges': p.badges or [],
            'scenarios_completed': len(p.scenarios_completed or []),
            'vms_created': p.vms_created,
            'attacks_simulated': p.attacks_simulated
        })

    return jsonify({
        'status': 'success',
        'data': {
            'organization_id': org_id,
            'total_students': len(analytics),
            'students': analytics
        }
    }), 200
