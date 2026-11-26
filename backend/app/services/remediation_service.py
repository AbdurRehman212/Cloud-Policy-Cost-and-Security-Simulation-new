"""Remediation workflow (Module 10, UC10 Execute Remediation).

Issue → plan → approve → execute → verify → record:

1. ``list_issues``  open threats, policy violations and idle VMs of one organization.
2. ``build_plan``   the agent's explainable recommendations with a before/after preview.
3. ``execute``      applies the approved actions to *simulated* rows in this database only
                    (security groups, instance type, flags). Nothing outside the simulator is
                    contacted. The issue row is locked (SELECT … FOR UPDATE) so two requests
                    cannot remediate it twice; all state changes run in one savepoint and are
                    rolled back together if any action fails or cannot be verified.
4. Each action is re-read after it runs; an issue is marked resolved only when every
   executed change is verified (governance issues are re-evaluated with the policy engine).
5. Every outcome — success, failure, approval — is written to the audit trail.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime

from app import db
from app.ai_models.remediation_agent import (
    ACTION_CATALOG,
    APPROVAL_REQUIRED,
    IDLE_CPU_THRESHOLD,
    remediation_agent,
)
from app.models.governance import ComplianceCheck, Policy
from app.models.resources import (
    Database,
    ResourceStatus,
    ResourceTag,
    SecurityGroup,
    SecurityGroupRule,
    VirtualMachine,
)
from app.models.security import RemediationAction, SecurityLog, ThreatDetection
from app.services.audit_service import record_audit, record_audit_safely

OPEN_THREAT_STATUSES = ('active', 'contained', 'under_review')
QUARANTINE_GROUP = 'remediation-quarantine'
BLOCKLIST_GROUP = 'remediation-blocklist'
# Rule-changing actions run before isolation so a block rule lands on the original groups.
EXECUTION_ORDER = [
    'block_ip', 'disable_public_access', 'enable_encryption', 'add_required_tag',
    'scale_up', 'downsize_resource', 'stop_idle_resource', 'isolate_resource', 'request_review',
]


class RemediationError(Exception):
    def __init__(self, message, status_code=400, code='bad_request'):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


# ── helpers ────────────────────────────────────────────────────────────────────

def _instance_types():
    from app.routes.resources import INSTANCE_TYPES
    return INSTANCE_TYPES


def _type_ladder():
    types = _instance_types()
    return sorted(types, key=lambda name: (types[name]['vcpu'], types[name]['memory_gb']))


def _next_type(current, direction):
    """Next instance type with strictly more (up) / less (down) vCPU, else memory."""
    types = _instance_types()
    if current not in types:
        return None
    spec = types[current]
    ladder = _type_ladder()
    if direction == 'up':
        for name in ladder:
            s = types[name]
            if s['vcpu'] > spec['vcpu']:
                return name
        return None
    for name in reversed(ladder):
        s = types[name]
        if (s['vcpu'], s['memory_gb']) < (spec['vcpu'], spec['memory_gb']):
            return name
    return None


def _resolve_resource(org_id, ref):
    """A VM or Database of this organization from an id or instance id; None if absent."""
    if ref in (None, ''):
        return None
    ref = str(ref)
    queries = []
    if ref.isdigit():
        queries += [VirtualMachine.query.filter_by(id=int(ref)), Database.query.filter_by(id=int(ref))]
    queries += [VirtualMachine.query.filter_by(instance_id=ref), Database.query.filter_by(instance_id=ref)]
    for query in queries:
        row = query.filter_by(organization_id=org_id).first()
        if row is not None and row.status != ResourceStatus.TERMINATED:
            return row
    return None


def _kind(row):
    if isinstance(row, VirtualMachine):
        return 'vm'
    if isinstance(row, Database):
        return 'database'
    return None


def _snapshot(row):
    if row is None:
        return None
    if isinstance(row, VirtualMachine):
        return {
            'kind': 'vm', 'id': row.id, 'name': row.name, 'instance_id': row.instance_id,
            'status': row.status.value if row.status else None, 'instance_type': row.instance_type,
            'hourly_rate': row.hourly_rate, 'cpu_utilization': round(row.cpu_utilization or 0, 2),
            'public_ip': row.public_ip, 'security_groups': [g.name for g in row.security_groups],
            'tags': {t.key: t.value for t in row.tags},
        }
    return {
        'kind': 'database', 'id': row.id, 'name': row.name, 'instance_id': row.instance_id,
        'status': row.status.value if row.status else None, 'instance_class': row.instance_class,
        'publicly_accessible': bool(row.publicly_accessible), 'storage_encrypted': bool(row.storage_encrypted),
        'tags': {t.key: t.value for t in row.tags},
    }


def _source_ip(threat):
    vectors = threat.attack_vectors if isinstance(threat.attack_vectors, dict) else {}
    candidate = vectors.get('source_ip')
    if not candidate and threat.detected_at:
        logs = (
            SecurityLog.query
            .filter(SecurityLog.organization_id == threat.organization_id, SecurityLog.source_ip.isnot(None))
            .filter(SecurityLog.event_type.like(f'{threat.threat_type.value}%'))
            .order_by(SecurityLog.timestamp.desc())
            .limit(50)
            .all()
        )
        nearest = min(logs, key=lambda log: abs((log.timestamp - threat.detected_at).total_seconds()), default=None)
        candidate = nearest.source_ip if nearest else None
    try:
        return str(ipaddress.IPv4Address(candidate)) if candidate else None
    except ValueError:
        return None


def _get_or_create_group(org_id, name, description, deny_all_inbound):
    group = SecurityGroup.query.filter_by(org_id=org_id, name=name).first()
    if group is None:
        group = SecurityGroup(org_id=org_id, name=name, description=description)
        db.session.add(group)
        db.session.flush()
        if deny_all_inbound:
            db.session.add(SecurityGroupRule(
                group_id=group.id, direction='inbound', protocol='All', port_range='all',
                source_cidr='0.0.0.0/0', action='deny', description='Remediation quarantine: deny all inbound',
            ))
            db.session.flush()
    return group


# ── issues ─────────────────────────────────────────────────────────────────────

def _threat_issue(threat):
    affected = threat.affected_resources or []
    return {
        'key': f'threat:{threat.id}', 'type': 'threat', 'id': threat.id,
        'title': f'{threat.threat_type.value.replace("_", " ").title()} threat',
        'severity': threat.severity.value if threat.severity else 'medium',
        'confidence': round(float(threat.confidence_score or 0), 4),
        'status': threat.status, 'detected_at': threat.detected_at.isoformat() if threat.detected_at else None,
        'resource_ref': affected[0] if affected else None,
        'summary': threat.detection_pattern,
        'simulated': bool((threat.attack_vectors or {}).get('simulation')) if isinstance(threat.attack_vectors, dict) else False,
    }


def list_issues(org_id):
    from app.services.governance_engine import governance_engine

    issues = []
    threats = (
        ThreatDetection.query
        .filter(ThreatDetection.organization_id == org_id, ThreatDetection.status.in_(OPEN_THREAT_STATUSES))
        .order_by(ThreatDetection.detected_at.desc())
        .limit(200)
        .all()
    )
    issues += [_threat_issue(t) for t in threats]

    for violation in governance_engine.get_latest_state(org_id)['violations']:
        if violation.get('remediation_applied'):
            continue
        issues.append({
            'key': f'violation:{violation["check_id"]}', 'type': 'violation', 'id': violation['check_id'],
            'title': f'Policy violation: {violation["policy_name"]}',
            'severity': violation.get('severity') or 'medium', 'confidence': None, 'status': 'open',
            'detected_at': violation.get('checked_at'), 'resource_ref': violation.get('resource_id'),
            'summary': '; '.join(violation.get('violations') or []),
        })

    idle_vms = VirtualMachine.query.filter(
        VirtualMachine.organization_id == org_id,
        VirtualMachine.status == ResourceStatus.RUNNING,
        VirtualMachine.cpu_utilization < IDLE_CPU_THRESHOLD,
    ).order_by(VirtualMachine.id).limit(100).all()
    for vm in idle_vms:
        issues.append({
            'key': f'idle:vm:{vm.id}', 'type': 'idle', 'id': vm.id,
            'title': f'Idle resource: {vm.name}', 'severity': 'low', 'confidence': None, 'status': 'open',
            'detected_at': None, 'resource_ref': vm.instance_id,
            'summary': f'CPU {vm.cpu_utilization:.1f}% < {IDLE_CPU_THRESHOLD:.0f}% while running at ${vm.hourly_rate}/h',
        })
    return issues


def _load_issue(org_id, key, lock=False):
    """(issue dict, locked row, resource row, violation messages, policy) for an issue key."""
    parts = str(key or '').split(':')
    try:
        if parts[0] == 'threat' and len(parts) == 2:
            query = ThreatDetection.query.filter_by(id=int(parts[1]), organization_id=org_id)
            threat = (query.with_for_update().populate_existing() if lock else query).first()
            if threat is None:
                raise RemediationError('Issue not found', 404, 'not_found')
            ref = (threat.affected_resources or [None])[0]
            issue = _threat_issue(threat)
            if threat.status not in OPEN_THREAT_STATUSES:
                issue['status'] = 'resolved'
            return issue, threat, _resolve_resource(org_id, ref), [], None
        if parts[0] == 'violation' and len(parts) == 2:
            query = ComplianceCheck.query.join(Policy).filter(
                ComplianceCheck.id == int(parts[1]), Policy.organization_id == org_id)
            check = (query.with_for_update(of=ComplianceCheck).populate_existing() if lock else query).first()
            if check is None:
                raise RemediationError('Issue not found', 404, 'not_found')
            messages = (check.violation_details or {}).get('violations', [])
            issue = {
                'key': key, 'type': 'violation', 'id': check.id, 'title': f'Policy violation: {check.policy.name}',
                'severity': check.policy.severity, 'confidence': None,
                'status': 'resolved' if check.remediation_applied or check.is_compliant else 'open',
                'resource_ref': check.resource_id, 'summary': '; '.join(messages),
            }
            return issue, check, _resolve_resource(org_id, check.resource_id), messages, check.policy
        if parts[0] == 'idle' and len(parts) == 3 and parts[1] == 'vm':
            query = VirtualMachine.query.filter_by(id=int(parts[2]), organization_id=org_id)
            vm = (query.with_for_update().populate_existing() if lock else query).first()
            if vm is None or vm.status == ResourceStatus.TERMINATED:
                raise RemediationError('Issue not found', 404, 'not_found')
            idle = vm.status == ResourceStatus.RUNNING and (vm.cpu_utilization or 0) < IDLE_CPU_THRESHOLD
            issue = {
                'key': key, 'type': 'idle', 'id': vm.id, 'title': f'Idle resource: {vm.name}', 'severity': 'low',
                'confidence': None, 'status': 'open' if idle else 'resolved', 'resource_ref': vm.instance_id,
                'summary': f'CPU {vm.cpu_utilization:.1f}%',
            }
            return issue, vm, vm, [], None
    except ValueError:
        pass
    raise RemediationError('Invalid issue key', 400)


# ── plan ───────────────────────────────────────────────────────────────────────

def _preview(action, row, org_id, threat):
    """(applicable, reason_if_not, {field: {before, after}}) without changing anything."""
    kind = _kind(row)
    allowed = ACTION_CATALOG[action]['targets']
    if action == 'request_review':
        return True, None, {}
    if action == 'block_ip':
        ip = _source_ip(threat) if threat else None
        if not ip:
            return False, 'No valid source IP is recorded for this threat.', {}
        groups = [g.name for g in row.security_groups] if kind == 'vm' and row.security_groups else [BLOCKLIST_GROUP]
        return True, None, {'inbound_deny_rule': {'before': None, 'after': f'{ip}/32 on {", ".join(groups)}'}}
    if row is None:
        return False, 'The issue is not linked to an existing simulated resource; select a target resource.', {}
    if kind not in allowed:
        return False, f'Not supported for a {kind} resource.', {}
    if action == 'isolate_resource':
        return True, None, {'security_groups': {'before': [g.name for g in row.security_groups], 'after': [QUARANTINE_GROUP]}}
    if action in ('scale_up', 'downsize_resource'):
        target = _next_type(row.instance_type, 'up' if action == 'scale_up' else 'down')
        if target is None:
            return False, f'{row.instance_type} is already the {"largest" if action == "scale_up" else "smallest"} type.', {}
        rate = _instance_types()[target]['hourly_rate']
        return True, None, {
            'instance_type': {'before': row.instance_type, 'after': target},
            'hourly_rate': {'before': row.hourly_rate, 'after': rate},
        }
    if action == 'stop_idle_resource':
        if row.status != ResourceStatus.RUNNING:
            return False, f'Resource is {row.status.value}, not running.', {}
        return True, None, {'status': {'before': 'running', 'after': 'stopped'}}
    if action == 'disable_public_access':
        if kind == 'database':
            if not row.publicly_accessible:
                return False, 'Public access is already disabled.', {}
            return True, None, {'publicly_accessible': {'before': True, 'after': False}}
        if not row.public_ip:
            return False, 'The VM has no public IP.', {}
        return True, None, {'public_ip': {'before': row.public_ip, 'after': None}}
    if action == 'enable_encryption':
        if row.storage_encrypted:
            return False, 'Storage is already encrypted.', {}
        return True, None, {'storage_encrypted': {'before': False, 'after': True}}
    return True, None, {}


def _required_tags(policy, row):
    rule = (policy.compiled_rule or {}) if policy else {}
    rule = rule.get('fields', rule)
    current = {t.key.lower() for t in row.tags} if row is not None else set()
    return [t for t in rule.get('required_tags') or [] if (t.get('key') or '').lower() not in current]


def build_plan(org_id, key, target_ref=None):
    issue, locked, row, messages, policy = _load_issue(org_id, key)
    threat = locked if isinstance(locked, ThreatDetection) else None
    if row is None and target_ref is not None:
        row = _resolve_resource(org_id, target_ref)
        if row is None:
            raise RemediationError('Target resource not found in this organization', 404, 'not_found')

    resource_dict = row.to_dict() if row is not None else None
    threat_dict = {'type': threat.threat_type.value, 'confidence': threat.confidence_score} if threat else None
    if issue['type'] == 'violation':
        recs = remediation_agent.recommend(None, None, violations=messages)
    elif issue['type'] == 'idle':
        recs = remediation_agent.recommend(None, resource_dict)
    else:
        recs = remediation_agent.recommend(threat_dict, resource_dict)

    actions = []
    for rec in recs:
        action = rec['action']
        meta = ACTION_CATALOG[action]
        applicable, why_not, preview = _preview(action, row, org_id, threat)
        params = {}
        if action == 'add_required_tag':
            missing = [t for t in _required_tags(policy, row) if t.get('value')]
            if not missing:
                applicable, why_not = False, 'The policy does not state a tag value; a person must choose one.'
            else:
                params['tags'] = [{'key': t['key'], 'value': t['value']} for t in missing]
                preview = {'tags': {'before': _snapshot(row)['tags'], 'after': {t['key']: t['value'] for t in missing}}}
        actions.append({
            'action': action, 'label': meta['label'], 'reason': rec['reason'],
            'description': meta['description'], 'consequence': meta['consequence'], 'recovery': meta['recovery'],
            'requires_approval': action in APPROVAL_REQUIRED, 'applicable': applicable,
            'not_applicable_reason': why_not, 'preview': preview, 'params': params,
        })
    actions.sort(key=lambda a: EXECUTION_ORDER.index(a['action']))
    return {
        'issue': issue,
        'resource': _snapshot(row),
        'actions': actions,
        'requires_approval': any(a['requires_approval'] and a['applicable'] for a in actions),
        'engine': 'rule-based (deterministic, explainable)',
        'history': history(org_id, issue_key=key, limit=20),
    }


# ── execute ────────────────────────────────────────────────────────────────────

def _apply(action, row, org_id, threat, params):
    """Change simulated state for one action; returns (before, after). Raises on failure."""
    before = _snapshot(row)
    if action == 'request_review':
        return before, before
    if action == 'block_ip':
        ip = _source_ip(threat)
        if not ip:
            raise RemediationError('No valid source IP is recorded for this threat', 422, 'action_failed')
        if _kind(row) == 'vm' and row.security_groups:
            groups = [g for g in row.security_groups if g.name != QUARANTINE_GROUP] or list(row.security_groups)
        else:
            groups = [_get_or_create_group(org_id, BLOCKLIST_GROUP, 'Source addresses blocked by remediation', False)]
        for group in groups:
            exists = SecurityGroupRule.query.filter_by(
                group_id=group.id, direction='inbound', source_cidr=f'{ip}/32', action='deny').first()
            if not exists:
                db.session.add(SecurityGroupRule(
                    group_id=group.id, direction='inbound', protocol='All', port_range='all',
                    source_cidr=f'{ip}/32', action='deny', description=f'Remediation: block {ip}',
                ))
        db.session.flush()
        ok = all(SecurityGroupRule.query.filter_by(group_id=g.id, source_cidr=f'{ip}/32', action='deny').first() for g in groups)
        if not ok:
            raise RemediationError('Block rule could not be verified', 422, 'verification_failed')
        return before, {**(before or {}), 'blocked_source': f'{ip}/32', 'rule_groups': [g.name for g in groups]}
    if action == 'isolate_resource':
        quarantine = _get_or_create_group(org_id, QUARANTINE_GROUP, 'Remediation quarantine: deny all inbound', True)
        row.security_groups = [quarantine]
        db.session.flush()
        if [g.id for g in row.security_groups] != [quarantine.id]:
            raise RemediationError('Isolation could not be verified', 422, 'verification_failed')
    elif action in ('scale_up', 'downsize_resource'):
        from app.routes.resources import _apply_vm_instance_type
        target = _next_type(row.instance_type, 'up' if action == 'scale_up' else 'down')
        if target is None:
            raise RemediationError(f'No {"larger" if action == "scale_up" else "smaller"} instance type available', 422, 'action_failed')
        old_vcpu, old_mem = row.vcpu or 1, row.memory_gb or 1
        _apply_vm_instance_type(row, target)
        # Same load on a different capacity: utilization scales by old/new capacity.
        row.cpu_utilization = round(min(100.0, (row.cpu_utilization or 0) * old_vcpu / row.vcpu), 2)
        row.memory_utilization = round(min(100.0, (row.memory_utilization or 0) * old_mem / row.memory_gb), 2)
        db.session.flush()
        if row.instance_type != target:
            raise RemediationError('Resize could not be verified', 422, 'verification_failed')
    elif action == 'stop_idle_resource':
        if row.status != ResourceStatus.RUNNING:
            raise RemediationError('Resource is not running', 422, 'action_failed')
        row.status = ResourceStatus.STOPPED
        row.stopped_at = datetime.utcnow()
        row.cpu_utilization = round((row.cpu_utilization or 0) * 0.05, 2)
        row.memory_utilization = round((row.memory_utilization or 0) * 0.05, 2)
        db.session.flush()
    elif action == 'disable_public_access':
        if _kind(row) == 'database':
            row.publicly_accessible = False
        else:
            row.public_ip = None
            row.subnet_type = 'private'
        db.session.flush()
    elif action == 'enable_encryption':
        row.storage_encrypted = True
        db.session.flush()
    elif action == 'add_required_tag':
        for tag in params.get('tags') or []:
            field = 'vm_id' if _kind(row) == 'vm' else 'db_id'
            db.session.add(ResourceTag(**{field: row.id}, key=tag['key'], value=tag['value']))
        db.session.flush()
        db.session.refresh(row)
    else:
        raise RemediationError(f'Unsupported action {action}', 400)
    db.session.refresh(row)
    return before, _snapshot(row)


def _verify_governance(policy, row):
    from app.ai_models.policy_engine import policy_engine
    rule = (policy.compiled_rule or {})
    rule = rule.get('fields', rule)
    return policy_engine.evaluate_resource(rule, row.to_dict())


def execute(org_id, user_id, key, selected_actions, approved, target_ref=None):
    if not isinstance(selected_actions, list) or not selected_actions:
        raise RemediationError('Select at least one action', 400)
    if len(set(selected_actions)) != len(selected_actions):
        raise RemediationError('Duplicate actions in request', 400)

    plan = build_plan(org_id, key, target_ref)
    by_action = {a['action']: a for a in plan['actions']}
    for action in selected_actions:
        if action not in by_action:
            raise RemediationError(f'"{action}" is not a recommended action for this issue', 400)
        if not by_action[action]['applicable']:
            raise RemediationError(f'"{action}" cannot run: {by_action[action]["not_applicable_reason"]}', 409, 'not_applicable')
    needs_approval = [a for a in selected_actions if by_action[a]['requires_approval']]
    if needs_approval and approved is not True:
        raise RemediationError('Explicit approval is required for: ' + ', '.join(needs_approval), 400, 'approval_required')

    # Lock the issue row; a concurrent request for the same issue waits here, then sees it resolved.
    issue, locked, row, messages, policy = _load_issue(org_id, key, lock=True)
    if row is None and target_ref is not None:
        row = _resolve_resource(org_id, target_ref)
    threat = locked if isinstance(locked, ThreatDetection) else None
    if issue['status'] == 'resolved':
        db.session.rollback()
        raise RemediationError('This issue is already resolved', 409, 'already_resolved')
    in_progress = RemediationAction.query.filter_by(issue_key=key, organization_id=org_id, status='in_progress').first()
    if in_progress:
        db.session.rollback()
        raise RemediationError('A remediation for this issue is already running', 409, 'in_progress')

    ordered = sorted(selected_actions, key=EXECUTION_ORDER.index)
    now = datetime.utcnow()
    applied = []
    savepoint = db.session.begin_nested()
    try:
        for action in ordered:
            before, after = _apply(action, row, org_id, threat, by_action[action]['params'])
            applied.append({'action': action, 'before': before, 'after': after})
        verification = None
        if issue['type'] == 'violation':
            verification = _verify_governance(policy, row)
            fixable = [a for a in ordered if a != 'request_review']
            if fixable and not verification['compliant'] and 'request_review' not in ordered:
                raise RemediationError(
                    'Changes applied but the resource still violates the policy: ' + '; '.join(verification['violations']),
                    422, 'verification_failed')
        savepoint.commit()
    except RemediationError as exc:
        savepoint.rollback()
        failure = exc
    except Exception as exc:  # unexpected: roll back state, report a safe message
        savepoint.rollback()
        failure = RemediationError(f'Remediation failed: {exc.__class__.__name__}', 500, 'action_failed')
    else:
        failure = None

    resource_type, resource_id = (_kind(row), row.id) if row is not None else ('organization', None)
    if failure is not None:
        db.session.rollback()  # release the lock; no resource or issue changes were kept
        for action in ordered:
            db.session.add(RemediationAction(
                organization_id=org_id, threat_id=threat.id if threat else None, issue_type=issue['type'],
                issue_key=key, resource_type=resource_type, resource_id=resource_id, assigned_to=user_id,
                action_type=action, executed_at=now, executed_by=str(user_id), status='failed',
                details={'verified': False, 'explanation': by_action[action]['reason']},
                result=failure.message, requires_approval=action in APPROVAL_REQUIRED,
                approved_by=user_id if approved else None, approved_at=now if approved else None,
            ))
        record_audit('remediation_failed', org_id=org_id, user_id=user_id, resource_type=issue['type'],
                     resource_id=key, outcome='failure', compliance_relevant=True,
                     new_values={'actions': ordered, 'error': failure.message})
        db.session.commit()
        raise failure

    executed = [a for a in ordered if a != 'request_review']
    review = 'request_review' in ordered
    records = []
    for item in applied:
        action = item['action']
        record = RemediationAction(
            organization_id=org_id, threat_id=threat.id if threat else None, issue_type=issue['type'],
            issue_key=key, resource_type=resource_type, resource_id=resource_id, assigned_to=user_id,
            action_type=action, executed_at=now, executed_by=str(user_id),
            status='awaiting_review' if action == 'request_review' else 'succeeded',
            details={
                'verified': action != 'request_review', 'explanation': by_action[action]['reason'],
                'before': item['before'], 'after': item['after'], 'recovery': ACTION_CATALOG[action]['recovery'],
                'simulated': True,
            },
            result='Recorded for human review; no configuration changed.' if action == 'request_review'
            else f'{ACTION_CATALOG[action]["label"]} applied to simulated resource and verified.',
            requires_approval=action in APPROVAL_REQUIRED,
            approved_by=user_id if action in APPROVAL_REQUIRED else None,
            approved_at=now if action in APPROVAL_REQUIRED else None,
        )
        db.session.add(record)
        records.append(record)

    # Issue status follows verified state only.
    if threat is not None:
        old_status = threat.status
        threat.status = 'resolved' if executed and not review else ('contained' if executed else 'under_review')
        if threat.status == 'resolved':
            threat.resolved_at, threat.resolved_by = now, user_id
        new_status = threat.status
    elif issue['type'] == 'violation':
        old_status = 'open'
        new_status = 'resolved' if verification and verification['compliant'] else 'under_review'
        locked.remediation_applied = new_status == 'resolved'
        locked.remediation_details = {'actions': ordered, 'by': user_id, 'at': now.isoformat(),
                                      'verified_compliant': bool(verification and verification['compliant'])}
    else:
        old_status = 'open'
        new_status = 'resolved' if executed else 'under_review'

    if needs_approval:
        record_audit('remediation_approved', org_id=org_id, user_id=user_id, resource_type=issue['type'],
                     resource_id=key, compliance_relevant=True, new_values={'actions': needs_approval})
    record_audit('remediation_executed', org_id=org_id, user_id=user_id, resource_type=issue['type'],
                 resource_id=key, compliance_relevant=True,
                 old_values={'issue_status': old_status, 'resource': applied[0]['before'] if applied else None},
                 new_values={'issue_status': new_status, 'actions': ordered,
                             'resource': applied[-1]['after'] if applied else None})
    db.session.commit()

    if issue['type'] == 'violation' and new_status == 'resolved':
        from app.services.governance_engine import governance_engine
        governance_engine.evaluate_org_policies(org_id, actor_user_id=user_id)  # refresh persisted score

    _emit(org_id, row)
    return {
        'issue_key': key, 'issue_status': new_status, 'previous_status': old_status,
        'actions': [r.to_dict() for r in records], 'resource': _snapshot(row) if row is not None else None,
        'verification': verification and {'compliant': verification['compliant'], 'violations': verification['violations']},
    }


def _emit(org_id, row):
    try:
        from app import socketio
        payload = {'organization_id': org_id, 'org_id': org_id, 'source': 'remediation'}
        socketio.emit('threats:update', payload, room=f'org_{org_id}', namespace='/metrics')
        socketio.emit('dashboard_update', payload, room=f'org_{org_id}', namespace='/metrics')
        if isinstance(row, VirtualMachine):
            from app.routes.resources import _vm_to_envelope
            socketio.emit('vm_updated', _vm_to_envelope(row), room=f'org_{org_id}', namespace='/metrics')
    except Exception:  # real-time push is best-effort; the HTTP response carries the result
        pass


def history(org_id, issue_key=None, limit=100, offset=0):
    query = RemediationAction.query.filter(RemediationAction.organization_id == org_id)
    if issue_key:
        query = query.filter(RemediationAction.issue_key == issue_key)
    rows = (query.order_by(RemediationAction.executed_at.desc(), RemediationAction.id.desc())
            .offset(offset).limit(limit).all())
    return [r.to_dict() for r in rows]


def history_count(org_id):
    return RemediationAction.query.filter(RemediationAction.organization_id == org_id).count()


__all__ = ['RemediationError', 'list_issues', 'build_plan', 'execute', 'history', 'history_count', 'record_audit_safely']
