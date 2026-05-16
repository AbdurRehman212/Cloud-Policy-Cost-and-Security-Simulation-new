from datetime import datetime, timedelta
from flask import current_app
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db, socketio
from app.services.learning_context_engine import learning_context_service
from app.services.operational_event_service import operational_event_service
from app.models.resources import (
    VirtualMachine,
    Database,
    ResourceTag,
    ResourceStatus,
    SecurityGroup,
    SecurityGroupRule,
    VPC,
    Subnet,
)
from app.models.organization import Organization, OrganizationMember, ensure_default_organization_membership
from app.models.user import User
from app.models.governance import AuditLog
from app.config import Config
from app.utils.rbac import require_org_role
import logging
import math
import random
import string
import ipaddress

resource_bp = Blueprint('resources', __name__)
logger = logging.getLogger(__name__)

# XP point values for actions
XP_VALUES = {
    'vm_created': 10,
    'vm_deleted': 5,
    'db_created': 10,
    'db_deleted': 5,
    'attack_simulated': 15,
    'scenario_completed': 25,
    'policy_created': 10,
    'budget_created': 10,
}


def _award_xp_for_action(user_id, org_id, action):
    """Award XP and update progress for an action."""
    try:
        from app.models.progress import UserProgress

        progress = UserProgress.query.filter_by(user_id=user_id, org_id=org_id).first()
        if not progress:
            progress = UserProgress(user_id=user_id, org_id=org_id)
            db.session.add(progress)
            db.session.flush()

        points = XP_VALUES.get(action, 5)

        if action == 'vm_created':
            progress.vms_created += 1
        elif action == 'db_created':
            progress.vms_created += 1  # Count DBs as VMs for simplicity
        elif action == 'attack_simulated':
            progress.attacks_simulated += 1
        elif action == 'policy_created' or action == 'budget_created':
            progress.policies_created += 1

        progress.total_points += points
        old_level = progress.level
        progress.update_level()
        new_level = progress.level

        # Check for new badges
        new_badges = progress.check_badge_conditions()
        for badge_name in new_badges:
            if badge_name not in (progress.badges or []):
                badges = progress.badges or []
                badges.append(badge_name)
                progress.badges = badges

        db.session.commit()
        logger.info(f"[XP] user={user_id} action={action} points={points} level={old_level}->{new_level}")
    except Exception as e:
        logger.warning(f"[XP] Failed to award XP: action={action} user_id={user_id} org_id={org_id} error={e}")
        db.session.rollback()


def _record_operational_lifecycle_event(user_id, org_id, event_type, resource_type, resource_id, details):
    """Persist a lifecycle event so the learning timeline survives resource deletion."""
    operational_event_service.record_event(
        user_id=user_id,
        org_id=org_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=str(resource_id),
        details=details,
    )


# ── Instance type catalogue ────────────────────────────────────────────────────
INSTANCE_TYPES = {
    "t2.micro":  {"vcpu": 1, "memory_gb": 1,  "baseline_cpu": 0.20, "baseline_memory": 0.30, "hourly_rate": 0.0116},
    "t2.small":  {"vcpu": 1, "memory_gb": 2,  "baseline_cpu": 0.40, "baseline_memory": 0.50, "hourly_rate": 0.0230},
    "t2.medium": {"vcpu": 2, "memory_gb": 4,  "baseline_cpu": 0.60, "baseline_memory": 0.70, "hourly_rate": 0.0464},
    "t2.large":  {"vcpu": 2, "memory_gb": 8,  "baseline_cpu": 0.75, "baseline_memory": 0.80, "hourly_rate": 0.0928},
    "t2.xlarge": {"vcpu": 4, "memory_gb": 16, "baseline_cpu": 0.85, "baseline_memory": 0.90, "hourly_rate": 0.1856},
}

DB_ENGINE_RATES = {
    "PostgreSQL": 0.025,
    "MySQL":      0.020,
    "MongoDB":    0.030,
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _emit_resource_update(org_id):
    """Emit resource_update event with current org stats."""
    total_vms = VirtualMachine.query.filter_by(
        organization_id=org_id,
    ).filter(VirtualMachine.status != 'terminated').count()
    running_vms = VirtualMachine.query.filter_by(
        organization_id=org_id,
        status='running'
    ).count()
    
    running_vms_objs = VirtualMachine.query.filter_by(
        organization_id=org_id, status='running'
    ).all()
    running_dbs_objs = Database.query.filter_by(
        organization_id=org_id, status='running'
    ).all()
    all_running = running_vms_objs + running_dbs_objs
    
    if all_running:
        cpu_avg = sum(float(r.cpu_utilization or 0) for r in all_running) / len(all_running)
        memory_avg = sum(float(r.memory_utilization or 0) for r in all_running) / len(all_running)
    else:
        cpu_avg = 0.0
        memory_avg = 0.0
    
    socketio.emit(
        'resource_update',
        {
            'total_vms': total_vms,
            'running_vms': running_vms,
            'cpu_avg': round(cpu_avg, 2),
            'memory_avg': round(memory_avg, 2),
        },
        room=f'org_{org_id}',
        namespace='/metrics'
    )

def _success(data, status_code=200):
    user_id = None
    try:
        user_id = get_jwt_identity()
    except Exception:
        pass

    org_id = request.args.get('organization_id', type=int)
    role = 'system'
    if user_id:
        if not org_id:
            org_id = _resolve_org_id_for_user(user_id) or 1
        member = OrganizationMember.query.filter_by(
            organization_id=org_id, user_id=user_id
        ).first()
        if member:
            role = member.role
    else:
        org_id = org_id or 1

    return jsonify({
        'status': 'success',
        'data': data,
        'organization_id': org_id,
        'role': role,
    }), status_code


def _error(message, status_code=400, code='bad_request'):
    return jsonify({'status': 'error', 'error': {'message': message}}), status_code


def _ensure_org_membership(user_id):
    memberships = (
        OrganizationMember.query
        .filter_by(user_id=user_id)
        .order_by(OrganizationMember.joined_at.asc(), OrganizationMember.id.asc())
        .all()
    )
    if memberships:
        return {m.organization_id for m in memberships}

    return set()


def _resolve_org_id_for_user(user_id, preferred_org_id=None):
    allowed = _ensure_org_membership(user_id)
    if not allowed:
        return None
    if preferred_org_id is not None:
        try:
            preferred_org_id = int(preferred_org_id)
        except (TypeError, ValueError):
            preferred_org_id = None
    if preferred_org_id in allowed:
        return preferred_org_id
    return sorted(allowed)[0]


def _resolve_request_org_id(user_id):
    data = request.get_json(silent=True) or {}
    preferred_org_id = request.args.get(
        'organization_id',
        request.args.get('org_id', data.get('organization_id', data.get('org_id'))),
    )
    return _resolve_org_id_for_user(user_id, preferred_org_id)


def _sanitize_metric(value, fallback=0.05):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = fallback
    return round(max(0.0, min(1.0, value)), 4)


def check_org_access(user_id, org_id, min_role='member'):
    member = OrganizationMember.query.filter_by(
        organization_id=org_id, user_id=user_id
    ).first()
    if not member:
        return None
    role_hierarchy = {'viewer': 1, 'member': 2, 'admin': 3, 'owner': 4}
    if role_hierarchy.get(member.role, 0) < role_hierarchy.get(min_role, 2):
        return None
    return member


def generate_instance_id(prefix='i'):
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=17))
    return f"{prefix}-{suffix}"


def _random_private_ip():
    return f"10.0.{random.randint(0, 255)}.{random.randint(1, 254)}"


def _apply_vm_instance_type(vm: VirtualMachine, instance_type: str):
    spec = INSTANCE_TYPES.get(instance_type, INSTANCE_TYPES['t2.micro'])
    current_cost = vm.calculate_current_cost()
    vm.instance_type = instance_type
    vm.vcpu = spec['vcpu']
    vm.memory_gb = spec['memory_gb']
    vm.hourly_rate = spec['hourly_rate']
    if spec['hourly_rate'] > 0:
        vm.total_runtime_hours = current_cost / spec['hourly_rate']
    return spec


def _serialize_security_group(group: SecurityGroup, include_rules=True):
    if not group:
        return None
    return group.to_dict(include_rules=include_rules)


