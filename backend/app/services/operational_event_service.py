"""Operational Event Service - Persistent operational event timeline.

Tracks real operational events chronologically using AuditLog.
Events persist independently of resource state.
"""

from datetime import datetime
from typing import Any

from app import db
from app.models.governance import AuditLog


# Event types for learning timeline
OPERATIONAL_EVENTS = {
    'vm_created': {
        'category': 'compute',
        'icon': '🖥️',
        'narrative': 'provisioned a compute instance',
    },
    'vm_deleted': {
        'category': 'compute',
        'icon': '🗑️',
        'narrative': 'terminated a compute instance',
    },
    'vm_started': {
        'category': 'compute',
        'icon': '▶️',
        'narrative': 'started a compute instance',
    },
    'vm_stopped': {
        'category': 'compute',
        'icon': '⏹️',
        'narrative': 'stopped a compute instance',
    },
    'vm_restarted': {
        'category': 'other',
        'icon': '🔄',
        'narrative': 'restarted a compute instance',
    },
    'db_created': {
        'category': 'other',
        'icon': '🗄️',
        'narrative': 'provisioned a database instance',
    },
    'db_started': {
        'category': 'other',
        'icon': '▶️',
        'narrative': 'started a database instance',
    },
    'db_stopped': {
        'category': 'other',
        'icon': '⏹️',
        'narrative': 'stopped a database instance',
    },
    'db_restarted': {
        'category': 'other',
        'icon': '🔄',
        'narrative': 'restarted a database instance',
    },
    'db_deleted': {
        'category': 'other',
        'icon': '🗑️',
        'narrative': 'terminated a database instance',
    },
    'scale_out': {
        'category': 'scaling',
        'icon': '📈',
        'narrative': 'scaled out capacity',
    },
    'scale_in': {
        'category': 'scaling',
        'icon': '📉',
        'narrative': 'scaled in capacity',
    },
    'autoscale_triggered': {
        'category': 'scaling',
        'icon': '⚡',
        'narrative': 'autoscaling triggered',
    },
    'security_group_created': {
        'category': 'security',
        'icon': '🛡️',
        'narrative': 'created a security group',
    },
    'security_group_updated': {
        'category': 'security',
        'icon': '🔐',
        'narrative': 'updated security group rules',
    },
    'budget_created': {
        'category': 'cost',
        'icon': '💰',
        'narrative': 'established a budget',
    },
    'policy_created': {
        'category': 'governance',
        'icon': '📜',
        'narrative': 'created a governance policy',
    },
    'policy_updated': {
        'category': 'governance',
        'icon': '📝',
        'narrative': 'updated a governance policy',
    },
    'policy_deleted': {
        'category': 'governance',
        'icon': '🗑️',
        'narrative': 'deleted a governance policy',
    },
    'policy_evaluated': {
        'category': 'governance',
        'icon': '✅',
        'narrative': 'evaluated governance compliance',
    },
    'budget_exceeded': {
        'category': 'cost',
        'icon': '⚠️',
        'narrative': 'budget threshold exceeded',
    },
    'threat_detected': {
        'category': 'security',
        'icon': '🚨',
        'narrative': 'security threat detected',
    },
    'alert_rule_created': {
        'category': 'security',
        'icon': '🔔',
        'narrative': 'created an alert rule',
    },
    'alert_rule_updated': {
        'category': 'security',
        'icon': '🛠️',
        'narrative': 'updated an alert rule',
    },
    'alert_rule_deleted': {
        'category': 'security',
        'icon': '🗑️',
        'narrative': 'deleted an alert rule',
    },
    'alert_rule_triggered': {
        'category': 'security',
        'icon': '🚨',
        'narrative': 'triggered an alert rule',
    },
    'threat_mitigated': {
        'category': 'security',
        'icon': '✅',
        'narrative': 'threat mitigated',
    },
    'topology_viewed': {
        'category': 'exploration',
        'icon': '🔍',
        'narrative': 'explored infrastructure topology',
    },
    'cost_analyzed': {
        'category': 'exploration',
        'icon': '📊',
        'narrative': 'analyzed cost breakdown',
    },
    'lab_started': {
        'category': 'learning',
        'icon': '📚',
        'narrative': 'started a learning lab',
    },
    'lab_completed': {
        'category': 'learning',
        'icon': '🎓',
        'narrative': 'completed a learning lab',
    },
}


