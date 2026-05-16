from __future__ import annotations

from datetime import datetime

from app import db
from app.ai_models.policy_engine import policy_engine
from app.models.governance import AuditLog, ComplianceCheck, Policy, PolicyStatus
from app.models.resources import Database, VirtualMachine


class GovernanceEngine:
    """Backend-owned deterministic governance compiler and evaluator."""

    @staticmethod
    def compile_policy_text(policy_text: str) -> dict:
        return policy_engine.parse_policy(policy_text)

    @staticmethod
    def evaluate_org_policies(org_id: int, actor_user_id: int | None = None) -> dict:
        policies = (
            Policy.query
            .filter_by(organization_id=org_id, status=PolicyStatus.ACTIVE)
            .order_by(Policy.created_at.asc(), Policy.id.asc())
            .all()
        )
        resources = GovernanceEngine._load_resources(org_id)

        checked_at = datetime.utcnow()
        total_checks = 0
        compliant_checks = 0
        violations_found = 0
        policy_results = []
        recent_violations = []

        for policy in policies:
            compiled = policy.compiled_rule or {}
            rule = compiled.get('fields', compiled)
            applicable_resources = GovernanceEngine._filter_resources(resources, rule)
            policy_total = len(applicable_resources)
            policy_compliant = 0
            policy_violations = []

            for resource in applicable_resources:
                evaluation = policy_engine.evaluate_resource(rule, resource)
                is_compliant = bool(evaluation.get('compliant'))

                check = ComplianceCheck(
                    policy_id=policy.id,
                    resource_id=resource.get('instance_id') or str(resource.get('id')),
                    resource_type=resource.get('resource_kind') or resource.get('type') or 'resource',
                    checked_at=checked_at,
                    is_compliant=is_compliant,
                    violation_details=evaluation,
                    remediation_applied=False,
                    remediation_details=None,
                )
                db.session.add(check)

                total_checks += 1
                if is_compliant:
                    compliant_checks += 1
                    policy_compliant += 1
                    continue

                violations_found += 1
                violation_record = {
                    'policy_id': policy.id,
                    'policy_name': policy.name,
                    'resource_id': check.resource_id,
                    'resource_type': check.resource_type,
                    'violations': evaluation.get('violations', []),
                    'severity': policy.severity,
                }
                policy_violations.append(violation_record)
                recent_violations.append(violation_record)

            score = 100.0 if policy_total == 0 else round((policy_compliant / policy_total) * 100, 2)
            policy_results.append(
                {
                    'policy_id': policy.id,
                    'policy_name': policy.name,
                    'policy_type': policy.policy_type,
                    'resources_evaluated': policy_total,
                    'compliant_resources': policy_compliant,
                    'violations_found': len(policy_violations),
                    'compliance_score': score,
                    'violations': policy_violations,
                }
            )

        overall_score = 100.0 if total_checks == 0 else round((compliant_checks / total_checks) * 100, 2)
        summary = {
            'checked_at': checked_at.isoformat(),
            'org_id': org_id,
            'organization_id': org_id,
            'policies_checked': len(policies),
            'resources_evaluated': total_checks,
            'compliant_resources': compliant_checks,
            'violations_found': violations_found,
            'compliance_score': overall_score,
        }

        GovernanceEngine._record_audit_event(
            org_id=org_id,
            user_id=actor_user_id,
            action='policy_evaluated',
            resource_type='policy',
            resource_id=None,
            new_values=summary,
        )

        db.session.commit()

        return {
            **summary,
            'policy_results': policy_results,
            'results': recent_violations,
        }

    @staticmethod
    def get_recent_checks(org_id: int, limit: int = 100) -> list[dict]:
        checks = (
            ComplianceCheck.query
            .join(Policy, ComplianceCheck.policy_id == Policy.id)
            .filter(Policy.organization_id == org_id)
            .order_by(ComplianceCheck.checked_at.desc(), ComplianceCheck.id.desc())
            .limit(limit)
            .all()
        )
        return [check.to_dict() for check in checks]

    @staticmethod
    def _load_resources(org_id: int) -> list[dict]:
        vms = VirtualMachine.query.filter_by(organization_id=org_id).all()
        databases = Database.query.filter_by(organization_id=org_id).all()
        return [vm.to_dict() for vm in vms] + [database.to_dict() for database in databases]

    @staticmethod
    def _filter_resources(resources: list[dict], rule: dict) -> list[dict]:
        resource_type = rule.get('resource_type')
        if not resource_type:
            return resources
        return [
            resource for resource in resources
            if (resource.get('resource_kind') or resource.get('type')) == resource_type
        ]

    @staticmethod
    def _record_audit_event(
        org_id: int,
        user_id: int | None,
        action: str,
        resource_type: str | None,
        resource_id: str | None,
        new_values: dict | None = None,
        old_values: dict | None = None,
    ) -> None:
        audit = AuditLog(
            organization_id=org_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            timestamp=datetime.utcnow(),
            old_values=old_values,
            new_values=new_values or {},
            compliance_relevant=True,
        )
        db.session.add(audit)


governance_engine = GovernanceEngine()