def _default_security_group_definitions():
    return [
        {
            'name': 'default',
            'description': 'Default security group: deny all inbound, allow all outbound.',
            'rules': [
                {
                    'direction': 'inbound',
                    'protocol': 'All',
                    'port_range': 'all',
                    'source_cidr': '0.0.0.0/0',
                    'action': 'deny',
                    'description': 'Deny all inbound traffic',
                },
                {
                    'direction': 'outbound',
                    'protocol': 'All',
                    'port_range': 'all',
                    'source_cidr': '0.0.0.0/0',
                    'action': 'allow',
                    'description': 'Allow all outbound traffic',
                },
            ],
        },
        {
            'name': 'web-server',
            'description': 'Web server access: allow HTTP and HTTPS from anywhere.',
            'rules': [
                {
                    'direction': 'inbound',
                    'protocol': 'TCP',
                    'port_range': '80',
                    'source_cidr': '0.0.0.0/0',
                    'action': 'allow',
                    'description': 'Allow HTTP traffic',
                },
                {
                    'direction': 'inbound',
                    'protocol': 'TCP',
                    'port_range': '443',
                    'source_cidr': '0.0.0.0/0',
                    'action': 'allow',
                    'description': 'Allow HTTPS traffic',
                },
                {
                    'direction': 'outbound',
                    'protocol': 'All',
                    'port_range': 'all',
                    'source_cidr': '0.0.0.0/0',
                    'action': 'allow',
                    'description': 'Allow all outbound traffic',
                },
            ],
        },
        {
            'name': 'ssh-access',
            'description': 'SSH access for admin operations.',
            'rules': [
                {
                    'direction': 'inbound',
                    'protocol': 'TCP',
                    'port_range': '22',
                    'source_cidr': '0.0.0.0/0',
                    'action': 'allow',
                    'description': 'Allow SSH access',
                },
                {
                    'direction': 'outbound',
                    'protocol': 'All',
                    'port_range': 'all',
                    'source_cidr': '0.0.0.0/0',
                    'action': 'allow',
                    'description': 'Allow all outbound traffic',
                },
            ],
        },
        {
            'name': 'database',
            'description': 'Database access from private VPC ranges only.',
            'rules': [
                {
                    'direction': 'inbound',
                    'protocol': 'TCP',
                    'port_range': '5432',
                    'source_cidr': '10.0.0.0/8',
                    'action': 'allow',
                    'description': 'Allow PostgreSQL access from private network',
                },
                {
                    'direction': 'inbound',
                    'protocol': 'TCP',
                    'port_range': '3306',
                    'source_cidr': '10.0.0.0/8',
                    'action': 'allow',
                    'description': 'Allow MySQL access from private network',
                },
                {
                    'direction': 'outbound',
                    'protocol': 'All',
                    'port_range': 'all',
                    'source_cidr': '0.0.0.0/0',
                    'action': 'allow',
                    'description': 'Allow all outbound traffic',
                },
            ],
        },
    ]


def _ensure_default_security_groups(org_id):
    created = False
    groups = []
    for group_spec in _default_security_group_definitions():
        group = SecurityGroup.query.filter_by(org_id=org_id, name=group_spec['name']).first()
        if not group:
            group = SecurityGroup(
                org_id=org_id,
                name=group_spec['name'],
                description=group_spec['description'],
            )
            db.session.add(group)
            db.session.flush()
            for rule_spec in group_spec['rules']:
                db.session.add(SecurityGroupRule(group_id=group.id, **rule_spec))
            created = True
        groups.append(group)
    if created:
        db.session.flush()
    return groups


def _security_group_query_for_org(org_id):
    _ensure_default_security_groups(org_id)
    return SecurityGroup.query.filter_by(org_id=org_id)


def _parse_security_group_ids(payload):
    raw_ids = payload.get('security_group_ids')
    if raw_ids is None:
        raw_ids = payload.get('security_groups')
    if raw_ids is None:
        return []
    if isinstance(raw_ids, (int, str)):
        raw_ids = [raw_ids]
    ids = []
    for value in raw_ids:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def _attach_security_groups_to_vm(vm, security_group_ids):
    if not security_group_ids:
        default_group = SecurityGroup.query.filter_by(org_id=vm.organization_id, name='default').first()
        security_group_ids = [default_group.id] if default_group else []

    groups = []
    for group_id in security_group_ids:
        group = SecurityGroup.query.filter_by(id=group_id, org_id=vm.organization_id).first()
        if not group:
            return None, f'Security group {group_id} not found for this organization'
        groups.append(group)

    if groups:
        vm.security_groups = groups
    return groups, None


def _vm_to_envelope(vm: VirtualMachine) -> dict:
    """Convert a VirtualMachine ORM row to the frontend-expected envelope."""
    # cpu_utilization is stored as 0-100 float; use 'is not None' so 0.0 is not treated as missing
    cpu_norm = _sanitize_metric(float(vm.cpu_utilization) if vm.cpu_utilization is not None else 2.0)
    mem_norm = _sanitize_metric(float(vm.memory_utilization) if vm.memory_utilization is not None else 3.0)
    spec = INSTANCE_TYPES.get(vm.instance_type, {})
    base_cpu = _sanitize_metric(spec.get('baseline_cpu', cpu_norm))
    base_mem = _sanitize_metric(spec.get('baseline_memory', mem_norm))
    return {
        'id': vm.id,
        'name': vm.name,
        'type': 'vm',
        'instance_type': vm.instance_type,
        'engine': None,
        'cpu': cpu_norm,
        'memory': mem_norm,
        'cpu_percent': round(float(vm.cpu_utilization or 0), 1),
        'memory_percent': round(float(vm.memory_utilization or 0), 1),
        'status': vm.status.value if vm.status else 'stopped',
        'base_cpu': base_cpu,
        'base_memory': base_mem,
        'seed': vm.id * 1000 + 7,
        'org_id': vm.organization_id,
        'organization_id': vm.organization_id,
        'region': 'us-east-1',
        'private_ip': vm.private_ip,
        'vcpu': vm.vcpu,
        'memory_gb': vm.memory_gb,
        'hourly_rate': vm.hourly_rate,
        'current_cost': round(vm.calculate_current_cost(), 4),
        'created_at': vm.created_at.isoformat() if vm.created_at else None,
        'launched_at': vm.launched_at.isoformat() if vm.launched_at else None,
        'last_updated': datetime.utcnow().isoformat(),
        'security_groups': [_serialize_security_group(group, include_rules=False) for group in vm.security_groups],
    }


def _db_to_envelope(database: Database) -> dict:
    """Convert a Database ORM row to the frontend-expected envelope."""
    # cpu_utilization is stored as 0-100 float; send as-is (no /100 division)
    cpu_norm = _sanitize_metric(float(database.cpu_utilization) if database.cpu_utilization else 2.0)
    mem_raw = min(100.0, max(0.0, (database.cpu_utilization or 0) * 1.35 + (database.database_connections or 0) * 0.65))
    mem_norm = _sanitize_metric(mem_raw)
    return {
        'id': database.id,
        'name': database.name,
        'type': 'database',
        'instance_type': database.instance_class,
        'engine': database.engine,
        'cpu': cpu_norm,
        'memory': mem_norm,
        'cpu_percent': round(float(database.cpu_utilization or 0), 1),
        'memory_percent': round(float(mem_raw), 1),
        'status': database.status.value if database.status else 'stopped',
        'base_cpu': cpu_norm,
        'base_memory': mem_norm,
        'seed': database.id * 1000 + 13,
        'org_id': database.organization_id,
        'organization_id': database.organization_id,
        'region': 'us-east-1',
        'hourly_rate': database.hourly_rate,
        'current_cost': round(database.total_runtime_hours * database.hourly_rate, 4),
        'created_at': database.created_at.isoformat() if database.created_at else None,
        'last_updated': datetime.utcnow().isoformat(),
    }


# ── Provisioning helpers ───────────────────────────────────────────────────────

