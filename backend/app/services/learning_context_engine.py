"""Learning Context Engine - Generates contextual feedback for user actions.

Provides KodeKloud/A Cloud Guru-style learning feedback after important
user actions, explaining the cloud equivalent, cost impact, and
operational significance.
"""

from dataclasses import dataclass
from typing import Any


# AWS/Azure equivalent mapping for instance types
INSTANCE_EQUIVALENTS = {
    "t2.micro": {
        "aws": "t2.micro - General purpose (1 vCPU, 1GiB RAM)",
        "azure": "B1s - Burstable virtual machine",
        "description": "Entry-level compute, ideal for learning and development",
        "monthly_cost_estimate": 8.47,
    },
    "t2.small": {
        "aws": "t2.small - General purpose (1 vCPU, 2GiB RAM)",
        "azure": "B1ms - Burstable virtual machine",
        "description": "Light workload compute for development/testing",
        "monthly_cost_estimate": 16.94,
    },
    "t2.medium": {
        "aws": "t2.medium - General purpose (2 vCPU, 4GiB RAM)",
        "azure": "B2s - Burstable virtual machine",
        "description": "Medium compute for production workloads",
        "monthly_cost_estimate": 33.88,
    },
    "t2.large": {
        "aws": "t2.large - General purpose (2 vCPU, 8GiB RAM)",
        "azure": "B2ms - Burstable virtual machine",
        "description": "High compute for production with more memory",
        "monthly_cost_estimate": 67.76,
    },
    "t2.xlarge": {
        "aws": "t2.xlarge - General purpose (4 vCPU, 16GiB RAM)",
        "azure": "B4ms - Burstable virtual machine",
        "description": "Large compute for memory-intensive workloads",
        "monthly_cost_estimate": 135.52,
    },
}

DATABASE_EQUIVALENTS = {
    "PostgreSQL": {
        "aws": "Amazon RDS for PostgreSQL",
        "azure": "Azure Database for PostgreSQL - Flexible server",
        "description": "Enterprise-grade PostgreSQL with managed backups",
        "monthly_cost_estimate": 18.25,
    },
    "MySQL": {
        "aws": "Amazon RDS for MySQL",
        "azure": "Azure Database for MySQL - Flexible server",
        "description": "Enterprise-grade MySQL with managed backups",
        "monthly_cost_estimate": 14.60,
    },
    "MongoDB": {
        "aws": "Amazon DocumentDB (MongoDB compatible)",
        "azure": "Azure Cosmos DB for MongoDB",
        "description": "Document database for flexible schema data",
        "monthly_cost_estimate": 21.90,
    },
}


@dataclass
class LearningContext:
    """Structured learning feedback for an action."""
    action: str
    title: str
    summary: str
    cloud_equivalent: str
    azure_equivalent: str
    cost_impact: str
    operational_meaning: str
    optimization_insight: str | None
    learning_explanation: str
    severity: str = "info"  # info, warning, success


