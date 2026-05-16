from __future__ import annotations

from dataclasses import dataclass

from flask import current_app

from app import db
from app.models.security import AlertRule, SecurityLog, ThreatDetection, ThreatSeverity
from app.services.operational_event_service import OperationalEventService


SUPPORTED_CONDITION_FIELDS = {'severity', 'threat_type', 'confidence_score'}
SUPPORTED_OPERATORS = {'equals', 'contains', 'greater_than', 'less_than'}
SUPPORTED_ACTIONS = {'IN_APP_NOTIFY', 'EMAIL_NOTIFY', 'ISOLATE_RESOURCE', 'BLOCK_IP'}


@dataclass
class AlertRuleValidationError(Exception):
    message: str


def _normalize_condition_value(field: str, value) -> str:
    if value is None or str(value).strip() == '':
        raise AlertRuleValidationError('Condition value is required')

    if field == 'confidence_score':
        try:
            numeric_value = float(value)
        except (TypeError, ValueError) as exc:
            raise AlertRuleValidationError('Confidence score conditions require a numeric value') from exc

        if numeric_value < 0 or numeric_value > 1:
            raise AlertRuleValidationError('Confidence score must be between 0 and 1')

        return str(numeric_value)

    return str(value).strip()


def validate_rule_payload(payload: dict, require_condition: bool = True) -> dict:
    data = payload or {}
    normalized: dict = {}

    if 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            raise AlertRuleValidationError('Rule name is required')
        normalized['name'] = name

    if 'description' in data:
        normalized['description'] = (data.get('description') or '').strip() or None

    condition = data.get('condition') or {}
    field = condition.get('field', data.get('condition_field'))
    operator = condition.get('operator', data.get('condition_operator'))
    value = condition.get('value', data.get('condition_value'))

    if require_condition or field is not None or operator is not None or value is not None:
        field = (field or '').strip()
        operator = (operator or '').strip()

        if field not in SUPPORTED_CONDITION_FIELDS:
            raise AlertRuleValidationError(
                f"Unsupported condition field. Expected one of: {', '.join(sorted(SUPPORTED_CONDITION_FIELDS))}"
            )
        if operator not in SUPPORTED_OPERATORS:
            raise AlertRuleValidationError(
                f"Unsupported operator. Expected one of: {', '.join(sorted(SUPPORTED_OPERATORS))}"
            )
        if field != 'confidence_score' and operator in {'greater_than', 'less_than'}:
            raise AlertRuleValidationError('Numeric operators are only supported for confidence_score')
        if field == 'confidence_score' and operator == 'contains':
            raise AlertRuleValidationError('contains is not supported for confidence_score')

        normalized['condition_field'] = field
        normalized['condition_operator'] = operator
        normalized['condition_value'] = _normalize_condition_value(field, value)

    if 'action_type' in data or require_condition:
        action_type = (data.get('action_type') or '').strip().upper()
        if action_type not in SUPPORTED_ACTIONS:
            raise AlertRuleValidationError(
                f"Unsupported action type. Expected one of: {', '.join(sorted(SUPPORTED_ACTIONS))}"
            )
        normalized['action_type'] = action_type

    if 'is_active' in data:
        normalized['is_active'] = bool(data.get('is_active'))

    return normalized


def evaluate_rule_match(rule: AlertRule, threat: ThreatDetection) -> bool:
    field = rule.condition_field
    operator = rule.condition_operator
    condition_value = rule.condition_value

    actual_value = getattr(threat, field, None)
    if hasattr(actual_value, 'value'):
        actual_value = actual_value.value

    if field == 'confidence_score':
        actual_numeric = float(actual_value or 0)
        expected_numeric = float(condition_value)
        if operator == 'greater_than':
            return actual_numeric > expected_numeric
        if operator == 'less_than':
            return actual_numeric < expected_numeric
        return actual_numeric == expected_numeric

    actual_text = str(actual_value or '').strip().lower()
    expected_text = str(condition_value or '').strip().lower()

    if operator == 'equals':
        return actual_text == expected_text
    if operator == 'contains':
        return expected_text in actual_text

    return False