def _complete_vm_creation(vm_id: int, app):
    """Transition VM from PENDING → RUNNING after a fixed provisioning window.

    Also registers the VM in the VMRegistry so metric computation
    and deletion guards work correctly from the first tick.
    """
    with app.app_context():
        # Fixed delay for determinism in system-wide validation
        socketio.sleep(2.5)
        vm = VirtualMachine.query.get(vm_id)
        if vm and vm.status == ResourceStatus.PENDING:
            spec = INSTANCE_TYPES.get(vm.instance_type, {})
            vm.status = ResourceStatus.RUNNING
            vm.launched_at = datetime.utcnow()
            vm.cpu_utilization = round(spec.get('baseline_cpu', 0.2) * 100, 2)
            vm.memory_utilization = round(spec.get('baseline_memory', 0.3) * 100, 2)
            db.session.commit()

            envelope = _vm_to_envelope(vm)
            socketio.emit(
                'vm_created',
                envelope,
                room=f'org_{vm.organization_id}',
                namespace='/metrics',
            )


def _complete_db_creation(db_id: int, app):
    """Transition Database from PENDING → RUNNING after a fixed provisioning window."""
    with app.app_context():
        # Fixed delay for determinism
        socketio.sleep(2.5)
        database = Database.query.get(db_id)
        if database and database.status == ResourceStatus.PENDING:
            database.cpu_utilization = 5.0
            database.status = ResourceStatus.RUNNING
            db.session.commit()
            envelope = _db_to_envelope(database)
            socketio.emit(
                'vm_created',
                envelope,
                room=f'org_{database.organization_id}',
                namespace='/metrics',
            )
            _emit_resource_update(database.organization_id)


def _provision_vm_record(org_id, data):
    """Create a VM row and schedule its provisioning transition."""
    from app.models.organization import Organization
    active_vms = VirtualMachine.query.filter(
        VirtualMachine.organization_id == org_id,
        VirtualMachine.status != ResourceStatus.TERMINATED,
    ).count()
    active_dbs = Database.query.filter(
        Database.organization_id == org_id,
        Database.status != ResourceStatus.TERMINATED,
    ).count()
    org = Organization.query.get(org_id)
    resource_limit = int(getattr(org, 'max_resources', 50) or 50)
    if active_vms + active_dbs >= resource_limit:
        return None, _error(f'Quota exceeded: maximum {resource_limit} resources per organization', status_code=400)

    instance_type = data.get('instance_type', 't2.micro')
    spec = INSTANCE_TYPES.get(instance_type, INSTANCE_TYPES['t2.micro'])
    name = (data.get('name') or '').strip() or f"VM-{generate_instance_id('i')[:8]}"
    _ensure_default_security_groups(org_id)

    vm = VirtualMachine(
        organization_id=org_id,
        name=name,
        instance_id=generate_instance_id('i'),
        instance_type=instance_type,
        status=ResourceStatus.PENDING,
        vcpu=spec['vcpu'],
        memory_gb=spec['memory_gb'],
        storage_gb=data.get('storage_gb', 8),
        private_ip=_random_private_ip(),
        cpu_utilization=spec['baseline_cpu'] * 100,
        memory_utilization=spec['baseline_memory'] * 100,
        hourly_rate=spec['hourly_rate'],
        total_runtime_hours=0.0,
        requests_per_second=data.get('requests_per_second', random.randint(10, 100)),
        workload_pattern=data.get('workload_pattern', random.choice(['steady', 'spiky', 'diurnal'])),
    )
    db.session.add(vm)
    db.session.flush()
    group_ids = _parse_security_group_ids(data)
    groups, error = _attach_security_groups_to_vm(vm, group_ids)
    if error:
        db.session.rollback()
        return None, _error(error, status_code=400)
    db.session.commit()
    socketio.start_background_task(_complete_vm_creation, vm.id, current_app._get_current_object())
    return vm, None


def _provision_database_record(org_id, data):
    """Create a Database row and schedule its provisioning transition."""
    from app.models.organization import Organization
    active_vms = VirtualMachine.query.filter(
        VirtualMachine.organization_id == org_id,
        VirtualMachine.status != ResourceStatus.TERMINATED,
    ).count()
    active_dbs = Database.query.filter(
        Database.organization_id == org_id,
        Database.status != ResourceStatus.TERMINATED,
    ).count()
    org = Organization.query.get(org_id)
    resource_limit = int(getattr(org, 'max_resources', 50) or 50)
    if active_vms + active_dbs >= resource_limit:
        return None, _error(f'Quota exceeded: maximum {resource_limit} resources per organization', status_code=400)

    engine = data.get('engine', 'PostgreSQL')
    name = (data.get('name') or '').strip() or f"DB-{generate_instance_id('db')[:8]}"
    hourly_rate = DB_ENGINE_RATES.get(engine, 0.025)

    database = Database(
        organization_id=org_id,
        name=name,
        instance_id=generate_instance_id('db'),
        engine=engine,
        engine_version='14.0',
        instance_class=data.get('instance_class', 'db.t2.micro'),
        status=ResourceStatus.PENDING,
        allocated_storage_gb=data.get('storage_gb', 20),
        cpu_utilization=5.0,
        database_connections=0,
        hourly_rate=hourly_rate,
        total_runtime_hours=0.0,
    )
    db.session.add(database)
    db.session.commit()
    socketio.start_background_task(_complete_db_creation, database.id, current_app._get_current_object())
    return database, None


# ── Routes ─────────────────────────────────────────────────────────────────────

@resource_bp.route('/vpcs', methods=['GET'])
@jwt_required()
def list_vpcs():
    """List VPCs with nested subnets for the org."""
    user_id = get_jwt_identity()
    org_id = _resolve_org_id_for_user(user_id, request.args.get('organization_id', type=int))
    if org_id is None:
        return _success([])
    if not check_org_access(user_id, org_id, 'viewer'):
        return _error('Access denied', status_code=403)
    vpcs = VPC.query.filter_by(organization_id=org_id).all()
    return _success([v.to_dict(include_subnets=True) for v in vpcs])


@resource_bp.route('/network/topology', methods=['GET'])
@jwt_required()
def network_topology():
    """Return full VPC → Subnet → VM/DB map for the org."""
    user_id = get_jwt_identity()
    org_id = _resolve_org_id_for_user(user_id, request.args.get('organization_id', type=int))
    if org_id is None:
        return _success({'vpcs': []})
    if not check_org_access(user_id, org_id, 'viewer'):
        return _error('Access denied', status_code=403)

    vpcs = VPC.query.filter_by(organization_id=org_id).all()
    vms = VirtualMachine.query.filter(
        VirtualMachine.organization_id == org_id,
        VirtualMachine.status != ResourceStatus.TERMINATED,
    ).all()
    databases = Database.query.filter(
        Database.organization_id == org_id,
        Database.status != ResourceStatus.TERMINATED,
    ).all()

    result = []
    for vpc in vpcs:
        vpc_data = vpc.to_dict(include_subnets=False)
        vpc_data['subnets'] = []
        for subnet in vpc.subnets:
            subnet_data = subnet.to_dict()
            subnet_data['vms'] = [
                {'id': vm.id, 'name': vm.name, 'ip': vm.private_ip, 'status': vm.status.value if vm.status else None}
                for vm in vms if str(vm.subnet_id) == str(subnet.id)
            ]
            subnet_data['databases'] = [
                {'id': db_obj.id, 'name': db_obj.name, 'status': db_obj.status.value if db_obj.status else None}
                for db_obj in databases
            ]
            vpc_data['subnets'].append(subnet_data)
        result.append(vpc_data)

    return _success({'vpcs': result})


@resource_bp.route('', methods=['GET'])
@jwt_required()
def list_resources():
    """Return all VMs and databases for the user's org."""
    user_id = get_jwt_identity()
    org_id_filter = request.args.get('organization_id', type=int)
    org_id = _resolve_org_id_for_user(user_id, org_id_filter)
    if org_id is None:
        return _success([])

    vms = VirtualMachine.query.filter(
        VirtualMachine.organization_id == org_id,
        VirtualMachine.status != ResourceStatus.TERMINATED,
    ).all()
    databases = Database.query.filter(
        Database.organization_id == org_id,
        Database.status != ResourceStatus.TERMINATED,
    ).all()

    result = [_vm_to_envelope(vm) for vm in vms] + [_db_to_envelope(d) for d in databases]
    return _success(result)


