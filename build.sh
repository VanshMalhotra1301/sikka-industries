#!/usr/bin/env bash
# Render Build Script
set -o errexit   # exit on error

echo ">>> Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo ">>> Creating database tables..."
python -c "
from app import create_app, db
app = create_app('production')
with app.app_context():
    db.create_all()
    print('All tables created successfully.')
"

echo ">>> Seeding demo admin user (if not exists)..."
python -c "
from app import create_app, db, bcrypt
from app.models import User
app = create_app('production')
with app.app_context():
    existing = User.query.filter_by(username='admin').first()
    if not existing:
        hashed = bcrypt.generate_password_hash('admin123').decode('utf-8')
        admin = User(username='admin', password_hash=hashed, role='Admin', is_active=True)
        db.session.add(admin)
        db.session.commit()
        print('Demo admin created -> Username: admin | Password: admin123')
    else:
        print('Admin user already exists, skipping.')
"

echo ">>> Build complete!"
