"""Operational Activity Timeline - Persistent learning history tracker.

Tracks user actions, scaling events, security incidents, cost optimizations,
and lab milestones for the learning timeline.
"""

from datetime import datetime
from typing import Any

from app import db


class ActivityTimeline:
    """Tracks operational learning history per user/org."""

    @staticmethod
    def record_activity(user_id: int, org_id: int, activity_type: str,
                    details: dict[str, Any] | None = None) -> dict:
        """Record an activity in the timeline."""
        from app.models.audit import AuditLog

        try:
            action = activity_type.replace('_', ' ').title()

            # Create audit log entry as persistent record
            audit = AuditLog(
                organization_id=org_id,
                user_id=user_id,
                action=action,
                resource_type=activity_type.split('_')[0] if '_' in activity_type else activity_type,
                details=details or {},
                timestamp=datetime.utcnow(),
            )
            db.session.add(audit)
            db.session.commit()

            return {
                'id': audit.id,
                'type': activity_type,
                'timestamp': audit.timestamp.isoformat(),
                'recorded': True,
            }
        except Exception as e:
            db.session.rollback()
            return {
                'type': activity_type,
                'timestamp': datetime.utcnow().isoformat(),
                'recorded': False,
                'error': str(e),
            }

    @staticmethod
    def get_recent_activities(org_id: int, limit: int = 20) -> list[dict]:
        """Get recent activities for an organization."""
        from app.models.audit import AuditLog

        try:
            activities = (
                AuditLog.query
                .filter_by(organization_id=org_id)
                .order_by(AuditLog.timestamp.desc())
                .limit(limit)
                .all()
            )

            return [
                {
                    'id': a.id,
                    'type': a.action,
                    'resource_type': a.resource_type,
                    'timestamp': a.timestamp.isoformat() if a.timestamp else None,
                    'status': 'completed',
                }
                for a in activities
            ]
        except Exception:
            return []

    @staticmethod
    def get_learning_milestones(org_id: int) -> list[dict]:
        """Get learning milestones based on activity history."""
        from app.models.resources import VirtualMachine, Database
        from app.models.progress import UserProgress

        milestones = []

        try:
            # Count VMs created
            vm_count = VirtualMachine.query.filter_by(
                organization_id=org_id
            ).filter(
                VirtualMachine.status != 'terminated'
            ).count()

            if vm_count >= 1:
                milestones.append({
                    'id': 'first_vm',
                    'title': 'Compute Foundations',
                    'description': f'Created {vm_count} compute instance(s)',
                    'completed': True,
                    'timestamp': None,
                })

            # Check security groups
            from app.models.resources import SecurityGroup
            sg_count = SecurityGroup.query.filter_by(org_id=org_id).count()
            if sg_count >= 1:
                milestones.append({
                    'id': 'security_group',
                    'title': 'Network Security',
                    'description': f'Configured {sg_count} security group(s)',
                    'completed': True,
                })

            # Check budgets
            from app.models.cost import Budget
            budget_count = Budget.query.filter_by(organization_id=org_id).count()
            if budget_count >= 1:
                milestones.append({
                    'id': 'budget',
                    'title': 'Cost Governance',
                    'description': f'Set {budget_count} budget(s)',
                    'completed': True,
                })

            return milestones
        except Exception:
            return milestones


# Singleton
activity_timeline = ActivityTimeline()