@resource_bp.route('/create', methods=['POST'])
@jwt_required()
@require_org_role('member')
def create_resource():
    """Create a VM or database, persisted to the database."""
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    resource_type = (request.args.get('type') or data.get('type') or 'vm').strip().lower()
    if resource_type in {'db', 'database'}:
        resource_type = 'database'
    else:
        resource_type = 'vm'

    org_id = _resolve_org_id_for_user(user_id, data.get('org_id', data.get('organization_id')))
    if org_id is None:
        org_id = 1
    if not check_org_access(user_id, org_id, 'member'):
        return _error('Permission denied', status_code=403)

    if resource_type == 'vm':
        instance_type = data.get('instance_type', 't2.micro')
        vm, error = _provision_vm_record(org_id, data)
        if error:
            return error
        _emit_resource_update(org_id)

        # Award XP for VM creation
        _award_xp_for_action(user_id, org_id, 'vm_created')

        # Record persistent operational event
        operational_event_service.record_event(
            user_id=user_id,
            org_id=org_id,
            event_type='vm_created',
            resource_type='vm',
            resource_id=str(vm.id),
            details={
                'instance_type': instance_type,
                'name': vm.name,
                'hourly_rate': float(vm.hourly_rate or 0),
            }
        )

        # Generate learning context
        total_vms = VirtualMachine.query.filter_by(
            organization_id=org_id, status=ResourceStatus.RUNNING
        ).count()
        learning_context = learning_context_service.for_vm_created(
            instance_type, vm.name,
            current_cost=float(vm.hourly_rate or 0),
            total_vms=total_vms
        )

        response_data = _vm_to_envelope(vm)
        response_data['learning_context'] = {
            'title': learning_context.title,
            'summary': learning_context.summary,
            'cloud_equivalent': learning_context.cloud_equivalent,
            'azure_equivalent': learning_context.azure_equivalent,
            'cost_impact': learning_context.cost_impact,
            'operational_meaning': learning_context.operational_meaning,
            'optimization_insight': learning_context.optimization_insight,
            'learning_explanation': learning_context.learning_explanation,
            'severity': learning_context.severity,
        }
        return _success(response_data, status_code=201)

    else:
        database, error = _provision_database_record(org_id, data)
        if error:
            return error

        # Award XP for database creation
        _award_xp_for_action(user_id, org_id, 'db_created')
        _record_operational_lifecycle_event(
            user_id=user_id,
            org_id=org_id,
            event_type='db_created',
            resource_type='database',
            resource_id=database.id,
            details={
                'engine': database.engine,
                'name': database.name,
                'hourly_rate': float(database.hourly_rate or 0),
            },
        )
        _emit_resource_update(org_id)
        return _success(_db_to_envelope(database), status_code=201)


@resource_bp.route('/security-groups', methods=['GET'])
@jwt_required()
def list_security_groups():
    """List security groups for an organization."""
    user_id = get_jwt_identity()
    org_id = request.args.get('organization_id', type=int)
    if org_id is None:
        org_id = _resolve_org_id_for_user(user_id) or 1
    if not check_org_access(user_id, org_id, 'viewer'):
        return _error('Access denied', status_code=403, code='forbidden')

    groups = _security_group_query_for_org(org_id).order_by(SecurityGroup.created_at.asc(), SecurityGroup.id.asc()).all()
    return _success([group.to_dict(include_rules=True) for group in groups])


@resource_bp.route('/security-groups', methods=['POST'])
@jwt_required()
@require_org_role('admin')
def create_security_group():
    """Create a new security group for an organization."""
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    org_id = (
        data.get('organization_id')
        or data.get('org_id')
        or request.args.get('organization_id', type=int)
        or request.args.get('org_id', type=int)
    )
    if org_id is None:
        org_id = _resolve_org_id_for_user(user_id) or 1
    if not check_org_access(user_id, org_id, 'member'):
        return _error('Access denied', status_code=403, code='forbidden')

    _ensure_default_security_groups(org_id)
    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip()
    if not name:
        return _error('Security group name required', status_code=400)
    if SecurityGroup.query.filter_by(org_id=org_id, name=name).first():
        return _error('Security group already exists', status_code=409, code='conflict')

    group = SecurityGroup(org_id=org_id, name=name, description=description)
    db.session.add(group)
    db.session.commit()
    return _success(group.to_dict(include_rules=True), status_code=201)


@resource_bp.route('/security-groups/<int:group_id>/rules', methods=['POST'])
@jwt_required()
def add_security_group_rule(group_id):
    """Add a rule to a security group."""
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    group = SecurityGroup.query.get(group_id)
    if not group:
        return _error('Security group not found', status_code=404, code='not_found')
    if not check_org_access(user_id, group.org_id, 'member'):
        return _error('Access denied', status_code=403, code='forbidden')

    direction = (data.get('direction') or '').strip().lower()
    protocol = (data.get('protocol') or '').strip().upper()
    action = (data.get('action') or '').strip().lower()
    port_range = (data.get('port_range') or '').strip()
    source_cidr = (data.get('source_cidr') or '').strip()
    description = (data.get('description') or '').strip()

    if direction not in {'inbound', 'outbound'}:
        return _error('direction must be inbound or outbound', status_code=400)
    if protocol not in {'TCP', 'UDP', 'ICMP', 'ALL'}:
        return _error('protocol must be TCP, UDP, ICMP, or All', status_code=400)
    if action not in {'allow', 'deny'}:
        return _error('action must be allow or deny', status_code=400)
    if not port_range:
        return _error('port_range required', status_code=400)
    if not source_cidr:
        return _error('source_cidr required', status_code=400)

    rule = SecurityGroupRule(
        group_id=group.id,
        direction=direction,
        protocol='All' if protocol == 'ALL' else protocol,
        port_range=port_range,
        source_cidr=source_cidr,
        action=action,
        description=description,
    )
    db.session.add(rule)
    db.session.commit()
    return _success(rule.to_dict(), status_code=201)


@resource_bp.route('/security-groups/<int:group_id>/rules/<int:rule_id>', methods=['PUT'])
@jwt_required()
def update_security_group_rule(group_id, rule_id):
    """Update a security group rule."""
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    group = SecurityGroup.query.get(group_id)
    if not group:
        return _error('Security group not found', status_code=404, code='not_found')
    if not check_org_access(user_id, group.org_id, 'member'):
        return _error('Access denied', status_code=403, code='forbidden')

    rule = SecurityGroupRule.query.filter_by(id=rule_id, group_id=group_id).first()
    if not rule:
        return _error('Rule not found', status_code=404, code='not_found')

    direction = (data.get('direction') or rule.direction).strip().lower()
    protocol = (data.get('protocol') or rule.protocol).strip().upper()
    action = (data.get('action') or rule.action).strip().lower()
    port_range = (data.get('port_range') or rule.port_range).strip()
    source_cidr = (data.get('source_cidr') or rule.source_cidr).strip()
    description = (data.get('description') if data.get('description') is not None else rule.description) or ''

    if direction not in {'inbound', 'outbound'}:
        return _error('direction must be inbound or outbound', status_code=400)
    if protocol not in {'TCP', 'UDP', 'ICMP', 'ALL'}:
        return _error('protocol must be TCP, UDP, ICMP, or All', status_code=400)
    if action not in {'allow', 'deny'}:
        return _error('action must be allow or deny', status_code=400)
    if not port_range:
        return _error('port_range required', status_code=400)
    if not source_cidr:
        return _error('source_cidr required', status_code=400)

    rule.direction = direction
    rule.protocol = 'All' if protocol == 'ALL' else protocol
    rule.port_range = port_range
    rule.source_cidr = source_cidr
    rule.action = action
    rule.description = description
    db.session.commit()
    return _success(rule.to_dict())


@resource_bp.route('/security-groups/<int:group_id>/rules/<int:rule_id>', methods=['DELETE'])
@jwt_required()
def delete_security_group_rule(group_id, rule_id):
    """Delete a rule from a security group."""
    user_id = get_jwt_identity()
    group = SecurityGroup.query.get(group_id)
    if not group:
        return _error('Security group not found', status_code=404, code='not_found')
    if not check_org_access(user_id, group.org_id, 'member'):
        return _error('Access denied', status_code=403, code='forbidden')

    rule = SecurityGroupRule.query.filter_by(id=rule_id, group_id=group_id).first()
    if not rule:
        return _error('Rule not found', status_code=404, code='not_found')

    db.session.delete(rule)
    db.session.commit()
    return _success({'message': 'Rule deleted'})


