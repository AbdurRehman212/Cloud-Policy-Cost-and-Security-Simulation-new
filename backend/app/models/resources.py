from datetime import datetime
from enum import Enum
from app import db


class ResourceStatus(Enum):
    """VM lifecycle states used throughout the simulation engine.

    Values stored in the DB are the .value strings so the column
    can be compared as plain VARCHAR (native_enum=False).

    Lifecycle state machine:
        PENDING (provisioning) → RUNNING
        RUNNING → OVERLOADED | SCALING | TERMINATED
        OVERLOADED → RUNNING | SCALING | TERMINATED
        SCALING    → RUNNING | TERMINATED
        TERMINATED is terminal

    STOPPED and FAILED are kept for backward-compat with existing DB rows.
    """
    # ── Active lifecycle states ────────────────────────────────────────────
    PENDING    = 'pending'      # alias: provisioning
    RUNNING    = 'running'
    OVERLOADED = 'overloaded'
    SCALING    = 'scaling'
    TERMINATED = 'terminated'
    # ── Legacy / compat states ─────────────────────────────────────────────
    STOPPED    = 'stopped'
    FAILED     = 'failed'

    @property
    def is_provisioning(self) -> bool:
        return self == ResourceStatus.PENDING

    @property
    def is_deletable(self) -> bool:
        """A VM is deletable only when it is NOT in the provisioning state."""
        return self != ResourceStatus.PENDING


vm_security_group_links = db.Table(
    'vm_security_group_links',
    db.Column('vm_id', db.Integer, db.ForeignKey('virtual_machines.id'), primary_key=True),
    db.Column('security_group_id', db.Integer, db.ForeignKey('security_groups.id'), primary_key=True),
)


class SecurityGroup(db.Model):
    """Virtual firewall security group attached to VMs."""
    __tablename__ = 'security_groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    org_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    rules = db.relationship(
        'SecurityGroupRule',
        back_populates='group',
        cascade='all, delete-orphan',
        lazy='select',
    )
    vms = db.relationship(
        'VirtualMachine',
        secondary=vm_security_group_links,
        back_populates='security_groups',
        lazy='select',
    )

    __table_args__ = (
        db.UniqueConstraint('org_id', 'name', name='uq_security_groups_org_name'),
    )

    def to_dict(self, include_rules=True):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'org_id': self.org_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'rule_count': len(self.rules),
            'vm_count': len(self.vms),
            'rules': [rule.to_dict() for rule in self.rules] if include_rules else [],
        }


