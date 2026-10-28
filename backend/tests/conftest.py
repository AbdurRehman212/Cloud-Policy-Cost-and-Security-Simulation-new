import os
import sys

import pytest
from flask_jwt_extended import create_access_token

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db  # noqa: E402
from app.models.organization import Organization, OrganizationMember  # noqa: E402
from app.models.resources import ResourceStatus, VirtualMachine  # noqa: E402
from app.models.user import User  # noqa: E402


@pytest.fixture()
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _user(email):
    user = User(email=email, password_hash='x', first_name='T', last_name=email.split('@')[0])
    db.session.add(user)
    db.session.flush()
    return user


def _org(name, owner):
    org = Organization(name=name, slug=name.lower(), owner_id=owner.id)
    db.session.add(org)
    db.session.flush()
    return org


@pytest.fixture()
def world(app):
    """Two organizations; org A has owner/admin/viewer, org B has its own owner."""
    owner, admin, viewer, other = (_user(f'{n}@t.io') for n in ('owner', 'admin', 'viewer', 'other'))
    org_a, org_b = _org('OrgA', owner), _org('OrgB', other)
    for user, role in ((owner, 'owner'), (admin, 'admin'), (viewer, 'viewer')):
        db.session.add(OrganizationMember(organization_id=org_a.id, user_id=user.id, role=role))
    db.session.add(OrganizationMember(organization_id=org_b.id, user_id=other.id, role='owner'))
    db.session.commit()

    def headers(user):
        return {'Authorization': f'Bearer {create_access_token(identity=user.id)}'}

    return {
        'org_a': org_a.id, 'org_b': org_b.id,
        'owner': headers(owner), 'admin': headers(admin),
        'viewer': headers(viewer), 'other': headers(other),
        'owner_id': owner.id,
    }


def make_vm(org_id, name, **kwargs):
    defaults = dict(
        organization_id=org_id, name=name, instance_id=f'i-{name}', instance_type='t2.micro',
        status=ResourceStatus.RUNNING, cpu_utilization=50.0, memory_utilization=50.0, hourly_rate=0.0116,
    )
    defaults.update(kwargs)
    vm = VirtualMachine(**defaults)
    db.session.add(vm)
    db.session.commit()
    return vm