@resource_bp.route('/vm/<int:resource_id>/security-groups', methods=['PUT'])
@resource_bp.route('/vms/<int:resource_id>/security-groups', methods=['PUT'])
@jwt_required()
def attach_security_groups_to_vm(resource_id):
    """Attach one or more security groups to a VM."""
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    vm = VirtualMachine.query.filter(
        VirtualMachine.id == resource_id,
        VirtualMachine.status != ResourceStatus.TERMINATED,
    ).first()
    if not vm:
        return _error('VM not found', status_code=404, code='not_found')
    if not check_org_access(user_id, vm.organization_id, 'member'):
        return _error('Access denied', status_code=403, code='forbidden')

    _ensure_default_security_groups(vm.organization_id)
    group_ids = _parse_security_group_ids(data)
    groups, error = _attach_security_groups_to_vm(vm, group_ids)
    if error:
        return _error(error, status_code=400)

    db.session.commit()
    return _success(_vm_to_envelope(vm))


@resource_bp.route('/<int:resource_id>', methods=['DELETE'])
@jwt_required()
@require_org_role('member')
def delete_resource(resource_id):
    """Terminate (soft-delete) a resource.

    VM lifecycle rule: A VM in PROVISIONING (PENDING) state CANNOT be deleted.
    On successful deletion:
      - metrics are zeroed
      - cost is frozen at its current value
      - registry entry is removed (no orphan VMs)
    """
    user_id = get_jwt_identity()
    org_id = _resolve_request_org_id(user_id)
    if org_id is None:
        return _error('organization_id required', status_code=400)

    vm = VirtualMachine.query.filter(
        VirtualMachine.id == resource_id,
        VirtualMachine.organization_id == org_id,
        VirtualMachine.status != ResourceStatus.TERMINATED,
    ).first()
    if vm:
        if not check_org_access(user_id, vm.organization_id, 'admin'):
            return _error('Permission denied', status_code=403)

        # ── Lifecycle guard: PENDING VMs cannot be deleted ─────────────────────
        if vm.status == ResourceStatus.PENDING:
            logger.warning(
                "[delete_resource] Blocked deletion of PROVISIONING VM vm_id=%s org=%d",
                vm.instance_id, vm.organization_id,
            )
            return _error(
                'Cannot delete a VM that is still provisioning. Wait for it to reach running state.',
                status_code=409,
                code='vm_provisioning',
            )

        # ── Zero metrics (no orphan metric state) ──────────────────────────────
        final_cost = vm.calculate_current_cost()
        vm.cpu_utilization = 0.0
        vm.memory_utilization = 0.0
        vm.disk_read_iops = 0.0
        vm.disk_write_iops = 0.0
        vm.network_in_mbps = 0.0
        vm.network_out_mbps = 0.0
        vm.status = ResourceStatus.TERMINATED
        vm.terminated_at = datetime.utcnow()
        db.session.commit()

        # Award XP for VM deletion
        _award_xp_for_action(user_id, vm.organization_id, 'vm_deleted')
        _record_operational_lifecycle_event(
            user_id=user_id,
            org_id=vm.organization_id,
            event_type='vm_deleted',
            resource_type='vm',
            resource_id=vm.id,
            details={
                'instance_id': vm.instance_id,
                'name': vm.name,
                'final_cost': round(final_cost, 4),
                'status': 'terminated',
            },
        )

        # ── Update resource-count metric ────────────────────────────────────
        remaining = VirtualMachine.query.filter_by(
            organization_id=vm.organization_id, status=ResourceStatus.RUNNING
        ).count()
        logger.info(
            "[delete_resource] VM DELETED vm_id=%s org=%d final_cost=%.4f remaining_running=%d",
            vm.instance_id, vm.organization_id, final_cost, remaining,
        )
        socketio.emit(
            'vm_deleted',
            {
                'id': vm.id,
                'instance_id': vm.instance_id,
                'org_id': vm.organization_id,
                'organization_id': vm.organization_id,
            },
            room=f'org_{vm.organization_id}',
            namespace='/metrics',
        )
        _emit_resource_update(vm.organization_id)
        return _success(_vm_to_envelope(vm))

    database = Database.query.filter(
        Database.id == resource_id,
        Database.organization_id == org_id,
        Database.status != ResourceStatus.TERMINATED,
    ).first()
    if database:
        if not check_org_access(user_id, database.organization_id, 'admin'):
            return _error('Permission denied', status_code=403)
        database.status = ResourceStatus.TERMINATED
        db.session.commit()
        _award_xp_for_action(user_id, database.organization_id, 'db_deleted')
        _record_operational_lifecycle_event(
            user_id=user_id,
            org_id=database.organization_id,
            event_type='db_deleted',
            resource_type='database',
            resource_id=database.id,
            details={
                'instance_id': database.instance_id,
                'name': database.name,
                'engine': database.engine,
                'status': 'terminated',
            },
        )
        socketio.emit(
            'vm_deleted',
            {
                'id': database.id,
                'instance_id': database.instance_id,
                'org_id': database.organization_id,
                'organization_id': database.organization_id,
            },
            room=f'org_{database.organization_id}',
            namespace='/metrics',
        )
        _emit_resource_update(database.organization_id)
        return _success(_db_to_envelope(database))

    return _error('Resource not found.', status_code=404, code='not_found')


@resource_bp.route('/<int:resource_id>/stop', methods=['POST'])
@jwt_required()
@require_org_role('member')
def stop_resource(resource_id):
    """Stop a running resource."""
    user_id = get_jwt_identity()
    org_id = _resolve_request_org_id(user_id)
    if org_id is None:
        return _error('organization_id required', status_code=400)

    vm = VirtualMachine.query.filter(
        VirtualMachine.id == resource_id,
        VirtualMachine.organization_id == org_id,
        VirtualMachine.status != ResourceStatus.TERMINATED,
    ).first()
    if vm:
        if not check_org_access(user_id, vm.organization_id, 'member'):
            return _error('Permission denied', status_code=403)
        vm.status = ResourceStatus.STOPPED
        vm.stopped_at = datetime.utcnow()
        vm.cpu_utilization = round(vm.cpu_utilization * 0.05, 2)
        vm.memory_utilization = round(vm.memory_utilization * 0.05, 2)
        db.session.commit()
        _record_operational_lifecycle_event(
            user_id=user_id,
            org_id=vm.organization_id,
            event_type='vm_stopped',
            resource_type='vm',
            resource_id=vm.id,
            details={
                'instance_id': vm.instance_id,
                'name': vm.name,
                'status': 'stopped',
            },
        )
        socketio.emit(
            'vm_updated',
            _vm_to_envelope(vm),
            room=f'org_{vm.organization_id}',
            namespace='/metrics',
        )
        _emit_resource_update(vm.organization_id)
        return _success(_vm_to_envelope(vm))

    database = Database.query.filter(
        Database.id == resource_id,
        Database.organization_id == org_id,
        Database.status != ResourceStatus.TERMINATED,
    ).first()
    if database:
        if not check_org_access(user_id, database.organization_id, 'member'):
            return _error('Permission denied', status_code=403)
        database.status = ResourceStatus.STOPPED
        database.cpu_utilization = 0.0
        database.database_connections = 0
        db.session.commit()
        _record_operational_lifecycle_event(
            user_id=user_id,
            org_id=database.organization_id,
            event_type='db_stopped',
            resource_type='database',
            resource_id=database.id,
            details={
                'instance_id': database.instance_id,
                'name': database.name,
                'engine': database.engine,
                'status': 'stopped',
            },
        )
        socketio.emit(
            'vm_updated',
            _db_to_envelope(database),
            room=f'org_{database.organization_id}',
            namespace='/metrics',
        )
        return _success(_db_to_envelope(database))

    return _error('Resource not found.', status_code=404, code='not_found')