class SecurityGroupRule(db.Model):
    """Inbound or outbound firewall rule for a security group."""
    __tablename__ = 'security_group_rules'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('security_groups.id'), nullable=False)
    direction = db.Column(db.String(20), nullable=False)  # inbound | outbound
    protocol = db.Column(db.String(20), nullable=False)  # TCP | UDP | ICMP | All
    port_range = db.Column(db.String(30), nullable=False)  # "22" or "80-443"
    source_cidr = db.Column(db.String(50), nullable=False)
    action = db.Column(db.String(20), nullable=False, default='allow')  # allow | deny
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    group = db.relationship('SecurityGroup', back_populates='rules')

    def to_dict(self):
        return {
            'id': self.id,
            'group_id': self.group_id,
            'direction': self.direction,
            'protocol': self.protocol,
            'port_range': self.port_range,
            'source_cidr': self.source_cidr,
            'action': self.action,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class VirtualMachine(db.Model):
    """Simulated Virtual Machine with full lifecycle state machine.

    States: pending (provisioning) → running → overloaded / scaling → terminated
    Deletion rule: VM must NOT be in PENDING state to be deleted.
    """
    __tablename__ = 'virtual_machines'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    instance_id = db.Column(db.String(50), unique=True, nullable=False)  # i-xxxxxxxx
    instance_type = db.Column(db.String(50), nullable=False)  # t2.micro, etc.
    status = db.Column(
        db.Enum(ResourceStatus, values_callable=lambda x: [e.value for e in x], native_enum=False),
        default=ResourceStatus.PENDING
    )
    # Specifications
    vcpu = db.Column(db.Integer, default=1)
    memory_gb = db.Column(db.Float, default=1.0)
    storage_gb = db.Column(db.Integer, default=8)
    # Networking
    private_ip = db.Column(db.String(15))
    public_ip = db.Column(db.String(15))
    subnet_id = db.Column(db.String(50))
    vpc_id = db.Column(db.String(50))
    subnet_type = db.Column(db.String(20), default='public')
    # Utilization Metrics (Real-time simulated)
    cpu_utilization = db.Column(db.Float, default=0.0)  # Percentage
    memory_utilization = db.Column(db.Float, default=0.0)  # Percentage
    disk_read_iops = db.Column(db.Float, default=0.0)
    disk_write_iops = db.Column(db.Float, default=0.0)
    network_in_mbps = db.Column(db.Float, default=0.0)
    network_out_mbps = db.Column(db.Float, default=0.0)
    # Metadata
    image_id = db.Column(db.String(50))  # AMI ID
    key_name = db.Column(db.String(100))
    security_groups = db.relationship(
        'SecurityGroup',
        secondary=vm_security_group_links,
        back_populates='vms',
        lazy='select',
    )
    tags = db.relationship('ResourceTag', backref='vm', lazy='dynamic')
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    launched_at = db.Column(db.DateTime)
    stopped_at = db.Column(db.DateTime)
    terminated_at = db.Column(db.DateTime)
    # Workload model
    requests_per_second = db.Column(db.Integer, default=50)
    workload_pattern = db.Column(db.String(20), default='steady')  # steady | spiky | diurnal
    # Cost tracking
    hourly_rate = db.Column(db.Float, nullable=False)
    total_runtime_hours = db.Column(db.Float, default=0.0)
    def calculate_current_cost(self):
        """Calculate cost based on runtime."""
        if self.status == ResourceStatus.RUNNING and self.launched_at:
            runtime = (datetime.utcnow() - self.launched_at).total_seconds() / 3600
            return (self.total_runtime_hours + runtime) * self.hourly_rate
        return self.total_runtime_hours * self.hourly_rate
    def to_dict(self):
        return {
            'resource_kind': 'vm',
            'id': self.id,
            'instance_id': self.instance_id,
            'name': self.name,
            'instance_type': self.instance_type,
            'status': self.status.value if self.status else None,
            'vcpu': self.vcpu,
            'memory_gb': self.memory_gb,
            'storage_gb': self.storage_gb,
            'private_ip': self.private_ip,
            'public_ip': self.public_ip,
            'cpu_utilization': round(self.cpu_utilization, 2),
            'memory_utilization': round(self.memory_utilization, 2),
            'disk_read_iops': round(self.disk_read_iops, 2),
            'disk_write_iops': round(self.disk_write_iops, 2),
            'network_in_mbps': round(self.network_in_mbps, 2),
            'network_out_mbps': round(self.network_out_mbps, 2),
            'hourly_rate': self.hourly_rate,
            'current_cost': round(self.calculate_current_cost(), 4),
            'requests_per_second': self.requests_per_second or 50,
            'workload_pattern': self.workload_pattern or 'steady',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'tags': [tag.to_dict() for tag in self.tags],
            'security_groups': [group.to_dict(include_rules=False) for group in self.security_groups],
        }


class Database(db.Model):
    """Simulated Database Instance."""
    __tablename__ = 'databases'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    instance_id = db.Column(db.String(50), unique=True, nullable=False)  # db-xxxxxxxx
    engine = db.Column(db.String(50), nullable=False)  # mysql, postgres, etc.
    engine_version = db.Column(db.String(20))
    instance_class = db.Column(db.String(50), nullable=False)  # db.t2.micro, etc.
    status = db.Column(
        db.Enum(ResourceStatus, values_callable=lambda x: [e.value for e in x], native_enum=False),
        default=ResourceStatus.PENDING
    )
    # Specifications
    allocated_storage_gb = db.Column(db.Integer, default=20)
    max_storage_gb = db.Column(db.Integer, default=100)
    # Connectivity
    endpoint = db.Column(db.String(255))
    port = db.Column(db.Integer, default=3306)
    master_username = db.Column(db.String(100))
    # Security
    publicly_accessible = db.Column(db.Boolean, default=False)
    storage_encrypted = db.Column(db.Boolean, default=False)
    vpc_security_groups = db.Column(db.JSON, default=list)
    tags = db.relationship('ResourceTag', backref='database', lazy='dynamic')
    # Performance Metrics
    cpu_utilization = db.Column(db.Float, default=0.0)
    memory_utilization = db.Column(db.Float, default=0.0)
    free_storage_space = db.Column(db.Float, default=0.0)
    read_iops = db.Column(db.Float, default=0.0)
    write_iops = db.Column(db.Float, default=0.0)
    database_connections = db.Column(db.Integer, default=0)
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    hourly_rate = db.Column(db.Float, nullable=False)
    total_runtime_hours = db.Column(db.Float, default=0.0)
    def to_dict(self):
        memory_utilization = min(100.0, max(0.0, round(self.cpu_utilization * 1.35 + self.database_connections * 0.65, 2)))
        network_in_mbps = max(0.0, round(self.database_connections * 0.75 + self.read_iops / 45, 2))
        network_out_mbps = max(0.0, round(self.database_connections * 0.55 + self.write_iops / 55, 2))
        disk_io_total = round(self.read_iops + self.write_iops, 2)
        return {
            'resource_kind': 'database',
            'id': self.id,
            'instance_id': self.instance_id,
            'name': self.name,
            'engine': self.engine,
            'instance_class': self.instance_class,
            'status': self.status.value if self.status else None,
            'allocated_storage_gb': self.allocated_storage_gb,
            'endpoint': self.endpoint,
            'publicly_accessible': self.publicly_accessible,
            'storage_encrypted': self.storage_encrypted,
            'cpu_utilization': round(self.cpu_utilization, 2),
            'memory_utilization': memory_utilization,
            'disk_read_iops': round(self.read_iops, 2),
            'disk_write_iops': round(self.write_iops, 2),
            'disk_io_total': disk_io_total,
            'network_in_mbps': network_in_mbps,
            'network_out_mbps': network_out_mbps,
            'database_connections': self.database_connections,
            'hourly_rate': self.hourly_rate,
            'current_cost': round(self.total_runtime_hours * self.hourly_rate, 4),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'tags': [tag.to_dict() for tag in self.tags],
        }


class ResourceTag(db.Model):
    """Tags for resources."""
    __tablename__ = 'resource_tags'
    id = db.Column(db.Integer, primary_key=True)
    vm_id = db.Column(db.Integer, db.ForeignKey('virtual_machines.id'))
    db_id = db.Column(db.Integer, db.ForeignKey('databases.id'))
    key = db.Column(db.String(128), nullable=False)
    value = db.Column(db.String(256))
    def to_dict(self):
        return {'key': self.key, 'value': self.value}


class NetworkInterface(db.Model):
    """Network interfaces for VMs."""
    __tablename__ = 'network_interfaces'
    id = db.Column(db.Integer, primary_key=True)
    vm_id = db.Column(db.Integer, db.ForeignKey('virtual_machines.id'), nullable=False)
    network_interface_id = db.Column(db.String(50), unique=True, nullable=False)
    subnet_id = db.Column(db.String(50))
    vpc_id = db.Column(db.String(50))
    private_ip = db.Column(db.String(15))
    public_ip = db.Column(db.String(15))
    status = db.Column(db.String(20))  # in-use, available


class VPC(db.Model):
    """Virtual Private Cloud for an organization."""
    __tablename__ = 'vpcs'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'))
    cidr_block = db.Column(db.String(20), default='10.0.0.0/16')
    region = db.Column(db.String(50), default='us-east-1')
    is_default = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    subnets = db.relationship('Subnet', backref='vpc', lazy='select', cascade='all, delete-orphan')

    def to_dict(self, include_subnets=True):
        data = {
            'id': self.id,
            'name': self.name,
            'organization_id': self.organization_id,
            'cidr_block': self.cidr_block,
            'region': self.region,
            'is_default': self.is_default,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_subnets:
            data['subnets'] = [s.to_dict() for s in self.subnets]
        return data


class Subnet(db.Model):
    """Subnet within a VPC."""
    __tablename__ = 'subnets'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    vpc_id = db.Column(db.Integer, db.ForeignKey('vpcs.id'))
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'))
    cidr_block = db.Column(db.String(20))
    subnet_type = db.Column(db.String(20), default='public')
    availability_zone = db.Column(db.String(20), default='us-east-1a')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'vpc_id': self.vpc_id,
            'organization_id': self.organization_id,
            'cidr_block': self.cidr_block,
            'subnet_type': self.subnet_type,
            'availability_zone': self.availability_zone,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
