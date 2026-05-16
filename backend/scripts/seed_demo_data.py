#!/usr/bin/env python3
"""Seed a local PostgreSQL demo account and starter organization data."""

import os
from datetime import datetime, timedelta

os.environ.setdefault('ENABLE_SIMULATION_THREADS', 'false')

from app import create_app, db
from app.models import (
    User,
    UserProfile,
    UserSettings,
    Organization,
    OrganizationMember,
    VirtualMachine,
    Database,
    ResourceTag,
    CostRecord,
    Policy,
    SecurityLog,
    ThreatDetection,
)
from app.models.resources import ResourceStatus
from app.models.governance import PolicyStatus
from app.models.security import ThreatSeverity, ThreatType


def get_or_create_user():
    user = User.query.filter_by(email='admin@cloud.local').first()
    if user is None:
        user = User(
            email='admin@cloud.local',
            first_name='Admin',
            last_name='User',
            is_active=True,
            email_verified=True,
            is_superadmin=True,
        )
        user.set_password('Admin1234')
        db.session.add(user)
        db.session.flush()

    user.is_active = True
    user.email_verified = True
    user.is_superadmin = True
    user.set_password('Admin1234')

    if user.profile is None:
        db.session.add(UserProfile(user_id=user.id, department='Platform', job_title='Administrator'))

    if user.settings is None:
        db.session.add(UserSettings(user_id=user.id, theme='light', default_view='grid'))

    return user


def get_or_create_org(user):
    org = Organization.query.filter_by(slug='cloud-policy-cost-security-demo').first()
    if org is None:
        org = Organization(
            name='Cloud Policy, Cost & Security Demo',
            slug='cloud-policy-cost-security-demo',
            description='Starter organization for end-to-end demo testing.',
            owner_id=user.id,
            billing_email='admin@cloud.local',
            max_resources=100,
        )
        db.session.add(org)
        db.session.flush()

    membership = OrganizationMember.query.filter_by(organization_id=org.id, user_id=user.id).first()
    if membership is None:
        db.session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role='owner'))

    return org


def seed_resources(org):
    if not VirtualMachine.query.filter_by(organization_id=org.id).first():
        vm = VirtualMachine(
            organization_id=org.id,
            name='demo-web-01',
            instance_id='i-demo-web01',
            instance_type='t2.medium',
            status=ResourceStatus.RUNNING,
            vcpu=2,
            memory_gb=4.0,
            storage_gb=40,
            private_ip='10.0.1.10',
            public_ip='203.0.113.10',
            subnet_id='subnet-demo-1',
            vpc_id='vpc-demo-1',
            cpu_utilization=64.2,
            memory_utilization=71.8,
            disk_read_iops=145.0,
            disk_write_iops=88.0,
            network_in_mbps=132.0,
            network_out_mbps=98.0,
            image_id='ami-demo-001',
            key_name='demo-key',

            hourly_rate=0.0464,
            total_runtime_hours=48.5,
            launched_at=datetime.utcnow() - timedelta(days=2),
        )
        db.session.add(vm)
        db.session.flush()
        db.session.add(ResourceTag(vm_id=vm.id, key='Environment', value='Development'))
        db.session.add(ResourceTag(vm_id=vm.id, key='Owner', value='Platform'))

    if not Database.query.filter_by(organization_id=org.id).first():
        database = Database(
            organization_id=org.id,
            name='demo-postgres-01',
            instance_id='db-demo-01',
            engine='postgres',
            engine_version='15',
            instance_class='db.t2.small',
            status=ResourceStatus.RUNNING,
            allocated_storage_gb=50,
            max_storage_gb=100,
            endpoint='demo-postgres.local',
            port=5432,
            master_username='admin',
            publicly_accessible=False,
            storage_encrypted=True,
            vpc_security_groups=['sg-demo-db'],
            cpu_utilization=38.5,
            free_storage_space=21.4,
            read_iops=260.0,
            write_iops=140.0,
            database_connections=18,
            hourly_rate=0.034,
            total_runtime_hours=48.5,
        )
        db.session.add(database)


def seed_cost_history(org):
    if not CostRecord.query.filter_by(organization_id=org.id).first():
        base_date = datetime.utcnow().date() - timedelta(days=6)
        for day_offset in range(7):
            day = base_date + timedelta(days=day_offset)
            vm_total = 0.0464 * 12
            db_total = 0.034 * 12
            total = round(vm_total + db_total + (day_offset * 1.15), 2)
            db.session.add(
                CostRecord(
                    organization_id=org.id,
                    resource_id='i-demo-web01',
                    resource_type='vm',
                    date=day,
                    hour=day_offset,
                    compute_cost=round(total * 0.72, 2),
                    storage_cost=round(total * 0.18, 2),
                    network_cost=round(total * 0.10, 2),
                    total_cost=total,
                    cpu_avg=55.0 + day_offset,
                    memory_avg=62.0 + day_offset,
                )
            )


def seed_governance(org, user):
    if not Policy.query.filter_by(organization_id=org.id).first():
        policy_rule = 'resource_type=vm; max_cpu=80; max_memory=85; tag=Environment:Development'
        db.session.add(
            Policy(
                organization_id=org.id,
                name='Demo VM Policy',
                description='Keep demo VMs inside safe utilization ranges.',
                natural_language_rule=policy_rule,
                compiled_rule={
                    'expression': policy_rule,
                    'fields': {
                        'type': 'custom',
                        'severity': 'medium',
                        'resource_type': 'vm',
                        'requires_encryption': False,
                        'requires_private_access': False,
                        'requires_public_block': False,
                        'required_tags': [{'key': 'Environment', 'value': 'Development'}],
                        'max_cpu': 80,
                        'max_memory': 85,
                        'max_network': None,
                    },
                },
                policy_type='compliance',
                auto_remediate=False,
                severity='medium',
                status=PolicyStatus.ACTIVE,
                created_by=user.id,
            )
        )


def seed_security(org):
    if not SecurityLog.query.filter_by(organization_id=org.id).first():
        db.session.add(
            SecurityLog(
                organization_id=org.id,
                event_type='traffic_spike',
                severity=ThreatSeverity.HIGH,
                source_ip='198.51.100.10',
                destination_ip='10.0.1.10',
                resource_id='i-demo-web01',
                description='Synthetic traffic spike from the demo dataset.',
                raw_data={'requests_per_minute': 6200, 'error_rate': 0.18},
            )
        )

    if not ThreatDetection.query.filter_by(organization_id=org.id).first():
        db.session.add(
            ThreatDetection(
                organization_id=org.id,
                threat_type=ThreatType.DDoS,
                severity=ThreatSeverity.HIGH,
                confidence_score=0.94,
                affected_resources=['i-demo-web01'],
                attack_vectors={'requests_per_minute': 6200, 'avg_latency_ms': 390},
                network_traffic_snapshot={'bytes_in': 2400000, 'bytes_out': 6900000},
                model_version='demo',
                detection_pattern='DDoS style traffic spike',
                status='active',
            )
        )


def main():
    app = create_app('development')
    with app.app_context():
        user = get_or_create_user()
        org = get_or_create_org(user)
        seed_resources(org)
        seed_cost_history(org)
        seed_governance(org, user)
        seed_security(org)
        db.session.commit()
        print(f'Seeded demo data for {user.email} in organization "{org.name}".')


if __name__ == '__main__':
    main()