@resource_bp.route('/<int:resource_id>/start', methods=['POST'])
@jwt_required()
@require_org_role('member')
def start_resource(resource_id):
    """Start a stopped resource."""
    user_id = get_jwt_identity()
    org_id = _resolve_request_org_id(user_id)
    if org_id is None:
        return _error('organization_id required', status_code=400)

    vm = VirtualMachine.query.filter(
        VirtualMachine.id == resource_id,
        VirtualMachine.organization_id == org_id,
        VirtualMachine.status == ResourceStatus.STOPPED,
    ).first()
    if vm:
        if not check_org_access(user_id, vm.organization_id, 'member'):
            return _error('Permission denied', status_code=403)
        vm.status = ResourceStatus.RUNNING
        vm.launched_at = datetime.utcnow()
        spec = INSTANCE_TYPES.get(vm.instance_type, {})
        vm.cpu_utilization = spec.get('baseline_cpu', 0.2) * 100
        vm.memory_utilization = spec.get('baseline_memory', 0.3) * 100
        db.session.commit()
        _record_operational_lifecycle_event(
            user_id=user_id,
            org_id=vm.organization_id,
            event_type='vm_started',
            resource_type='vm',
            resource_id=vm.id,
            details={
                'instance_id': vm.instance_id,
                'name': vm.name,
                'status': 'running',
            },
        )
        socketio.emit(
            'vm_updated',
            _vm_to_envelope(vm),
            room=f'org_{vm.organization_id}',
            namespace='/metrics',
        )
        _emit_resource_update(vm.organization_id)
        return _success(_vm_to_envelope(vm))

    database = Database.query.filter(
        Database.id == resource_id,
        Database.organization_id == org_id,
        Database.status == ResourceStatus.STOPPED,
    ).first()
    if database:
        if not check_org_access(user_id, database.organization_id, 'member'):
            return _error('Permission denied', status_code=403)
        database.status = ResourceStatus.RUNNING
        database.cpu_utilization = 5.0
        db.session.commit()
        _record_operational_lifecycle_event(
            user_id=user_id,
            org_id=database.organization_id,
            event_type='db_started',
            resource_type='database',
            resource_id=database.id,
            details={
                'instance_id': database.instance_id,
                'name': database.name,
                'engine': database.engine,
                'status': 'running',
            },
        )
        socketio.emit(
            'vm_updated',
            _db_to_envelope(database),
            room=f'org_{database.organization_id}',
            namespace='/metrics',
        )
        return _success(_db_to_envelope(database))

    return _error('Resource not found or not in stopped state.', status_code=404, code='not_found')


@resource_bp.route('/<int:resource_id>/restart', methods=['POST'])
@jwt_required()
@require_org_role('member')
def restart_resource(resource_id):
    """Restart a running resource (brief PENDING → RUNNING transition)."""
    user_id = get_jwt_identity()
    org_id = _resolve_request_org_id(user_id)
    if org_id is None:
        return _error('organization_id required', status_code=400)

    vm = VirtualMachine.query.filter(
        VirtualMachine.id == resource_id,
        VirtualMachine.organization_id == org_id,
        VirtualMachine.status.in_([ResourceStatus.RUNNING, ResourceStatus.STOPPED]),
    ).first()
    if vm:
        if not check_org_access(user_id, vm.organization_id, 'member'):
            return _error('Permission denied', status_code=403)
        vm.status = ResourceStatus.PENDING
        vm.cpu_utilization = 1.0
        vm.memory_utilization = 1.0
        db.session.commit()
        _record_operational_lifecycle_event(
            user_id=user_id,
            org_id=vm.organization_id,
            event_type='vm_restarted',
            resource_type='vm',
            resource_id=vm.id,
            details={
                'instance_id': vm.instance_id,
                'name': vm.name,
                'status': 'pending',
            },
        )
        socketio.emit(
            'vm_updated',
            _vm_to_envelope(vm),
            room=f'org_{vm.organization_id}',
            namespace='/metrics',
        )
        socketio.start_background_task(_complete_vm_creation, vm.id, current_app._get_current_object())
        return _success(_vm_to_envelope(vm))

    database = Database.query.filter(
        Database.id == resource_id,
        Database.organization_id == org_id,
        Database.status.in_([ResourceStatus.RUNNING, ResourceStatus.STOPPED]),
    ).first()
    if database:
        if not check_org_access(user_id, database.organization_id, 'member'):
            return _error('Permission denied', status_code=403)
        database.status = ResourceStatus.PENDING
        database.cpu_utilization = 0.0
        db.session.commit()
        _record_operational_lifecycle_event(
            user_id=user_id,
            org_id=database.organization_id,
            event_type='db_restarted',
            resource_type='database',
            resource_id=database.id,
            details={
                'instance_id': database.instance_id,
                'name': database.name,
                'engine': database.engine,
                'status': 'pending',
            },
        )
        socketio.emit(
            'vm_updated',
            _db_to_envelope(database),
            room=f'org_{database.organization_id}',
            namespace='/metrics',
        )
        socketio.start_background_task(_complete_db_creation, database.id, current_app._get_current_object())
        return _success(_db_to_envelope(database))

    return _error('Resource not found.', status_code=404, code='not_found')


# ── VM-specific routes ─────────────────────────────────────────────────────────

@resource_bp.route('/vm', methods=['POST'])
@resource_bp.route('/vms', methods=['POST'])
@jwt_required()
def create_vm():
    """Create virtual machine (delegates to create_resource)."""
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    org_id = _resolve_org_id_for_user(user_id, data.get('organization_id', data.get('org_id')))
    if org_id is None:
        return _error('organization_id required', status_code=400)
    if not check_org_access(user_id, org_id, 'member'):
        return _error('Permission denied', status_code=403)

    vm, error = _provision_vm_record(org_id, data)
    if error:
        return error
    _award_xp_for_action(user_id, org_id, 'vm_created')
    _record_operational_lifecycle_event(
        user_id=user_id,
        org_id=org_id,
        event_type='vm_created',
        resource_type='vm',
        resource_id=vm.id,
        details={
            'instance_type': vm.instance_type,
            'name': vm.name,
            'hourly_rate': float(vm.hourly_rate or 0),
        },
    )
    _emit_resource_update(org_id)
    return _success(_vm_to_envelope(vm), status_code=201)


@resource_bp.route('/vm', methods=['GET'])
@resource_bp.route('/vms', methods=['GET'])
@jwt_required()
def list_vms():
    """List virtual machines."""
    user_id = get_jwt_identity()
    org_id = request.args.get('org_id', type=int) or request.args.get('organization_id', type=int)
    if org_id is None:
        org_id = _resolve_org_id_for_user(user_id) or 1
    if not check_org_access(user_id, org_id, 'viewer'):
        return _error('Access denied', status_code=403, code='forbidden')

    vms = VirtualMachine.query.filter(
        VirtualMachine.organization_id == org_id,
        VirtualMachine.status != ResourceStatus.TERMINATED,
    ).all()
    return _success([_vm_to_envelope(vm) for vm in vms])


@resource_bp.route('/cleanup-pending', methods=['POST'])
@jwt_required()
def cleanup_pending_vms():
    """Terminate stale pending VMs so they disappear from resource lists."""
    user_id = get_jwt_identity()
    org_id_filter = request.args.get('organization_id', type=int)

    if org_id_filter is not None:
        if not check_org_access(user_id, org_id_filter, 'member'):
            return _error('Permission denied', status_code=403)
        org_ids = [org_id_filter]
    else:
        org_ids = sorted(_ensure_org_membership(user_id))
        if not org_ids:
            return _error('Permission denied', status_code=403)

    cutoff = datetime.utcnow() - timedelta(minutes=10)
    stale_vms = VirtualMachine.query.filter(
        VirtualMachine.organization_id.in_(org_ids),
        VirtualMachine.status == ResourceStatus.PENDING,
        VirtualMachine.created_at < cutoff,
    ).all()

    terminated_ids = []
    for vm in stale_vms:
        vm.status = ResourceStatus.TERMINATED
        vm.terminated_at = datetime.utcnow()
        terminated_ids.append(vm.id)

    if stale_vms:
        db.session.commit()

    return _success({
        'terminated_count': len(terminated_ids),
        'terminated_vm_ids': terminated_ids,
    })


