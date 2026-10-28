# Cloud Policy, Cost and Security Simulator

## Project Overview
Cloud simulator for learning cloud infrastructure management - provision VMs, configure networking, detect security threats, track costs, and practice governance policies through interactive scenarios.

**Final Year Project 2026** - SZABIST University Islamabad

**Team:**
- Maryam Shahzad (2212396)
- M. Abdur Rehman Khan (2212399)
- Wasfa Nauman Bhatti (2312462)

**Supervisor:** Mr. Hasnain Tahir

## Tech Stack

### Backend
- **Framework:** Flask 3.x with Flask-SocketIO for real-time updates
- **Database:** PostgreSQL (primary), SQLAlchemy ORM
- **Cache/Queue:** Redis for sessions and real-time metrics
- **AI/ML:** Pandas, scikit-learn for threat detection and cost forecasting
- **Key Libraries:** Flask-JWT-Extended, Flask-Migrate, Python-dotenv

### Frontend
- **Framework:** React 18.x with React Router 6
- **State Management:** Redux Toolkit
- **UI:** TailwindCSS 3.x with @headlessui/react, @heroicons/react
- **Charts:** Recharts, Chart.js + react-chartjs-2
- **Real-time:** Socket.io-client
- **HTTP:** Axios

### Infrastructure
- **Database:** PostgreSQL at `postgresql://<user>:<password>@localhost/cloud_simulator  (set via DATABASE_URL in backend/.env; never commit)`
- **Cache:** Redis at `redis://localhost:6379/0`
- **Runtime:** Python 3.x with eventlet for async I/O

## Architecture

### Core Pipeline
```
Authentication → Organization → Scenario → User Action → Simulation → Metrics → Explanation → Feedback → Progression
```

### Multi-Tenant Model
```
User (account) → OrganizationMember (role-based) → Organization (tenant)
                              ↓
                    VirtualMachine / Database / SecurityGroup / VPC / Subnet
```

### Request Flow
1. User authenticates via JWT token
2. Selects organization context via membership
3. Performs actions (provision/scale/terminate resources)
4. Simulation engine models workload and resource state
5. Control plane computes MAPE metrics and autoscaling decisions
6. Dashboard aggregates real-time snapshots
7. Learning engine tracks progress and provides recommendations

## Database Models

### Core Entities
- **User** - Authentication, profile, settings, memberships
- **Organization** - Multi-tenant container, billing, limits
- **OrganizationMember** - User-Organization relationship with roles (owner/admin/member/viewer)
- **UserProgress** - Learning scenario tracking per user/org

### Resource Entities
- **VirtualMachine** - Simulated EC2-like VMs with lifecycle states (PENDING → RUNNING → OVERLOADED | SCALING | TERMINATED)
- **Database** - Simulated RDS-like databases
- **SecurityGroup** - Firewall rules for VMs
- **SecurityGroupRule** - Individual rules (direction, protocol, port, source_cidr, action)
- **VPC** - Virtual Private Cloud with CIDR block
- **Subnet** - Public/private subnets with availability zones
- **ResourceTag** - Key-value tags for resources

### Governance Entities
- **Policy** - Governance policies (naming, tagging, security, cost, compliance)
- **ComplianceCheck** - Policy enforcement results
- **AuditLog** - Immutable audit trail for all actions

### Cost Entities
- **CostRecord** - Time-series cost tracking
- **Budget** - Budget limits with alerts

### Security Entities
- **ThreatDetection** - Security threat records with severity (CRITICAL/HIGH/MEDIUM)

### Learning Entities
- **Scenario** - Learning scenarios with objectives and tasks
- **UserScenarioProgress** - Per-user scenario completion tracking

## API Routes

### Authentication
- `POST /api/auth/register` - User registration
- `POST /api/auth/login` - JWT login
- `POST /api/auth/refresh` - Token refresh

### Organization
- `GET /api/org` - List user's organizations
- `POST /api/org` - Create organization
- `GET /api/org/<id>` - Get organization details
- `PUT /api/org/<id>` - Update organization
- `DELETE /api/org/<id>` - Delete organization
- `POST /api/org/<id>/invite` - Invite members

### Resources (VM/Database)
- `GET /api/resources` - List all resources for org
- `POST /api/resources/vm` - Provision VM
- `POST /api/resources/database` - Provision database
- `PUT /api/resources/vm/<id>` - Update VM
- `DELETE /api/resources/vm/<id>` - Terminate VM

### Simulation
- `GET /api/simulation/state` - Get simulation state
- `POST /api/simulation/start` - Start simulation
- `POST /api/simulation/stop` - Stop simulation
- `GET /api/simulation/metrics` - Get real-time metrics