class LearningContextService:
    """Generates contextual learning feedback for platform actions."""

    @staticmethod
    def for_vm_created(instance_type: str, name: str, current_cost: float = 0,
                     total_vms: int = 0) -> LearningContext:
        """Generate learning context for VM creation."""
        eq = INSTANCE_EQUIVALENTS.get(instance_type, INSTANCE_EQUIVALENTS["t2.micro"])

        cost_estimate = eq["monthly_cost_estimate"]
        operational_note = (
            "This provision creates a new EC2-like instance that will incur hourly costs."
            if total_vms > 3
            else "Your first few VMs are building foundational infrastructure skills."
        )

        optimization = None
        if total_vms > 5:
            optimization = (
                f"You now have {total_vms} running instances. "
                "Consider using autoscaling to optimize costs during low utilization."
            )

        return LearningContext(
            action="vm_created",
            title=f"Created {instance_type} Instance",
            summary=f"Successfully provisioned {name} ({instance_type})",
            cloud_equivalent=eq["aws"],
            azure_equivalent=eq["azure"],
            cost_impact=f"Estimated ${cost_estimate:.2f}/month at constant use",
            operational_meaning=(
                "A new compute node is now available in your cloud workspace. "
                f"{operational_note}"
            ),
            optimization_insight=optimization,
            learning_explanation=(
                f"You've created an EC2-like VM. In AWS, this would be an EC2 instance. "
                f"This instance type has {eq['description']}. "
                "Try monitoring its CPU utilization to learn about instance sizing."
            ),
            severity="success",
        )

    @staticmethod
    def for_db_created(engine: str, name: str, current_cost: float = 0) -> LearningContext:
        """Generate learning context for database creation."""
        eq = DATABASE_EQUIVALENTS.get(engine, DATABASE_EQUIVALENTS["PostgreSQL"])

        return LearningContext(
            action="db_created",
            title=f"Created {engine} Database",
            summary=f"Successfully provisioned {name} ({engine})",
            cloud_equivalent=eq["aws"],
            azure_equivalent=eq["azure"],
            cost_impact=f"Estimated ${eq['monthly_cost_estimate']:.2f}/month",
            operational_meaning=(
                "A managed database is now provisioned. RDS handles backups, "
                "patching, and high availability automatically."
            ),
            optimization_insight=(
                "Consider enabling read replicas for read-heavy workloads to improve performance."
            ),
            learning_explanation=(
                f"You've created a managed {engine} database. In production AWS, this would "
                "be Amazon RDS, which handles database administration tasks. "
                f"{eq['description']}"
            ),
            severity="success",
        )

    @staticmethod
    def for_vm_deleted(name: str, cost_saved: float = 0,
                     remaining_vms: int = 0) -> LearningContext:
        """Generate learning context for VM deletion."""
        operational = (
            "Good cost management - stopping unused resources prevents bill shock."
            if remaining_vms == 0
            else f"You have {remaining_vms} instances remaining."
        )

        return LearningContext(
            action="vm_deleted",
            title="Terminated Compute Instance",
            summary=f"Successfully terminated {name}",
            cloud_equivalent="EC2 Instance Termination",
            azure_equivalent="Azure VM Deletion",
            cost_impact=f"Cost saving: ~${cost_saved:.2f}/month removed",
            operational_meaning=operational,
            optimization_insight=(
                None if remaining_vms > 0
                else "No running instances - perfect for stopping bill accumulation between labs."
            ),
            learning_explanation=(
                "Terminating resources is essential for cloud cost management. "
                "In production environments, always use termination protection "
                "for production instances and implement auto-terminate policies "
                "for development environments."
            ),
            severity="info",
        )

    @staticmethod
    def for_scaling_action(direction: str, current_count: int,
                          reason: str = "") -> LearningContext:
        """Generate learning context for scaling actions."""
        if direction == "scale_up":
            title = "Scaled Out Compute Capacity"
            summary = f"Added capacity: {current_count} instance(s) now running"
            cloud_eq = "EC2 Auto Scaling - Scale Out"
            cost_impact = f"~${current_count * 8.47:.2f}/month additional"
            learning = (
                "You initiated a scale-out event! In AWS, this resembles an Auto Scaling "
                "group responding to elevated CPU or request metrics. The platform will "
                "automatically distribute traffic across new instances."
            )
        else:
            title = "Scaled In Compute Capacity"
            summary = f"Reduced capacity: {current_count} instance(s) now running"
            cloud_eq = "EC2 Auto Scaling - Scale In"
            cost_impact = f"Cost reduced by ~$8.47/month"
            learning = (
                "You initiated a scale-in event! Reducing idle capacity saves costs. "
                "In production AWS, this would be an Auto Scaling group triggered "
                "by low utilization metrics."
            )

        return LearningContext(
            action=f"{direction}_action",
            title=title,
            summary=summary,
            cloud_equivalent=cloud_eq,
            azure_equivalent="Azure Virtual Machine Scale Sets",
            cost_impact=cost_impact,
            operational_meaning=(
                f"Capacity adjusted. Reason: {reason}" if reason
                else "Capacity adjusted based on utilization metrics."
            ),
            optimization_insight=(
                "Consider setting up autoscaling policies to automate this process."
            ),
            learning_explanation=learning,
            severity="warning" if direction == "scale_up" else "info",
        )

    @staticmethod
    def for_security_group_created(name: str, rules_count: int = 0) -> LearningContext:
        """Generate learning context for security group creation."""
        rules_note = (
            f"Currently has {rules_count} rule(s)." if rules_count > 0
            else "No rules configured - all traffic is blocked by default."
        )

        return LearningContext(
            action="sg_created",
            title="Created Security Group",
            summary=f"Created firewall rules: {name}",
            cloud_equivalent="AWS Security Group",
            azure_equivalent="Azure Network Security Group (NSG)",
            cost_impact="No additional cost (managed by cloud provider)",
            operational_meaning=(
                f"Network firewall created. {rules_note} Security groups "
                "act as virtual firewalls for your instances."
            ),
            optimization_insight=(
                "Best practice: Only allow necessary ports (80/443 for web) "
                "and restrict SSH (port 22) to specific IPs."
            ),
            learning_explanation=(
                "You've created a VPC security group! In AWS, security groups are "
                "stateful firewalls that control inbound and outbound traffic. "
                "They're essential for zero-trust network security."
            ),
            severity="success",
        )

    @staticmethod
    def for_budget_created(amount: float, alert_threshold: float = 80) -> LearningContext:
        """Generate learning context for budget creation."""
        alert_at = amount * (alert_threshold / 100)

        return LearningContext(
            action="budget_created",
            title="Created Cost Budget",
            summary=f"Budget limit: ${amount:.2f}/month",
            cloud_equivalent="AWS Budgets",
            azure_equivalent="Azure Cost Management Budgets",
            cost_impact="No direct cost - governance tool",
            operational_meaning=(
                f"Budget created. Alerts will trigger at ${alert_at:.2f} ({alert_threshold}% threshold)."
            ),
            optimization_insight=(
                "Set up multiple budgets for different resource categories "
                "(compute, storage, database) for granular cost control."
            ),
            learning_explanation=(
                "You've created a budget! In production, budgets help prevent "
                "unexpected charges. AWS Budgets can send alerts or triggers "
                "auto-remediation actions when limits are approached."
            ),
            severity="success",
        )

    @staticmethod
    def for_threat_detected(threat_type: str, severity: str = "medium") -> LearningContext:
        """Generate learning context for security threat detection."""
        severity_styles = {
            "critical": ("Critical Security Event", "red"),
            "high": ("High Severity Threat", "orange"),
            "medium": ("Security Warning", "yellow"),
            "low": ("Low Severity Alert", "blue"),
        }

        title, _ = severity_styles.get(severity, ("Security Alert", "yellow"))

        return LearningContext(
            action="threat_detected",
            title=title,
            summary=f"Detected: {threat_type}",
            cloud_equivalent="AWS GuardDuty / Security Hub Alert",
            azure_equivalent="Azure Defender / Security Center Alert",
            cost_impact="Alert - no direct cost change",
            operational_meaning=(
                f"Security monitoring detected {threat_type}. Review the flagged resources "
                "and take remediation action."
            ),
            optimization_insight=(
                "Review security group rules and consider implementing "
                "least-privilege network access."
            ),
            learning_explanation=(
                f"A security threat was detected! In production AWS, this would trigger "
                "GuardDuty or Security Hub alerts. Learning to respond to security "
                "events is crucial for cloud security roles."
            ),
            severity="warning",
        )

    @staticmethod
    def for_onboarding_step(step: str, total_steps: int,
                         completed: bool = True) -> LearningContext:
        """Generate learning context for onboarding progression."""
        step_descriptions = {
            "first_vm": "Your first compute instance",
            "observe_cost": "Cost monitoring",
            "trigger_scaling": "Autoscaling",
            "inspect_topology": "Network topology",
            "resolve_security": "Security remediation",
        }

        description = step_descriptions.get(step, step)

        if completed:
            title = f"Onboarding: {description}"
            summary = f"Completed step {total_steps}"
            learning = (
                f"Great progress! You've learned about {description}. "
                f"/{total_steps} steps completed. Continue building your cloud skills!"
            )
            severity = "success"
        else:
            title = f"Next: {description}"
            summary = f"Step {total_steps + 1} - {description}"
            learning = f"Ready to learn about {description}? This is core cloud infrastructure knowledge."
            severity = "info"

        return LearningContext(
            action="onboarding_progress",
            title=title,
            summary=summary,
            cloud_equivalent="AWS Learning Path",
            azure_equivalent="Azure Learning Path",
            cost_impact="Educational (no real costs)",
            operational_meaning="Guided lab progression",
            optimization_insight=None,
            learning_explanation=learning,
            severity=severity,
        )


# Singleton instance
learning_context_service = LearningContextService()