@resource_bp.route('/vm/<instance_id>', methods=['GET'])
@jwt_required()
def get_vm(instance_id):
    """Get VM details by numeric id or instance_id string."""
    user_id = get_jwt_identity()
    allowed_org_ids = _ensure_org_membership(user_id)

    # Try numeric id first
    vm = None
    try:
        vm_id = int(instance_id)
        vm = VirtualMachine.query.get(vm_id)
    except (TypeError, ValueError):
        vm = VirtualMachine.query.filter_by(instance_id=instance_id).first()

    if not vm:
        return _error('VM not found', status_code=404, code='not_found')
    if vm.organization_id not in allowed_org_ids:
        return _error('Access denied', status_code=403, code='forbidden')
    return _success(_vm_to_envelope(vm))


@resource_bp.route('/vm/<instance_id>/action', methods=['POST'])
@jwt_required()
def vm_action(instance_id):
    """Perform action on VM (start, stop, terminate)."""
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    action = data.get('action')

    vm = None
    try:
        vm_id = int(instance_id)
        vm = VirtualMachine.query.get(vm_id)
    except (TypeError, ValueError):
        vm = VirtualMachine.query.filter_by(instance_id=instance_id).first()

    if not vm:
        return _error('VM not found', status_code=404, code='not_found')

    required_role = 'admin' if action == 'terminate' else 'member'
    if not check_org_access(user_id, vm.organization_id, required_role):
        return _error('Permission denied', status_code=403)

    if action == 'stop':
        vm.status = ResourceStatus.STOPPED
        vm.stopped_at = datetime.utcnow()
        vm.cpu_utilization = round(vm.cpu_utilization * 0.05, 2)
        vm.memory_utilization = round(vm.memory_utilization * 0.05, 2)
        # Real-time synchronization
        socketio.emit(
            'vm_updated',
            _vm_to_envelope(vm),
            room=f'org_{vm.organization_id}',
            namespace='/metrics'
        )
    elif action == 'start':
        if vm.status == ResourceStatus.STOPPED:
            vm.status = ResourceStatus.RUNNING
            vm.launched_at = datetime.utcnow()
            spec = INSTANCE_TYPES.get(vm.instance_type, {})
            vm.cpu_utilization = spec.get('baseline_cpu', 0.2) * 100
            vm.memory_utilization = spec.get('baseline_memory', 0.3) * 100
            # Real-time synchronization
            socketio.emit(
                'vm_updated',
                _vm_to_envelope(vm),
                room=f'org_{vm.organization_id}',
                namespace='/metrics'
            )
    elif action == 'terminate':
        vm.status = ResourceStatus.TERMINATED
        vm.terminated_at = datetime.utcnow()
    else:
        return _error('Invalid action', status_code=400, code='bad_request')

    db.session.commit()
    if action == 'stop':
        _record_operational_lifecycle_event(
            user_id=user_id,
            org_id=vm.organization_id,
            event_type='vm_stopped',
            resource_type='vm',
            resource_id=vm.id,
            details={'instance_id': vm.instance_id, 'name': vm.name, 'status': 'stopped'},
        )
        socketio.emit(
            'vm_updated',
            _vm_to_envelope(vm),
            room=f'org_{vm.organization_id}',
            namespace='/metrics',
        )
        _emit_resource_update(vm.organization_id)
    elif action == 'start':
        _record_operational_lifecycle_event(
            user_id=user_id,
            org_id=vm.organization_id,
            event_type='vm_started',
            resource_type='vm',
            resource_id=vm.id,
            details={'instance_id': vm.instance_id, 'name': vm.name, 'status': 'running'},
        )
        socketio.emit(
            'vm_updated',
            _vm_to_envelope(vm),
            room=f'org_{vm.organization_id}',
            namespace='/metrics',
        )
        _emit_resource_update(vm.organization_id)
    elif action == 'terminate':
        _award_xp_for_action(user_id, vm.organization_id, 'vm_deleted')
        _record_operational_lifecycle_event(
            user_id=user_id,
            org_id=vm.organization_id,
            event_type='vm_deleted',
            resource_type='vm',
            resource_id=vm.id,
            details={'instance_id': vm.instance_id, 'name': vm.name, 'status': 'terminated'},
        )
        socketio.emit(
            'vm_deleted',
            {
                'id': vm.id,
                'instance_id': vm.instance_id,
                'org_id': vm.organization_id,
                'organization_id': vm.organization_id,
            },
            room=f'org_{vm.organization_id}',
            namespace='/metrics'
        )
        _emit_resource_update(vm.organization_id)
    return _success(_vm_to_envelope(vm))


@resource_bp.route('/vms/<int:resource_id>/metrics', methods=['GET'])
@jwt_required()
def get_vm_metrics(resource_id):
    """Return the last N minutes of per-VM metric history."""
    user_id = get_jwt_identity()
    vm = VirtualMachine.query.filter(
        VirtualMachine.id == resource_id,
        VirtualMachine.status != ResourceStatus.TERMINATED,
    ).first()
    if not vm:
        return _error('VM not found', status_code=404, code='not_found')
    if not check_org_access(user_id, vm.organization_id, 'viewer'):
        return _error('Access denied', status_code=403, code='forbidden')

    minutes = request.args.get('minutes', 60, type=int)
    points_needed = (minutes * 60) // 5  # 5-second intervals

    simulator = getattr(current_app, 'simulator', None)
    history = []
    if simulator and hasattr(simulator, 'vm_metric_history'):
        from collections import deque
        vm_history = simulator.vm_metric_history.get(str(vm.id), deque())
        history = list(vm_history)[-points_needed:] if vm_history else []
    
    # If no history, generate synthetic points based on instance type baseline
    if not history:
        spec = INSTANCE_TYPES.get(vm.instance_type, INSTANCE_TYPES['t2.micro'])
        base_cpu = spec.get('baseline_cpu', 0.2) * 100
        base_mem = spec.get('baseline_memory', 0.3) * 100
        import time
        now = time.time()
        for i in range(12):  # Generate 12 synthetic points (1 minute)
            phase = i * 30
            cpu_variation = 5 * math.sin(math.radians(phase))
            mem_variation = 4 * math.cos(math.radians(phase * 2))
            history.append({
                'timestamp': now - (12 - i) * 5,
                'cpu': round(max(0, min(100, base_cpu + cpu_variation)), 2),
                'memory': round(max(0, min(100, base_mem + mem_variation)), 2),
                'network_in': round(random.uniform(10, 100), 2),
                'network_out': round(random.uniform(5, 50), 2),
            })

    return _success({
        'vm_id': vm.id,
        'instance_id': vm.instance_id,
        'hourly_rate': vm.hourly_rate,
        'current_cost': round(vm.calculate_current_cost(), 4),
        'metrics': history,
    })


@resource_bp.route('/vms/<int:resource_id>/resize', methods=['PUT'])
@jwt_required()
def resize_vm(resource_id):
    """Resize a VM to a different instance type."""
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    instance_type = (data.get('instance_type') or '').strip()
    if instance_type not in INSTANCE_TYPES:
        return _error('Invalid instance type', status_code=400, code='bad_request')

    vm = VirtualMachine.query.filter(
        VirtualMachine.id == resource_id,
        VirtualMachine.status != ResourceStatus.TERMINATED,
    ).first()
    if not vm:
        return _error('VM not found', status_code=404, code='not_found')
    if not check_org_access(user_id, vm.organization_id, 'member'):
        return _error('Permission denied', status_code=403)

    spec = _apply_vm_instance_type(vm, instance_type)
    # Update cpu_utilization to new baseline
    vm.cpu_utilization = round(spec.get('baseline_cpu', 0.2) * 100, 2)
    vm.memory_utilization = round(spec.get('baseline_memory', 0.3) * 100, 2)
    db.session.commit()
    
    # Emit vm_updated event
    envelope = _vm_to_envelope(vm)
    socketio.emit(
        'vm_updated',
        envelope,
        room=f'org_{vm.organization_id}',
        namespace='/metrics',
    )
    
    return _success(envelope)