### Dashboard
- `GET /api/dashboard/summary` - Dashboard aggregation (resources, security, costs, learning)
- `GET /api/dashboard/cost-by-resource` - Per-resource cost breakdown

### Security
- `GET /api/security/threats` - List active threats
- `POST /api/security/scan` - Trigger threat scan
- `GET /api/security/score` - Security score

### Cost
- `GET /api/cost/summary` - Cost summary
- `GET /api/cost/history` - Cost history
- `POST /api/cost/budget` - Create budget

### Governance
- `GET /api/governance/policies` - List policies
- `POST /api/governance/policies` - Create policy
- `GET /api/governance/compliance` - Compliance status

### Learning
- `GET /api/learning/scenarios` - List available scenarios
- `GET /api/learning/scenarios/<id>` - Get scenario details
- `POST /api/learning/scenarios/<id>/start` - Start scenario
- `GET /api/learning/progress` - Learning progress
- `GET /api/learning/recommendations` - AI recommendations

### Network
- `GET /api/network/topology` - Network topology view

### Canvas
- `GET /api/canvas/architecture` - Architecture diagram data

## Key Services

### control_plane.py
MAPE (Monitor-Analyze-Plan-Execute) control loop:
- Computes organization snapshots every 2 seconds
- Aggregates CPU/memory via EMA smoothing
- Implements autoscaling with cooldown (15s) and hysteresis
- Threshold: 60% target utilization, 1s queue alarm
- Max 100 VMs per org (also capped by the organization quota), max 2 VMs per scale step

### simulation_engine.py
CloudSim-style discrete-event simulation:
- Per-context tick-based execution
- Request scheduler (round-robin)
- Queue modeling with capacity constraints
- Latency and dropped request tracking

### resource_simulator.py
In-memory VM state management:
- VM states: RUNNING, PENDING, OVERLOADED, SCALING, TERMINATED
- Workload patterns: steady, spiky, diurnal
- Metrics: CPU %, memory %, disk I/O, network throughput

### learning_engine.py
Adaptive learning system:
- Role mapping (viewer → student, admin → admin, owner → organization)
- Level progression (Beginner → Architect)
- Scenario recommendations based on progress
- Learning profile generation with coaching hints

### scoring_engine.py
Decision scoring for learning:
- Weights: action = 0.4, outcome = 0.3, efficiency = 0.2, speed = 0.1
- Criteria: correct_action, optimal_choice, resource_efficiency, completion_time

### infrastructure.py
Topology aggregation:
- VM → Host → DataCenter hierarchy
- Utilization aggregations at each level

### cost_performance_engine.py
Cost-performance trade-off analysis:
- Instance type recommendations based on workload
- Cost optimization suggestions

### operational_insights_engine.py
Operational intelligence:
- Anomaly detection in metrics
- Operation recommendations

### topology_mini_map.py
Dashboard topology visualization component for frontend integration

## Frontend Pages

- **Login/Register** - Authentication
- **Dashboard** - Main dashboard with metrics, topology mini-map, learning insights
- **Resources** - VM/Database management
- **Scenarios** - Learning scenario browser
- **ScenarioDetail** - Individual scenario with tasks
- **Security** - Threat monitoring
- **CostManagement** - Cost tracking and budgets
- **Governance** - Policy management
- **Membership** - Team management
- **Settings** - User settings
- **Organization** - Org management
- **Network** - Network topology
- **Canvas** - Architecture diagram

## Configuration

### Environment Variables
```bash
FLASK_ENV=development
DATABASE_URL=postgresql://<user>:<password>@localhost/cloud_simulator  # set in backend/.env, never commit
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=<secret>
JWT_SECRET_KEY=<jwt-secret>
PORT=5000
```

### Pricing (Simulated AWS-like)
- t2.micro: $0.0116/hr
- t2.small: $0.023/hr
- t2.medium: $0.0464/hr
- t2.large: $0.0928/hr

## Running the Project

### Backend
```bash
cd backend
source venv/bin/activate
python run.py
```

### Frontend
```bash
cd frontend
npm start
```

## Key Patterns

### JWT Authentication
- Access token: 1 hour expiry
- Refresh token: 7 day expiry
- Organization ID passed as query param

### Resource Lifecycle
```
PENDING (provisioning) → RUNNING → OVERLOADED | SCALING | TERMINATED
```
- VM cannot be deleted while PENDING

### Multi-Tenancy
- All queries filtered by OrganizationMember
- RBAC via role field (owner/admin/member/viewer)

### Real-time Updates
- SocketIO events for simulation metrics
- Dashboard polling for snapshots (2s TTL cache)