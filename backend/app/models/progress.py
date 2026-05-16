from datetime import datetime
from app import db


class UserProgress(db.Model):
    """User progress and achievements tracking."""
    __tablename__ = 'user_progress'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    org_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    
    # Points and level
    total_points = db.Column(db.Integer, default=0)
    level = db.Column(db.Integer, default=1)
    
    # Achievements (stored as JSON)
    badges = db.Column(db.JSON, default=list)  # List of badge names earned
    scenarios_completed = db.Column(db.JSON, default=list)  # List of scenario IDs
    
    # Counters
    vms_created = db.Column(db.Integer, default=0)
    attacks_simulated = db.Column(db.Integer, default=0)
    policies_created = db.Column(db.Integer, default=0)
    
    # Login streak
    login_streak = db.Column(db.Integer, default=0)
    last_login = db.Column(db.DateTime)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='progress')
    organization = db.relationship('Organization', backref='user_progress')
    
    @property
    def level_title(self):
        """Return the title for the current level."""
        level_titles = {
            1: "Beginner",
            2: "Foundation",
            3: "Intermediate",
            4: "Advanced",
            5: "Architect",
            6: "Expert",
        }
        return level_titles.get(self.level, "Expert")

    @property
    def learning_stage(self):
        """Return a compact stage label for the learning journey."""
        if self.level <= 1:
            return "beginner"
        if self.level <= 2:
            return "foundation"
        if self.level <= 3:
            return "intermediate"
        return "advanced"
    
    @property
    def xp_to_next_level(self):
        """Return XP needed to reach the next level."""
        next_level = self.level + 1
        return next_level * 100 - self.total_points
    
    @property
    def xp_for_current_level(self):
        """Return XP earned for the current level."""
        return self.total_points - ((self.level - 1) * 100)
    
    def update_level(self):
        """Update level based on total points."""
        new_level = 1 + (self.total_points // 100)
        if new_level > 6:
            new_level = 6
        self.level = new_level
    
    def check_badge_conditions(self):
        """Check and return any new badges earned."""
        new_badges = []
        badges = self.badges or []
        
        # Cloud Starter: first VM created
        if self.vms_created >= 1 and "Cloud Starter" not in badges:
            new_badges.append("Cloud Starter")
        
        # Security Aware: first attack simulated
        if self.attacks_simulated >= 1 and "Security Aware" not in badges:
            new_badges.append("Security Aware")
        
        # Policy Writer: first policy created
        if self.policies_created >= 1 and "Policy Writer" not in badges:
            new_badges.append("Policy Writer")
        
        # FinOps Beginner: first budget created (tracked via policies_created for now)
        if self.policies_created >= 1 and "FinOps Beginner" not in badges:
            new_badges.append("FinOps Beginner")
        
        # Lab Graduate: first scenario completed
        if len(self.scenarios_completed or []) >= 1 and "Lab Graduate" not in badges:
            new_badges.append("Lab Graduate")
        
        # Power User: 10 VMs created
        if self.vms_created >= 10 and "Power User" not in badges:
            new_badges.append("Power User")
        
        # Security Expert: 5 attacks simulated
        if self.attacks_simulated >= 5 and "Security Expert" not in badges:
            new_badges.append("Security Expert")
        
        # Architecture Pro: 3 scenarios completed
        if len(self.scenarios_completed or []) >= 3 and "Architecture Pro" not in badges:
            new_badges.append("Architecture Pro")
        
        return new_badges
    
    def to_dict(self):
        """Convert to dictionary for API response."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'org_id': self.org_id,
            'total_points': self.total_points,
            'level': self.level,
            'level_title': self.level_title,
            'learning_stage': self.learning_stage,
            'xp_to_next_level': self.xp_to_next_level,
            'xp_for_current_level': self.xp_for_current_level,
            'badges': self.badges or [],
            'scenarios_completed': self.scenarios_completed or [],
            'vms_created': self.vms_created,
            'attacks_simulated': self.attacks_simulated,
            'policies_created': self.policies_created,
            'login_streak': self.login_streak,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