def _mail_configured() -> bool:
    return bool(
        current_app.config.get('MAIL_SERVER')
        and current_app.config.get('MAIL_PORT')
        and current_app.config.get('MAIL_DEFAULT_SENDER')
        and current_app.config.get('MAIL_USERNAME')
        and current_app.config.get('MAIL_PASSWORD')
    )


def _build_action_metadata(rule: AlertRule, threat: ThreatDetection) -> dict:
    action_type = rule.action_type
    if action_type == 'IN_APP_NOTIFY':
        return {
            'status': 'recorded',
            'result': 'In-app notification recorded for the organization security feed.',
        }
    if action_type == 'EMAIL_NOTIFY':
        return {
            'status': 'skipped',
            'result': (
                'Email delivery skipped because alert rules do not send real emails in this simulation.'
                if _mail_configured()
                else 'Email delivery skipped because mail is not configured.'
            ),
        }
    if action_type == 'ISOLATE_RESOURCE':
        resource_id = (threat.affected_resources or [None])[0]
        return {
            'status': 'simulated',
            'result': f'Simulated resource isolation recorded for {resource_id or "the affected resource"}.',
        }
    if action_type == 'BLOCK_IP':
        source_ip = None
        snapshot = threat.network_traffic_snapshot if isinstance(threat.network_traffic_snapshot, dict) else {}
        source_ip = snapshot.get('source_ip') or '198.51.100.200'
        return {
            'status': 'simulated',
            'result': f'Simulated IP block recorded for {source_ip}.',
            'source_ip': source_ip,
        }

    return {
        'status': 'recorded',
        'result': f'Action {action_type} recorded.',
    }


def evaluate_alert_rules_for_threat(threat: ThreatDetection, acting_user_id: int | None = None) -> list[dict]:
    if not threat or not threat.organization_id:
        return []

    matching_rules = (
        AlertRule.query
        .filter_by(organization_id=threat.organization_id, is_active=True)
        .order_by(AlertRule.id.asc())
        .all()
    )

    matches: list[dict] = []
    for rule in matching_rules:
        if not evaluate_rule_match(rule, threat):
            continue

        rule.trigger_count = (rule.trigger_count or 0) + 1
        action_metadata = _build_action_metadata(rule, threat)
        log_payload = {
            'alert_rule_id': rule.id,
            'alert_rule_name': rule.name,
            'action_type': rule.action_type,
            'action_status': action_metadata.get('status'),
            'action_result': action_metadata.get('result'),
            'threat_id': threat.id,
            'threat_type': threat.threat_type.value if threat.threat_type else None,
            'condition': {
                'field': rule.condition_field,
                'operator': rule.condition_operator,
                'value': rule.condition_value,
            },
        }

        if action_metadata.get('source_ip'):
            log_payload['source_ip'] = action_metadata['source_ip']

        db.session.add(
            SecurityLog(
                organization_id=threat.organization_id,
                event_type='alert_rule_triggered',
                severity=threat.severity or ThreatSeverity.MEDIUM,
                source_ip=action_metadata.get('source_ip'),
                destination_ip=None,
                resource_id=(threat.affected_resources or [None])[0],
                description=f'Alert rule "{rule.name}" matched {threat.threat_type.value if threat.threat_type else "a threat"} and executed {rule.action_type}.',
                raw_data=log_payload,
            )
        )

        OperationalEventService.record_event(
            user_id=acting_user_id or 0,
            org_id=threat.organization_id,
            event_type='alert_rule_triggered',
            resource_type='alert_rule',
            resource_id=str(rule.id),
            details={
                'threat_id': threat.id,
                'action_type': rule.action_type,
                'action_status': action_metadata.get('status'),
            },
        )

        matches.append({
            'rule_id': rule.id,
            'rule_name': rule.name,
            'action_type': rule.action_type,
            'action_status': action_metadata.get('status'),
            'action_result': action_metadata.get('result'),
        })

    return matches
