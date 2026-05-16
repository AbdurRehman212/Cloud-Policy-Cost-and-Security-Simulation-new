from datetime import datetime, date
from app import db
class CostRecord(db.Model):
    """Hourly cost records."""
    __tablename__ = 'cost_records'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    resource_id = db.Column(db.String(50), nullable=False)  # VM or DB ID
    resource_type = db.Column(db.String(20), nullable=False)  # vm, database
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    date = db.Column(db.Date, default=date.today)
    hour = db.Column(db.Integer)  # 0-23
    # Cost breakdown
    compute_cost = db.Column(db.Float, default=0.0)
    storage_cost = db.Column(db.Float, default=0.0)
    network_cost = db.Column(db.Float, default=0.0)
    total_cost = db.Column(db.Float, default=0.0)
    # Utilization at time of recording
    cpu_avg = db.Column(db.Float)
    memory_avg = db.Column(db.Float)
    __table_args__ = (
        db.Index('idx_cost_org_date', 'organization_id', 'date'),
    )
class Budget(db.Model):
    """Budget configuration and tracking."""
    __tablename__ = 'budgets'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)  # Monthly budget
    period = db.Column(db.String(20), default='monthly')  # monthly, quarterly, yearly
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    # Alerts
    alert_threshold_1 = db.Column(db.Float, default=50.0)  # Percentage
    alert_threshold_2 = db.Column(db.Float, default=80.0)
    alert_threshold_3 = db.Column(db.Float, default=100.0)
    # Actions
    auto_shutdown_at_threshold = db.Column(db.Boolean, default=False)
    shutdown_threshold = db.Column(db.Float, default=100.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    def get_current_spend(self):
        """Calculate current period spend."""
        # This would query CostRecord for current period
        from sqlalchemy import func
        result = db.session.query(func.sum(CostRecord.total_cost)).filter(
            CostRecord.organization_id == self.organization_id,
            CostRecord.date >= self.start_date
        ).scalar()
        return result or 0.0
    def to_dict(self):
        current = self.get_current_spend()
        return {
            'id': self.id,
            'org_id': self.organization_id,
            'organization_id': self.organization_id,
            'name': self.name,
            'amount': self.amount,
            'current_spend': round(current, 2),
            'remaining': round(self.amount - current, 2),
            'percentage_used': round((current / self.amount) * 100, 2) if self.amount > 0 else 0,
            'alert_thresholds': {
                'warning': self.alert_threshold_1,
                'critical': self.alert_threshold_2,
                'exceeded': self.alert_threshold_3
            }
        }
class CostForecast(db.Model):
    """AI-generated cost forecasts."""
    __tablename__ = 'cost_forecasts'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    forecast_date = db.Column(db.Date, nullable=False)
    predicted_cost = db.Column(db.Float, nullable=False)
    confidence_lower = db.Column(db.Float)  # Lower bound
    confidence_upper = db.Column(db.Float)  # Upper bound
    model_version = db.Column(db.String(20))
    # Factors influencing forecast
    trend_factor = db.Column(db.Float)
    seasonal_factor = db.Column(db.Float)
    growth_rate = db.Column(db.Float)
    def to_dict(self):
        return {
            'org_id': self.organization_id,
            'organization_id': self.organization_id,
            'forecast_date': self.forecast_date.isoformat(),
            'predicted_cost': round(self.predicted_cost, 2),
            'confidence_range': [
                round(self.confidence_lower, 2) if self.confidence_lower else None,
                round(self.confidence_upper, 2) if self.confidence_upper else None
            ]
        }
