from app import db, app
from models import User, Room, Expense, RoomMember, PersonalExpense
import datetime

def init_database():
    with app.app_context():
        # Create all tables
        db.create_all()
        
        # Create sample admin user
        if not User.query.first():
            admin = User(
                username='admin',
                email='admin@expensio.com',
                password_hash='hashed_password_here'  # You'll hash this properly
            )
            db.session.add(admin)
            db.session.commit()
            print("✅ Database initialized successfully!")
            print("👤 Sample user created: admin / password")

if __name__ == '__main__':
    init_database()