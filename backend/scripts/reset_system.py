import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app, db
from sqlalchemy import text

app = create_app('development')
with app.app_context():
    print("Beginning system reset transaction...")
    db.session.begin()
    try:
        # Task 1 & 3: Safe bulk delete
        db.session.execute(text("DELETE FROM cost_records;"))
        db.session.execute(text("DELETE FROM audit_logs;"))
        db.session.execute(text("DELETE FROM threat_detections;"))
        db.session.execute(text("DELETE FROM security_logs;"))
        db.session.execute(text("DELETE FROM virtual_machines;"))
        db.session.execute(text("DELETE FROM databases;"))
        print("Bulk deleted VMs and related records.")
        
        # Task 5: Create clean baseline
        from app.models.organization import Organization
        from app.models.resources import VirtualMachine, ResourceStatus
        import random, string, datetime
        
        org = Organization.query.first()
        if org:
            suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
            vm = VirtualMachine(
                organization_id=org.id,
                name=f"baseline-vm-1",
                instance_id=f"i-{suffix}",
                instance_type="t2.medium",
                status=ResourceStatus.RUNNING,
                vcpu=2,
                memory_gb=4.0,
                storage_gb=8,
                private_ip=f"10.0.1.10",
                cpu_utilization=10.0,
                memory_utilization=20.0,
                hourly_rate=0.0464,
                total_runtime_hours=0.0,
                requests_per_second=50,
                workload_pattern="steady",
                launched_at=datetime.datetime.utcnow(),
            )
            db.session.add(vm)
            print("Baseline VM created.")
        
        # Task 2: Commit transaction
        db.session.commit()
        print("Transaction committed successfully.")
        
    except Exception as e:
        db.session.rollback()
        print(f"Error during reset, rolled back: {e}")
