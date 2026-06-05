from app import create_app, db, bcrypt
from app.models import User

app = create_app()

with app.app_context():
    existing_user = User.query.filter_by(username='admin').first()
    if existing_user:
        print("Admin user already exists. Updating password to 'admin'.")
        existing_user.password_hash = bcrypt.generate_password_hash('admin').decode('utf-8')
    else:
        print("Creating new admin user...")
        hashed_password = bcrypt.generate_password_hash('admin').decode('utf-8')
        admin_user = User(
            username='admin',
            password_hash=hashed_password,
            role='Admin',
            is_active=True
        )
        db.session.add(admin_user)
    
    db.session.commit()
    print("Admin credentials created successfully! Username: admin | Password: admin")
