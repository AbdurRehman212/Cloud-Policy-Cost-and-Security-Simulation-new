# Cloud Simulator FYP — Copilot Instructions

## Project
Flask + React cloud simulation platform. AWS/Azure Digital Twin for learning.
Path: /home/abdur/cloud-simulator-fyp/

## Stack
- Backend: Flask 3.x, Python 3.11, SQLAlchemy, Flask-SocketIO, PostgreSQL
- Frontend: React 18, Redux Toolkit, Tailwind CSS, Recharts, Socket.IO-client
- AI: Claude Sonnet 4.6 via Amazon Bedrock (boto3)
- Entry: backend/run.py

## URL Prefixes (CRITICAL)
- Auth: /api/auth
- Resources: /api/resources
- Dashboard: /api/dashboard
- Security: /api/security
- Governance: /api/governance
- Cost: /api/cost
- Assistant: /api/assistant

## Rules
- Always run python3 -m py_compile after editing any .py file
- Always run flask db migrate + flask db upgrade after model changes
- Never use in-memory storage — always use SQLAlchemy models
- Socket.IO namespace is /metrics, rooms are org_{org_id}
- JWT required on all endpoints except /api/auth/login and /api/auth/register
- Status values are lowercase: running, pending, stopped, terminated

## Current Status
- Modules 1-4 working
- Security Groups added (Feature 1)
- Auto Scaling added (Feature 2)
- Storage Volumes in progress (Feature 3)
- Monitoring Alarms next (Feature 4)

## Protected Files
- backend/app/models/user.py
- backend/migrations/
- frontend/src/store/slices/authSlice.js