class OperationalEventService:
    """Persistent operational event tracking."""

    @staticmethod
    def record_event(
        user_id: int,
        org_id: int,
        event_type: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> int | None:
        """Record a persistent operational event."""
        event_config = OPERATIONAL_EVENTS.get(event_type, {})

        try:
            audit = AuditLog(
                organization_id=org_id,
                user_id=user_id,
                action=event_type,
                resource_type=resource_type or event_type.split('_')[0] if '_' in event_type else event_type,
                resource_id=resource_id,
                timestamp=datetime.utcnow(),
                new_values=details or {},
            )
            db.session.add(audit)
            db.session.commit()

            return audit.id
        except Exception as e:
            db.session.rollback()
            return None

    @staticmethod
    def get_timeline(
        org_id: int,
        limit: int = 50,
        category: str | None = None,
    ) -> list[dict]:
        """Get chronological operational timeline events."""
        try:
            query = AuditLog.query.filter_by(organization_id=org_id)

            if category:
                # Filter by category by looking up event types
                category_types = [
                    k for k, v in OPERATIONAL_EVENTS.items()
                    if v.get('category') == category
                ]
                query = query.filter(AuditLog.action.in_(category_types))

            events = (
                query
                .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
                .limit(limit)
                .all()
            )

            events = list(reversed(events))

            timeline = []
            for event in events:
                config = OPERATIONAL_EVENTS.get(event.action, {})
                timeline.append({
                    'id': event.id,
                    'event_type': event.action,
                    'icon': config.get('icon', '📌'),
                    'narrative': config.get('narrative', event.action),
                    'category': config.get('category', 'other'),
                    'resource_type': event.resource_type,
                    'resource_id': event.resource_id,
                    'timestamp': event.timestamp.isoformat() if event.timestamp else None,
                    'details': event.new_values or {},
                    'user_id': event.user_id,
                })

            return timeline
        except Exception:
            return []

    @staticmethod
    def get_recent_by_category(
        org_id: int,
        category: str,
        limit: int = 10,
    ) -> list[dict]:
        """Get recent events by category."""
        category_types = [
            k for k, v in OPERATIONAL_EVENTS.items()
            if v.get('category') == category
        ]

        if not category_types:
            return []

        try:
            events = (
                AuditLog.query
                .filter_by(organization_id=org_id)
                .filter(AuditLog.action.in_(category_types))
                .order_by(AuditLog.timestamp.desc())
                .limit(limit)
                .all()
            )

            return [
                {
                    'id': e.id,
                    'event_type': e.action,
                    'timestamp': e.timestamp.isoformat() if e.timestamp else None,
                    'details': e.new_values or {},
                }
                for e in events
            ]
        except Exception:
            return []

    @staticmethod
    def get_scaling_events(org_id: int, limit: int = 20) -> list[dict]:
        """Get scaling-related events."""
        return OperationalEventService.get_recent_by_category(org_id, 'scaling', limit)

    @staticmethod
    def get_security_events(org_id: int, limit: int = 20) -> list[dict]:
        """Get security-related events."""
        return OperationalEventService.get_recent_by_category(org_id, 'security', limit)

    @staticmethod
    def get_cost_events(org_id: int, limit: int = 20) -> list[dict]:
        """Get cost-related events."""
        return OperationalEventService.get_recent_by_category(org_id, 'cost', limit)

    @staticmethod
    def get_learning_events(org_id: int, limit: int = 20) -> list[dict]:
        """Get learning-lab events."""
        return OperationalEventService.get_recent_by_category(org_id, 'learning', limit)

    @staticmethod
    def get_event_counts(org_id: int) -> dict:
        """Get event counts by category."""
        counts = {
            'total': 0,
            'compute': 0,
            'scaling': 0,
            'security': 0,
            'cost': 0,
            'exploration': 0,
            'learning': 0,
            'governance': 0,
        }

        try:
            for category in counts.keys():
                if category == 'total':
                    counts[category] = AuditLog.query.filter_by(
                        organization_id=org_id
                    ).count()
                else:
                    category_types = [
                        k for k, v in OPERATIONAL_EVENTS.items()
                        if v.get('category') == category
                    ]
                    if category_types:
                        counts[category] = AuditLog.query.filter_by(
                            organization_id=org_id
                        ).filter(AuditLog.action.in_(category_types)).count()
        except Exception:
            pass

        return counts


# Singleton
operational_event_service = OperationalEventService()
