from datetime import datetime
from app import db


# ---------------------------------------------------------------------------
# HOME EXPENSE CATEGORIES  –  Editable personal expense categories
# ---------------------------------------------------------------------------
class HomeExpenseCategory(db.Model):
    """Editable categories for personal/household expenses."""
    __tablename__ = 'home_expense_categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    icon = db.Column(db.String(10), default='📋')       # Emoji icon for display
    is_default = db.Column(db.Boolean, default=False)    # True for seeded defaults
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    expenses = db.relationship('HomeExpense', backref='category_ref', lazy=True)

    def __repr__(self):
        return f'<HomeExpenseCategory {self.name}>'


# ---------------------------------------------------------------------------
# HOME EXPENSES  –  Personal / household expense records
# ---------------------------------------------------------------------------
class HomeExpense(db.Model):
    """Lightweight personal/household expense records for the owner."""
    __tablename__ = 'home_expenses'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    amount = db.Column(db.Float, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('home_expense_categories.id'), nullable=False)
    description = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', foreign_keys=[created_by])

    def __repr__(self):
        return f'<HomeExpense ₹{self.amount} [{self.category_ref.name if self.category_ref else "?"}]>'


# ---------------------------------------------------------------------------
# SEED DEFAULTS  –  Call once to populate default categories
# ---------------------------------------------------------------------------
DEFAULT_CATEGORIES = [
    ('Grocery', '🛒'),
    ('Fuel', '⛽'),
    ('Household', '🏠'),
    ('Medical', '🏥'),
    ('Education', '📚'),
    ('Entertainment', '🎬'),
    ('Utilities', '💡'),
    ('Miscellaneous', '📋'),
]


def seed_home_expense_categories():
    """Insert default categories if they don't already exist."""
    for name, icon in DEFAULT_CATEGORIES:
        existing = HomeExpenseCategory.query.filter_by(name=name).first()
        if not existing:
            db.session.add(HomeExpenseCategory(name=name, icon=icon, is_default=True))
    db.session.commit()
