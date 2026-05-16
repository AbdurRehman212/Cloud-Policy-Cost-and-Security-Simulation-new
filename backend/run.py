#!/usr/bin/env python3
"""
Cloud Policy, Cost and Security Simulator - Main Entry Point
Final Year Project 2026
SZABIST University Islamabad
"""
import eventlet

eventlet.monkey_patch()

import os
from dotenv import load_dotenv
from app import create_app, db, socketio
from app.models import *
from app.data_sources.real_datasets import dataset_catalog

load_dotenv()
# Create app instance
app = create_app(os.getenv('FLASK_ENV', 'development'))
@app.shell_context_processor
def make_shell_context():
    """Make database models available in shell."""
    return {
        'db': db,
        'User': User,
        'Organization': Organization,
        'VirtualMachine': VirtualMachine,
        'Database': Database,
        'ThreatDetection': ThreatDetection,
        'CostRecord': CostRecord,
        'Policy': Policy
    }
@app.cli.command()
def init_db():
    """Initialize database with tables."""
    db.create_all()
    print("Database initialized successfully!")
@app.cli.command()
def seed_data():
    """Validate that real datasets are present."""
    availability = dataset_catalog.list_available_files()
    if not any(availability.values()):
        print("No real datasets found.")
        print("Place staged real dataset exports under backend/data/finops and backend/data/security.")
        return
    print("Real datasets discovered:")
    for key, files in availability.items():
        print(f"- {key}: {len(files)} file(s)")
        for path in files:
            print(f"  - {path}")
@app.cli.command()
def train_models():
    """Smoke-test the real-data-backed intelligence modules."""
    from app.ai_models.threat_detector import threat_detector
    from app.ai_models.cost_forecaster import cost_forecaster

    security_frame = dataset_catalog.load_security_frame()
    if not security_frame.empty:
        trained = threat_detector.train_from_frame(security_frame)
        print("Threat detector:", "trained from real dataset" if trained else "using heuristic mode")
    else:
        print("Threat detector: no security dataset found; using heuristic mode")

    finops_frame = dataset_catalog.load_finops_frame()
    if not finops_frame.empty:
        forecast = cost_forecaster.forecast(finops_frame, days_ahead=7)
        print(f"Cost forecaster: loaded {len(finops_frame)} records and produced {len(forecast)} forecast point(s)")
    else:
        print("Cost forecaster: no FinOps dataset found; using current DB history only")

    print("Real-data smoke test complete.")
if __name__ == '__main__':
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║     Cloud Policy, Cost and Security Simulator                ║
    ║     Final Year Project 2026 - SZABIST University             ║
    ║                                                              ║
    ║     Team Members:                                            ║
    ║     - Maryam Shahzad (2212396)                               ║
    ║     - M. Abdur Rehman Khan (2212399)                         ║
    ║     - Wasfa Nauman Bhatti (2312462)                          ║
    ║                                                              ║
    ║     Supervisor: Mr. Hasnain Tahir                            ║
    ╚══════════════════════════════════════════════════════════════╝
    """)
    # Run with SocketIO for real-time updates
    # debug=False and use_reloader=False are CRITICAL to ensure only ONE process runs.
    socketio.run(
        app,
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=False,
        use_reloader=False,
        log_output=True
    )
