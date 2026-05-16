from datetime import datetime

from app import db


class ScenarioProgress(db.Model):
    __tablename__ = 'scenario_progress'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    org_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    scenario_id = db.Column(db.String(80), nullable=False, index=True)
    current_step = db.Column(db.Integer, default=0)
    completed = db.Column(db.Boolean, default=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    points_earned = db.Column(db.Integer, default=0)
    history = db.Column(db.JSON, default=list)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'org_id', 'scenario_id', name='uq_scenario_progress_user_org_scenario'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'org_id': self.org_id,
            'scenario_id': self.scenario_id,
            'current_step': self.current_step,
            'completed': self.completed,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'points_earned': self.points_earned,
        }
