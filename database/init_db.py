from werkzeug.security import generate_password_hash

from app import app, db, User

def init_database():
    with app.app_context():
        # Create all tables
        db.create_all()
        
        # Create sample admin user
        if not User.query.first():
            admin = User(
                username='admin',
                email='admin@expensio.com',
                password_hash=generate_password_hash('admin123')
            )
            db.session.add(admin)
            db.session.commit()
            print("Database initialized successfully.")
            print("Sample user created: admin / admin123")
        else:
            print("Database already initialized.")

if __name__ == '__main__':
    init_database()