@resource_bp.route('/vms/<int:resource_id>/tags', methods=['PUT'])
@jwt_required()
def update_vm_tags(resource_id):
    """Update tags on a VM. Accepts {tags: {key: value}}."""
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    tags = data.get('tags', {})

    vm = VirtualMachine.query.filter(
        VirtualMachine.id == resource_id,
        VirtualMachine.status != ResourceStatus.TERMINATED,
    ).first()
    if not vm:
        return _error('VM not found', status_code=404, code='not_found')
    if not check_org_access(user_id, vm.organization_id, 'member'):
        return _error('Permission denied', status_code=403)

    # Clear existing tags
    for tag in vm.tags:
        db.session.delete(tag)
    
    # Add new tags
    for key, value in tags.items():
        if key and value is not None:
            db.session.add(ResourceTag(vm_id=vm.id, key=str(key), value=str(value)))

    db.session.commit()
    return _success(_vm_to_envelope(vm))


@resource_bp.route('/db/<instance_id>/action', methods=['POST'])
@jwt_required()
def database_action(instance_id):
    """Perform an action on a database instance (start, stop, terminate)."""
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    action = data.get('action')

    database = None
    try:
        db_id = int(instance_id)
        database = Database.query.get(db_id)
    except (TypeError, ValueError):
        database = Database.query.filter_by(instance_id=instance_id).first()

    if not database:
        return _error('Database not found', status_code=404, code='not_found')

    required_role = 'admin' if action == 'terminate' else 'member'
    if not check_org_access(user_id, database.organization_id, required_role):
        return _error('Permission denied', status_code=403)

    if action == 'stop':
        database.status = ResourceStatus.STOPPED
        database.cpu_utilization = 0.0
        database.database_connections = 0

        # Real-time synchronization
        socketio.emit(
            'vm_updated',
            _db_to_envelope(database),
            room=f'org_{database.organization_id}',
            namespace='/metrics'
        )
    elif action == 'start':
        if database.status == ResourceStatus.STOPPED:
            database.status = ResourceStatus.RUNNING
            database.cpu_utilization = 5.0

            # Real-time synchronization
            socketio.emit(
                'vm_updated',
                _db_to_envelope(database),
                room=f'org_{database.organization_id}',
                namespace='/metrics'
            )
    elif action == 'terminate':
        database.status = ResourceStatus.TERMINATED
    else:
        return _error('Invalid action', status_code=400, code='bad_request')

    db.session.commit()
    if action == 'stop':
        _record_operational_lifecycle_event(
            user_id=user_id,
            org_id=database.organization_id,
            event_type='db_stopped',
            resource_type='database',
            resource_id=database.id,
            details={'instance_id': database.instance_id, 'name': database.name, 'engine': database.engine, 'status': 'stopped'},
        )
        socketio.emit(
            'vm_updated',
            _db_to_envelope(database),
            room=f'org_{database.organization_id}',
            namespace='/metrics'
        )
        _emit_resource_update(database.organization_id)
    elif action == 'start':
        _record_operational_lifecycle_event(
            user_id=user_id,
            org_id=database.organization_id,
            event_type='db_started',
            resource_type='database',
            resource_id=database.id,
            details={'instance_id': database.instance_id, 'name': database.name, 'engine': database.engine, 'status': 'running'},
        )
        socketio.emit(
            'vm_updated',
            _db_to_envelope(database),
            room=f'org_{database.organization_id}',
            namespace='/metrics'
        )
        _emit_resource_update(database.organization_id)
    elif action == 'terminate':
        _award_xp_for_action(user_id, database.organization_id, 'db_deleted')
        _record_operational_lifecycle_event(
            user_id=user_id,
            org_id=database.organization_id,
            event_type='db_deleted',
            resource_type='database',
            resource_id=database.id,
            details={'instance_id': database.instance_id, 'name': database.name, 'engine': database.engine, 'status': 'terminated'},
        )
        socketio.emit(
            'vm_deleted',
            {
                'id': database.id,
                'instance_id': database.instance_id,
                'org_id': database.organization_id,
                'organization_id': database.organization_id,
            },
            room=f'org_{database.organization_id}',
            namespace='/metrics'
        )
        _emit_resource_update(database.organization_id)
    return _success(_db_to_envelope(database))


@resource_bp.route('/db', methods=['POST'])
@jwt_required()
def create_database():
    """Create database instance."""
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    org_id = _resolve_org_id_for_user(user_id, data.get('organization_id', data.get('org_id')))
    if org_id is None:
        return _error('organization_id required', status_code=400)
    if not check_org_access(user_id, org_id, 'member'):
        return _error('Permission denied', status_code=403)

    database, error = _provision_database_record(org_id, data)
    if error:
        return error
    _award_xp_for_action(user_id, org_id, 'db_created')
    _record_operational_lifecycle_event(
        user_id=user_id,
        org_id=org_id,
        event_type='db_created',
        resource_type='database',
        resource_id=database.id,
        details={
            'engine': database.engine,
            'name': database.name,
            'hourly_rate': float(database.hourly_rate or 0),
        },
    )
    _emit_resource_update(org_id)
    return _success(_db_to_envelope(database), status_code=201)


@resource_bp.route('/db', methods=['GET'])
@resource_bp.route('/dbs', methods=['GET'])
@jwt_required()
def list_databases():
    """List databases."""
    user_id = get_jwt_identity()
    org_id = request.args.get('org_id', type=int) or request.args.get('organization_id', type=int)
    if org_id is None:
        org_id = _resolve_org_id_for_user(user_id) or 1
    if not check_org_access(user_id, org_id, 'viewer'):
        return _error('Access denied', status_code=403, code='forbidden')

    databases = Database.query.filter(
        Database.organization_id == org_id,
        Database.status != ResourceStatus.TERMINATED,
    ).all()
    return _success([_db_to_envelope(d) for d in databases])


@resource_bp.route('/metrics', methods=['GET'])
@jwt_required()
def get_resource_metrics():
    """Get aggregated resource metrics from the database."""
    user_id = get_jwt_identity()
    org_id = request.args.get('organization_id', type=int)
    if org_id is None:
        org_id = _resolve_org_id_for_user(user_id) or 1
    if not check_org_access(user_id, org_id, 'viewer'):
        return _error('Access denied', status_code=403, code='forbidden')

    vms = VirtualMachine.query.filter(
        VirtualMachine.organization_id == org_id,
        VirtualMachine.status != ResourceStatus.TERMINATED,
    ).all()
    databases = Database.query.filter(
        Database.organization_id == org_id,
        Database.status != ResourceStatus.TERMINATED,
    ).all()

    running_vms = [vm for vm in vms if vm.status == ResourceStatus.RUNNING]
    running_dbs = [d for d in databases if d.status == ResourceStatus.RUNNING]
    all_running = running_vms + running_dbs

    avg_cpu = (
        sum(r.cpu_utilization for r in all_running) / len(all_running)
        if all_running else 0.0
    )
    avg_memory = (
        sum(r.memory_utilization for r in running_vms) / len(running_vms)
        if running_vms else 0.0
    )
    # Calculate real costs: hourly_rate * (uptime_hours / total_runtime_hours) for each running resource
    vm_costs = [vm.calculate_current_cost() for vm in running_vms]
    db_costs = [d.total_runtime_hours * d.hourly_rate for d in running_dbs]
    total_cost = sum(vm_costs) + sum(db_costs)
    total_hourly_cost = sum(vm.hourly_rate for vm in running_vms) + sum(d.hourly_rate for d in running_dbs)
    daily_average_cost = total_cost / 30.0 if total_cost > 0 else 0.0

    return _success({
        'summary': {
            'total_vms': len(vms),
            'running_vms': len(running_vms),
            'total_databases': len(databases),
            'running_databases': len(running_dbs),
            'total_hourly_cost': round(total_hourly_cost, 4),
            'estimated_monthly_cost': round(total_hourly_cost * 730, 2),
            'total_cost': round(total_cost, 4),
            'daily_average_cost': round(daily_average_cost, 4),
            'average_cpu_utilization': round(avg_cpu, 2),
            'average_memory_utilization': round(avg_memory, 2),
            'average_network_throughput': 0.0,
            'average_database_cpu': round(
                sum(d.cpu_utilization for d in running_dbs) / len(running_dbs), 2
            ) if running_dbs else 0.0,
        },
        'cost_trend': [],
        'utilization_trend': [],
        'recent_activity': [],
        'vms': [_vm_to_envelope(vm) for vm in vms],
        'databases': [_db_to_envelope(d) for d in databases],
    })
