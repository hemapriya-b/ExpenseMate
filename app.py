from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import csv
import io
import os
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def _database_uri():
    uri = (
        os.getenv('DATABASE_URL')
        or os.getenv('POSTGRES_URL')
        or os.getenv('POSTGRES_PRISMA_URL')
        or 'sqlite:///expensio.db'
    )
    if uri.startswith('postgres://'):
        uri = uri.replace('postgres://', 'postgresql://', 1)
    return uri

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = _database_uri()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# ========== MODELS (Define them here to avoid circular imports) ==========
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships will be defined after all models

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    room_code = db.Column(db.String(50), unique=True, nullable=False)
    budget = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class RoomMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), default='Other')
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    paid_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

class ExpenseShare(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(db.Integer, db.ForeignKey('expense.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    share_amount = db.Column(db.Float, nullable=False)

class RoomActivity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    message = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class RoomNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PersonalExpense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), default='Other')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    budget_month = db.Column(db.String(7))  # YYYY-MM format

class PersonalBudget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    budget_month = db.Column(db.String(7), nullable=False)  # YYYY-MM format
    amount = db.Column(db.Float, default=0, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint('user_id', 'budget_month', name='unique_user_month_budget'),
    )

# Now define relationships
User.rooms = db.relationship('RoomMember', backref='member', lazy=True)
User.personal_expenses = db.relationship('PersonalExpense', backref='user', lazy=True)
User.personal_budgets = db.relationship('PersonalBudget', backref='user', lazy=True)
User.expenses_paid = db.relationship('Expense', foreign_keys='Expense.paid_by', backref='payer', lazy=True)
User.expense_shares = db.relationship('ExpenseShare', backref='share_user', lazy=True)
Room.expenses = db.relationship('Expense', backref='room', lazy=True)
Room.members = db.relationship('RoomMember', backref='room', lazy=True)
Room.activities = db.relationship('RoomActivity', backref='activity_room', lazy=True)
Room.notes = db.relationship('RoomNote', backref='note_room', lazy=True, cascade='all, delete-orphan')
Expense.shares = db.relationship('ExpenseShare', backref='expense', lazy=True, cascade='all, delete-orphan')
User.room_notes = db.relationship('RoomNote', backref='author', lazy=True)

# Ensure newly added tables exist even when app is imported (not only run as __main__).
with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))  # Fixed: Use db.session.get()

@app.context_processor
def inject_page_guide():
    guides = {
        'index': {
            'title': 'Welcome Guide',
            'intro': 'Expensio tracks shared room expenses and personal spending so you can see totals, balances, and budgets without manual math.',
            'steps': [
                'Create or join a room when expenses are shared with other people.',
                'Use personal expenses for your own monthly spending and budget tracking.',
                'Open charts or export when you want summaries outside the dashboard.'
            ],
            'tips': [
                'Rooms are best for trips, rent, office lunches, and any shared bill.',
                'Personal expenses stay private to your account.'
            ]
        },
        'login': {
            'title': 'Login Guide',
            'intro': 'Sign in with your username and password to access your rooms, personal expenses, budgets, charts, and exports.',
            'steps': [
                'Enter the username you used during signup.',
                'Enter your password and continue.',
                'After login, your dashboard shows your financial snapshot.'
            ],
            'tips': ['Use the sample account from the database initializer only for local testing.']
        },
        'signup': {
            'title': 'Signup Guide',
            'intro': 'Create an account so Expensio can keep your rooms, balances, and personal expenses separate from other users.',
            'steps': [
                'Choose a unique username and email.',
                'Set a password and confirm it.',
                'After signup, start by creating a room or adding personal expenses.'
            ],
            'tips': ['Your username is shown inside rooms when you pay, owe, or receive money.']
        },
        'dashboard': {
            'title': 'Dashboard Guide',
            'intro': 'The dashboard is your quick overview: rooms, recent personal expenses, monthly budget, and your net room balance.',
            'steps': [
                'Total paid is money you directly paid in shared rooms.',
                'Your share is calculated from expense splits inside each room.',
                'Net balance means paid minus your share: positive means others owe you, negative means you owe others.'
            ],
            'tips': [
                'Use Edit Budget to set this month\'s personal spending limit.',
                'Enter a room to see exact who-pays-whom settlement instructions.'
            ]
        },
        'create_room': {
            'title': 'Create Room Guide',
            'intro': 'A room groups people and shared expenses, like a trip, flat, event, or office lunch.',
            'steps': [
                'Give the room a clear name people will recognize.',
                'Share the room code with people who should join.',
                'Set a budget if you want a spending progress bar for the room.'
            ],
            'tips': [
                'The creator becomes the room admin automatically.',
                'Room codes should be easy to share but hard enough to guess.'
            ]
        },
        'join_room': {
            'title': 'Join Room Guide',
            'intro': 'Join a room using the code shared by the room creator. The preview checks the real database before you submit.',
            'steps': [
                'Enter the room code exactly as shared.',
                'Room name is optional, but if you enter it, it must match the room.',
                'Check the preview for creator name and member count before joining.'
            ],
            'tips': [
                'If the preview says room not found, check the code first.',
                'Once joined, the room will appear on your dashboard.'
            ]
        },
        'view_room': {
            'title': 'Room Balance Guide',
            'intro': 'This room uses every expense and split to calculate who paid extra, who owes, and the fewest payments needed to settle up.',
            'steps': [
                'For each expense, Expensio records who paid and how the amount is split.',
                'Each member balance is total paid minus their assigned share.',
                'Positive balance means that person should receive money. Negative balance means that person should pay.',
                'Settlement Summary pairs people who owe with people who should receive, reducing many bills into simple transfers.'
            ],
            'tips': [
                'Example: if A paid Rs. 900 for three equal members, A paid Rs. 900 and A\'s share is Rs. 300, so A gets Rs. 600 back.',
                'If a balance shows Rs. 0.00, that member is already settled.'
            ]
        },
        'add_expense': {
            'title': 'Add Expense Guide',
            'intro': 'Add a shared expense to a room and choose exactly how it should be split among members.',
            'steps': [
                'Enter what was bought, the amount, payer, category, and date.',
                'Equal split divides the amount evenly among selected members.',
                'Percentage split uses each member\'s percentage and must total 100%.',
                'Custom split lets you type each member\'s exact share and must total the expense amount.'
            ],
            'tips': [
                'The payer can be different from the person entering the expense.',
                'After saving, room balances and settlement instructions update automatically.'
            ]
        },
        'personal_expense': {
            'title': 'Personal Expenses Guide',
            'intro': 'Personal expenses track your own spending and monthly budget. These entries do not affect room settlements.',
            'steps': [
                'Add expenses with amount, category, and date.',
                'The monthly budget compares current-month spending against your saved budget.',
                'Edit Budget saves your limit for the current month.',
                'Clear removes the budget limit but keeps your expenses.'
            ],
            'tips': [
                'Use categories consistently so charts stay meaningful.',
                'Budget progress is based only on this month\'s personal expenses.'
            ]
        },
        'charts': {
            'title': 'Charts Guide',
            'intro': 'Charts turn your personal expense history into category, monthly, and comparison insights.',
            'steps': [
                'Category charts show where your money is going.',
                'Monthly charts show spending trends over time.',
                'Range filters change which expenses are included in the insight cards.'
            ],
            'tips': ['If charts look empty, add personal expenses first.']
        },
        'export_page': {
            'title': 'Export Guide',
            'intro': 'Export downloads your expense data as CSV so it can be opened in spreadsheet tools.',
            'steps': [
                'Choose room export for shared room expenses.',
                'Choose personal export for your private expense log.',
                'Use date ranges when you only need a smaller personal report.'
            ],
            'tips': ['CSV files are useful for backups, accounting, or sharing summaries.']
        },
        'export_room': {
            'title': 'Room Export Guide',
            'intro': 'Room export downloads the selected room\'s shared expenses, including payer, category, date, and notes.',
            'steps': [
                'Only room members can export a room.',
                'The downloaded CSV can be opened in Excel, Numbers, or Google Sheets.'
            ],
            'tips': ['Use this after a trip or event to keep a final record.']
        },
        'export_personal': {
            'title': 'Personal Export Guide',
            'intro': 'Personal export downloads your own expense history for the selected date range.',
            'steps': [
                'Pick a range from the export page or URL.',
                'The CSV includes description, amount, category, and date.'
            ],
            'tips': ['Exports include only your personal expenses, not room expenses.']
        },
        'about': {
            'title': 'About Page Guide',
            'intro': 'This page explains what Expensio is for and how shared expense tracking works at a high level.',
            'steps': [
                'Read the workflow to understand rooms, expenses, splits, and settlements.',
                'Use the navigation bar when you are ready to try the app.'
            ],
            'tips': ['The room page has the most detailed explanation of balance logic.']
        },
        'not_found': {
            'title': 'Page Guide',
            'intro': 'This page was not found. Use the navigation bar to return to a working area of Expensio.',
            'steps': ['Go back to dashboard, rooms, charts, or personal expenses.'],
            'tips': ['If you followed an old link, the room or page may have been deleted.']
        },
        'server_error': {
            'title': 'Error Guide',
            'intro': 'Something went wrong while loading this page.',
            'steps': ['Try refreshing, then return to the dashboard if the error continues.'],
            'tips': ['Local development errors usually appear in the terminal logs.']
        }
    }

    default_guide = {
        'title': 'Page Guide',
        'intro': 'Use this guide for a quick explanation of what this page does and how the numbers should be read.',
        'steps': [
            'Follow the main action button on the page.',
            'Check totals and preview panels before saving changes.',
            'Use the dashboard when you want to return to the overall summary.'
        ],
        'tips': ['Each page in Expensio has a guide tailored to its main workflow.']
    }

    endpoint = request.endpoint or ''
    return {'page_guide': guides.get(endpoint, default_guide)}

def _room_members(room_id):
    return RoomMember.query.filter_by(room_id=room_id).all()

def _split_amounts(total_amount, member_ids, split_method, percentages, custom_amounts):
    if not member_ids:
        raise ValueError('No members to split with')
    if total_amount <= 0:
        raise ValueError('Amount must be greater than 0')

    if split_method == 'equal':
        equal_share = round(total_amount / len(member_ids), 2)
        shares = {uid: equal_share for uid in member_ids}
        remainder = round(total_amount - sum(shares.values()), 2)
        shares[member_ids[0]] = round(shares[member_ids[0]] + remainder, 2)
        return shares

    if split_method == 'percentage':
        pct_sum = round(sum(percentages.get(uid, 0) for uid in member_ids), 2)
        if abs(pct_sum - 100.0) > 0.01:
            raise ValueError('Percentages must add up to 100')
        shares = {}
        for uid in member_ids:
            shares[uid] = round(total_amount * (percentages.get(uid, 0) / 100.0), 2)
        remainder = round(total_amount - sum(shares.values()), 2)
        shares[member_ids[0]] = round(shares[member_ids[0]] + remainder, 2)
        return shares

    if split_method == 'custom':
        custom_sum = round(sum(custom_amounts.get(uid, 0) for uid in member_ids), 2)
        if abs(custom_sum - total_amount) > 0.01:
            raise ValueError('Custom amounts must add up to total amount')
        return {uid: round(custom_amounts.get(uid, 0), 2) for uid in member_ids}

    raise ValueError('Invalid split method')

def _compute_room_balances(room_id):
    members = _room_members(room_id)
    member_ids = [m.user_id for m in members]
    expenses = Expense.query.filter_by(room_id=room_id).order_by(Expense.date.desc()).all()

    paid_map = {uid: 0.0 for uid in member_ids}
    owed_map = {uid: 0.0 for uid in member_ids}

    for exp in expenses:
        if exp.paid_by in paid_map:
            paid_map[exp.paid_by] += exp.amount

        if exp.shares:
            for s in exp.shares:
                if s.user_id in owed_map:
                    owed_map[s.user_id] += s.share_amount
        elif member_ids:
            # Backward compatibility for old expenses without share rows.
            equal_share = exp.amount / len(member_ids)
            for uid in member_ids:
                owed_map[uid] += equal_share

    member_data = []
    for m in members:
        user = db.session.get(User, m.user_id)
        paid = round(paid_map.get(m.user_id, 0.0), 2)
        share = round(owed_map.get(m.user_id, 0.0), 2)
        balance = round(paid - share, 2)  # positive: gets back, negative: owes
        member_data.append({
            'user': user,
            'is_admin': m.is_admin,
            'paid': paid,
            'share': share,
            'balance': balance
        })

    return expenses, member_data

def _build_settlements(member_data):
    creditors = []
    debtors = []
    for m in member_data:
        if m['balance'] > 0.01:
            creditors.append([m['user'], round(m['balance'], 2)])
        elif m['balance'] < -0.01:
            debtors.append([m['user'], round(abs(m['balance']), 2)])

    settlements = []
    i = 0
    j = 0
    while i < len(debtors) and j < len(creditors):
        debtor_user, debt = debtors[i]
        creditor_user, credit = creditors[j]
        amount = round(min(debt, credit), 2)
        if amount > 0:
            settlements.append({
                'from_user': debtor_user,
                'to_user': creditor_user,
                'amount': amount
            })
        debt = round(debt - amount, 2)
        credit = round(credit - amount, 2)
        debtors[i][1] = debt
        creditors[j][1] = credit

        if debt <= 0.01:
            i += 1
        if credit <= 0.01:
            j += 1

    return settlements

def _range_start(range_key):
    now = datetime.utcnow()
    today = datetime(now.year, now.month, now.day)

    if range_key == 'week':
        return today - timedelta(days=today.weekday())
    if range_key == 'month':
        return datetime(now.year, now.month, 1)
    if range_key == 'quarter':
        return today - timedelta(days=90)
    if range_key == 'year':
        return datetime(now.year, 1, 1)
    return None

def _month_key(date=None):
    return (date or datetime.utcnow()).strftime('%Y-%m')

def _get_personal_budget(user_id, month_key=None):
    month_key = month_key or _month_key()
    budget = PersonalBudget.query.filter_by(
        user_id=user_id,
        budget_month=month_key
    ).first()
    return round(float(budget.amount or 0), 2) if budget else 0.0

def _set_personal_budget(user_id, amount, month_key=None):
    month_key = month_key or _month_key()
    budget = PersonalBudget.query.filter_by(
        user_id=user_id,
        budget_month=month_key
    ).first()
    if not budget:
        budget = PersonalBudget(user_id=user_id, budget_month=month_key, amount=0)
        db.session.add(budget)

    budget.amount = round(float(amount), 2)
    return budget

def _budget_progress_pct(spent, budget):
    if budget <= 0:
        return 0
    return min(int(round((spent / budget) * 100)), 100)

def _filter_personal_expenses(user_id, range_key='all'):
    query = PersonalExpense.query.filter_by(user_id=user_id)
    start = _range_start(range_key)
    if start:
        query = query.filter(PersonalExpense.date >= start)
    return query.order_by(PersonalExpense.date.asc()).all()

def _personal_chart_payload(expenses):
    categories = {}
    monthly_data = {}
    total_spending = 0.0

    for exp in expenses:
        amount = float(exp.amount or 0)
        category = exp.category or 'Other'
        month = exp.date.strftime('%b %Y')
        categories[category] = round(categories.get(category, 0.0) + amount, 2)
        monthly_data[month] = round(monthly_data.get(month, 0.0) + amount, 2)
        total_spending += amount

    top_category = 'N/A'
    top_amount = 0.0
    if categories:
        top_category = max(categories, key=categories.get)
        top_amount = categories[top_category]

    dates = [exp.date.date() for exp in expenses]
    day_count = max(((max(dates) - min(dates)).days + 1), 1) if dates else 0
    daily_average = round(total_spending / day_count, 2) if day_count else 0.0

    now = datetime.utcnow()
    current_month_key = now.strftime('%Y-%m')
    previous_month_date = datetime(now.year, now.month, 1) - timedelta(days=1)
    previous_month_key = previous_month_date.strftime('%Y-%m')

    current_month_total = round(sum(exp.amount for exp in expenses if exp.date.strftime('%Y-%m') == current_month_key), 2)
    previous_month_total = round(sum(exp.amount for exp in expenses if exp.date.strftime('%Y-%m') == previous_month_key), 2)
    last_three_months = [
        exp.amount for exp in expenses
        if exp.date >= (datetime(now.year, now.month, 1) - timedelta(days=90))
    ]
    three_month_average = round(sum(last_three_months) / 3, 2) if last_three_months else 0.0

    return {
        'categories': categories,
        'monthly_data': monthly_data,
        'insights': {
            'total_spending': round(total_spending, 2),
            'top_category': top_category,
            'top_amount': round(top_amount, 2),
            'daily_average': daily_average,
            'expense_count': len(expenses)
        },
        'comparison': {
            'current_month': current_month_total,
            'previous_month': previous_month_total,
            'three_month_average': three_month_average
        }
    }

# ========== AUTH ROUTES ==========
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=True)
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('auth/login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Validation
        if password != confirm_password:
            flash('Passwords do not match!', 'error')
            return redirect(url_for('signup'))
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('signup'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('signup'))
        
        # Create new user
        new_user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Account created successfully! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash('Error creating account. Please try again.', 'error')
            print(f"Error: {e}")
    
    return render_template('auth/signup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully', 'info')
    return redirect(url_for('login'))

# ========== DASHBOARD ROUTES ==========
@app.route('/dashboard')
@login_required
def dashboard():
    try:
        # Calculate user statistics
        user_rooms = RoomMember.query.filter_by(user_id=current_user.id).all()
        room_ids = [room.room_id for room in user_rooms]
        
        # Get all expenses in user's rooms
        expenses = Expense.query.filter(Expense.room_id.in_(room_ids)).all() if room_ids else []
        
        # Calculate totals based on actual split shares
        total_spent = sum(exp.amount for exp in expenses if exp.paid_by == current_user.id)
        total_share = 0.0
        for exp in expenses:
            user_share = next((s.share_amount for s in exp.shares if s.user_id == current_user.id), None)
            if user_share is not None:
                total_share += user_share
            elif room_ids:
                # Backward compatibility for old expenses without share rows.
                member_count = RoomMember.query.filter_by(room_id=exp.room_id).count()
                if member_count > 0:
                    total_share += exp.amount / member_count

        total_owed = max(total_spent - total_share, 0)
        net_balance = total_spent - total_share
        
        # Get user's rooms
        rooms = Room.query.filter(Room.id.in_(room_ids)).all() if room_ids else []
        
        # Get personal expenses
        personal_expenses = PersonalExpense.query.filter_by(
            user_id=current_user.id
        ).order_by(PersonalExpense.date.desc()).limit(5).all()
        
        # Simple monthly personal budget metrics
        now = datetime.utcnow()
        month_key = _month_key(now)
        monthly_personal_expenses = [
            exp for exp in PersonalExpense.query.filter_by(user_id=current_user.id).all()
            if exp.date.strftime('%Y-%m') == month_key
        ]
        monthly_spent = round(sum(exp.amount for exp in monthly_personal_expenses), 2)
        personal_budget = _get_personal_budget(current_user.id, month_key)
        budget_progress_pct = _budget_progress_pct(monthly_spent, personal_budget)

        return render_template('dashboard.html',
                             total_spent=round(total_spent, 2),
                             total_owed=round(total_owed, 2),
                             net_balance=round(net_balance, 2),
                             rooms=rooms,
                             personal_expenses=personal_expenses,
                             monthly_spent=monthly_spent,
                             personal_budget=personal_budget,
                             budget_progress_pct=budget_progress_pct)
    except Exception as e:
        print(f"Dashboard error: {e}")
        return render_template('dashboard.html',
                             total_spent=0,
                             total_owed=0,
                             net_balance=0,
                             rooms=[],
                             personal_expenses=[],
                             monthly_spent=0,
                             personal_budget=0,
                             budget_progress_pct=0)

# ========== ROOM ROUTES ==========
@app.route('/room/create', methods=['GET', 'POST'])
@login_required
def create_room():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        room_code = request.form.get('room_code')
        budget = float(request.form.get('budget', 0))
        
        new_room = Room(
            name=name,
            description=description,
            room_code=room_code,
            budget=budget,
            created_by=current_user.id
        )
        
        try:
            db.session.add(new_room)
            db.session.commit()
            
            # Add creator as room member
            member = RoomMember(
                room_id=new_room.id,
                user_id=current_user.id,
                is_admin=True
            )
            db.session.add(member)
            db.session.commit()
            
            flash(f'Room "{name}" created successfully!', 'success')
            return redirect(url_for('view_room', room_id=new_room.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating room: {str(e)}', 'error')
    
    return render_template('room/create.html')

@app.route('/room/join', methods=['GET', 'POST'])
@login_required
def join_room():
    if request.method == 'POST':
        room_name = (request.form.get('room_name') or '').strip()
        room_code = (request.form.get('room_code') or '').strip().upper()

        room_query = Room.query.filter_by(room_code=room_code)
        if room_name:
            room = room_query.filter(Room.name.ilike(room_name)).first()
        else:
            room = room_query.first()
        
        if room:
            # Check if already a member
            existing = RoomMember.query.filter_by(
                room_id=room.id,
                user_id=current_user.id
            ).first()
            
            if not existing:
                member = RoomMember(
                    room_id=room.id,
                    user_id=current_user.id,
                    is_admin=False
                )
                db.session.add(member)
                db.session.add(RoomActivity(
                    room_id=room.id,
                    message=f'{current_user.username} joined the room.'
                ))
                db.session.commit()
                flash(f'Joined room "{room.name}" successfully!', 'success')
            else:
                flash('You are already a member of this room', 'info')
            
            return redirect(url_for('view_room', room_id=room.id))
        else:
            flash('Invalid room code. Please check the code and try again.', 'error')
    
    return render_template('room/join.html')

@app.route('/room/preview')
@login_required
def room_preview():
    room_code = (request.args.get('room_code') or '').strip().upper()
    room_name = (request.args.get('room_name') or '').strip()

    if not room_code:
        return jsonify({'found': False, 'message': 'Please enter a room code'}), 400

    room_query = Room.query.filter_by(room_code=room_code)
    if room_name:
        room = room_query.filter(Room.name.ilike(room_name)).first()
    else:
        room = room_query.first()

    if not room:
        return jsonify({
            'found': False,
            'message': 'No room found with those details'
        }), 404

    creator = db.session.get(User, room.created_by)
    member_count = RoomMember.query.filter_by(room_id=room.id).count()
    already_member = RoomMember.query.filter_by(
        room_id=room.id,
        user_id=current_user.id
    ).first() is not None

    return jsonify({
        'found': True,
        'name': room.name,
        'creator': creator.username if creator else 'Unknown',
        'members': member_count,
        'status': 'Already joined' if already_member else 'Active',
        'already_member': already_member
    })

@app.route('/room/<int:room_id>')
@login_required
def view_room(room_id):
    try:
        room = Room.query.get_or_404(room_id)
        
        # Check if user is member
        member = RoomMember.query.filter_by(
            room_id=room_id,
            user_id=current_user.id
        ).first()
        
        if not member:
            flash('You are not a member of this room', 'error')
            return redirect(url_for('dashboard'))
        
        expenses, member_data = _compute_room_balances(room_id)
        settlements = _build_settlements(member_data)
        room_members = _room_members(room_id)
        activities = RoomActivity.query.filter_by(room_id=room_id).order_by(
            RoomActivity.created_at.desc()
        ).limit(20).all()
        room_notes = RoomNote.query.filter_by(room_id=room_id).order_by(
            RoomNote.created_at.desc()
        ).limit(6).all()
        
        return render_template('room/view.html',
                             room=room,
                             expenses=expenses,
                             members=member_data,
                             is_admin=member.is_admin,
                             settlements=settlements,
                             activities=activities,
                             room_members=room_members,
                             room_notes=room_notes)
    except Exception as e:
        flash(f'Error loading room: {str(e)}', 'error')
        return redirect(url_for('dashboard'))

@app.route('/room/<int:room_id>/notes', methods=['POST'])
@login_required
def add_room_note(room_id):
    room = Room.query.get_or_404(room_id)
    membership = RoomMember.query.filter_by(room_id=room_id, user_id=current_user.id).first()
    if not membership:
        flash('You are not a member of this room.', 'error')
        return redirect(url_for('dashboard'))

    content = (request.form.get('content') or '').strip()
    if not content:
        flash('Note cannot be empty.', 'error')
        return redirect(url_for('view_room', room_id=room.id))
    if len(content) > 500:
        flash('Note must be 500 characters or fewer.', 'error')
        return redirect(url_for('view_room', room_id=room.id))

    db.session.add(RoomNote(
        room_id=room_id,
        user_id=current_user.id,
        content=content
    ))
    db.session.add(RoomActivity(
        room_id=room_id,
        message=f'{current_user.username} posted a room note.'
    ))
    db.session.commit()
    flash('Note posted to the room.', 'success')
    return redirect(url_for('view_room', room_id=room.id))

@app.route('/room/<int:room_id>/leave', methods=['POST'])
@login_required
def leave_room(room_id):
    room = Room.query.get_or_404(room_id)
    membership = RoomMember.query.filter_by(room_id=room_id, user_id=current_user.id).first()
    if not membership:
        flash('You are not a member of this room.', 'error')
        return redirect(url_for('dashboard'))

    room_members = _room_members(room_id)
    if membership.is_admin and len(room_members) > 1:
        # Transfer admin to another member before leaving.
        replacement = next((m for m in room_members if m.user_id != current_user.id), None)
        if replacement:
            replacement.is_admin = True

    db.session.delete(membership)
    db.session.add(RoomActivity(
        room_id=room_id,
        message=f'{current_user.username} exited the room.'
    ))
    remaining = RoomMember.query.filter_by(room_id=room_id).count()
    if remaining <= 0:
        expense_ids = [exp.id for exp in Expense.query.filter_by(room_id=room_id).all()]
        if expense_ids:
            ExpenseShare.query.filter(ExpenseShare.expense_id.in_(expense_ids)).delete(synchronize_session=False)
        RoomNote.query.filter_by(room_id=room_id).delete(synchronize_session=False)
        RoomActivity.query.filter_by(room_id=room_id).delete(synchronize_session=False)
        Expense.query.filter_by(room_id=room_id).delete(synchronize_session=False)
        db.session.delete(room)
    db.session.commit()

    flash(f'You exited "{room.name}".', 'info')
    return redirect(url_for('dashboard'))

@app.route('/room/<int:room_id>/delete', methods=['POST'])
@login_required
def delete_room(room_id):
    room = Room.query.get_or_404(room_id)
    membership = RoomMember.query.filter_by(room_id=room_id, user_id=current_user.id).first()
    if not membership or not membership.is_admin:
        flash('Only room admin can delete the room.', 'error')
        return redirect(url_for('view_room', room_id=room_id))

    # Delete dependent data in safe order.
    expense_ids = [exp.id for exp in Expense.query.filter_by(room_id=room_id).all()]
    if expense_ids:
        ExpenseShare.query.filter(ExpenseShare.expense_id.in_(expense_ids)).delete(synchronize_session=False)
    Expense.query.filter_by(room_id=room_id).delete(synchronize_session=False)
    RoomNote.query.filter_by(room_id=room_id).delete(synchronize_session=False)
    RoomActivity.query.filter_by(room_id=room_id).delete(synchronize_session=False)
    RoomMember.query.filter_by(room_id=room_id).delete(synchronize_session=False)
    db.session.delete(room)
    db.session.commit()

    flash('Room deleted successfully.', 'success')
    return redirect(url_for('dashboard'))

# ========== EXPENSE ROUTES ==========
@app.route('/expense/add/<int:room_id>', methods=['GET', 'POST'])
@login_required
def add_expense(room_id):
    room = Room.query.get_or_404(room_id)
    member = RoomMember.query.filter_by(room_id=room_id, user_id=current_user.id).first()
    if not member:
        flash('You are not a member of this room.', 'error')
        return redirect(url_for('dashboard'))
    room_members = _room_members(room_id)
    
    if request.method == 'POST':
        description = (request.form.get('description') or '').strip()
        amount = float(request.form.get('amount') or 0)
        category = request.form.get('category')
        split_method = request.form.get('split_method', 'equal')
        notes = request.form.get('notes')
        paid_by = int(request.form.get('paid_by') or current_user.id)
        date_str = request.form.get('date')
        expense_date = datetime.strptime(date_str, '%Y-%m-%d') if date_str else datetime.utcnow()
        member_ids = [m.user_id for m in room_members]

        if paid_by not in member_ids:
            flash('Selected payer is not in this room.', 'error')
            return redirect(url_for('add_expense', room_id=room_id))

        percentages = {}
        custom_amounts = {}
        posted_ids = request.form.getlist('split_user_id[]')
        posted_pcts = request.form.getlist('split_percentage[]')
        posted_customs = request.form.getlist('split_amount[]')
        for idx, user_id_str in enumerate(posted_ids):
            uid = int(user_id_str)
            if uid not in member_ids:
                continue
            try:
                percentages[uid] = float(posted_pcts[idx]) if idx < len(posted_pcts) else 0.0
            except (ValueError, TypeError):
                percentages[uid] = 0.0
            try:
                custom_amounts[uid] = float(posted_customs[idx]) if idx < len(posted_customs) else 0.0
            except (ValueError, TypeError):
                custom_amounts[uid] = 0.0
        
        try:
            shares = _split_amounts(
                total_amount=amount,
                member_ids=member_ids,
                split_method=split_method,
                percentages=percentages,
                custom_amounts=custom_amounts
            )

            new_expense = Expense(
                description=description,
                amount=amount,
                category=category,
                room_id=room_id,
                paid_by=paid_by,
                date=expense_date,
                notes=notes
            )
            db.session.add(new_expense)
            db.session.flush()

            for uid, share_amount in shares.items():
                db.session.add(ExpenseShare(
                    expense_id=new_expense.id,
                    user_id=uid,
                    share_amount=round(share_amount, 2)
                ))

            db.session.add(RoomActivity(
                room_id=room_id,
                message=f'{current_user.username} added expense "{description}" (₹{amount:.2f}).'
            ))
            db.session.commit()
            flash('Expense added successfully!', 'success')
            return redirect(url_for('view_room', room_id=room_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding expense: {str(e)}', 'error')
    
    return render_template('expenses/add.html', room=room, now=datetime.utcnow(), room_members=room_members)

@app.route('/expense/personal', methods=['GET', 'POST'])
@login_required
def personal_expense():
    if request.method == 'POST':
        try:
            description = (request.form.get('description') or '').strip()
            amount = float(request.form.get('amount') or 0)
            category = request.form.get('category') or 'Other'
            date_str = request.form.get('date')

            if not description:
                raise ValueError('Description is required')
            if amount <= 0:
                raise ValueError('Amount must be greater than 0')

            if date_str:
                date = datetime.strptime(date_str, '%Y-%m-%d')
            else:
                date = datetime.utcnow()
            
            new_expense = PersonalExpense(
                description=description,
                amount=amount,
                category=category,
                user_id=current_user.id,
                date=date,
                budget_month=date.strftime('%Y-%m')
            )
            
            db.session.add(new_expense)
            db.session.commit()
            flash('Personal expense added!', 'success')
            return redirect(url_for('personal_expense'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding expense: {str(e)}', 'error')
    
    # Get personal expenses
    expenses = PersonalExpense.query.filter_by(
        user_id=current_user.id
    ).order_by(PersonalExpense.date.desc()).all()
    
    # Calculate total
    total = sum(exp.amount for exp in expenses)
    category_totals = {}
    for exp in expenses:
        category_totals[exp.category] = category_totals.get(exp.category, 0) + exp.amount
    top_category = max(category_totals, key=category_totals.get) if category_totals else 'N/A'
    top_category_pct = 0
    if total > 0 and top_category in category_totals:
        top_category_pct = int(round((category_totals[top_category] / total) * 100))

    now = datetime.utcnow()
    month_key = _month_key(now)
    month_expenses = [exp for exp in expenses if exp.date.strftime('%Y-%m') == month_key]
    month_total = round(sum(exp.amount for exp in month_expenses), 2)
    month_count = len(month_expenses)
    month_avg = round((month_total / month_count), 2) if month_count else 0
    budget_limit = _get_personal_budget(current_user.id, month_key)
    budget_progress_pct = _budget_progress_pct(month_total, budget_limit)
    budget_remaining_pct = max(100 - budget_progress_pct, 0)
    
    return render_template(
        'expenses/personal.html',
        expenses=expenses,
        total=total,
        today_date=datetime.utcnow().strftime('%Y-%m-%d'),
        top_category=top_category,
        top_category_pct=top_category_pct,
        month_total=month_total,
        month_count=month_count,
        month_avg=month_avg,
        budget_limit=budget_limit,
        budget_progress_pct=budget_progress_pct,
        budget_remaining_pct=budget_remaining_pct
    )

@app.route('/budget/personal', methods=['POST'])
@login_required
def update_personal_budget():
    wants_json = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    try:
        raw_amount = request.form.get('amount')
        amount = float(raw_amount or 0)
        if amount < 0:
            raise ValueError('Budget amount cannot be negative')

        month_key = request.form.get('month') or _month_key()
        if len(month_key) != 7:
            raise ValueError('Invalid budget month')

        _set_personal_budget(current_user.id, amount, month_key)
        db.session.commit()

        message = 'Monthly budget cleared!' if amount == 0 else 'Monthly budget updated!'
        if wants_json:
            return jsonify({
                'success': True,
                'message': message,
                'amount': round(amount, 2)
            })

        flash(message, 'success')
    except Exception as e:
        db.session.rollback()
        if wants_json:
            return jsonify({'success': False, 'message': str(e)}), 400
        flash(f'Error updating budget: {str(e)}', 'error')

    return redirect(request.referrer or url_for('personal_expense'))

@app.route('/expense/personal/<int:expense_id>/edit', methods=['POST'])
@login_required
def edit_personal_expense(expense_id):
    expense = PersonalExpense.query.filter_by(
        id=expense_id,
        user_id=current_user.id
    ).first_or_404()

    try:
        description = (request.form.get('description') or '').strip()
        amount = float(request.form.get('amount') or 0)
        category = request.form.get('category') or 'Other'
        date_str = request.form.get('date')

        if not description:
            raise ValueError('Description is required')
        if amount <= 0:
            raise ValueError('Amount must be greater than 0')

        expense.description = description
        expense.amount = amount
        expense.category = category
        expense.date = datetime.strptime(date_str, '%Y-%m-%d') if date_str else datetime.utcnow()
        expense.budget_month = expense.date.strftime('%Y-%m')

        db.session.commit()
        flash('Personal expense updated!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating expense: {str(e)}', 'error')

    return redirect(url_for('personal_expense'))

@app.route('/expense/personal/<int:expense_id>/delete', methods=['POST'])
@login_required
def delete_personal_expense(expense_id):
    expense = PersonalExpense.query.filter_by(
        id=expense_id,
        user_id=current_user.id
    ).first_or_404()

    try:
        db.session.delete(expense)
        db.session.commit()
        flash('Personal expense deleted!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting expense: {str(e)}', 'error')

    return redirect(url_for('personal_expense'))

# ========== CHART ROUTES ==========
@app.route('/charts')
@login_required
def charts():
    try:
        range_key = request.args.get('range', 'all')
        if range_key not in {'week', 'month', 'quarter', 'year', 'all'}:
            range_key = 'all'

        personal_expenses = _filter_personal_expenses(current_user.id, range_key)
        chart_data = _personal_chart_payload(personal_expenses)

        return render_template('charts.html',
                             categories=chart_data['categories'],
                             monthly_data=chart_data['monthly_data'],
                             chart_data=chart_data,
                             selected_range=range_key)
    except Exception as e:
        print(f"Charts error: {e}")
        return render_template('charts.html',
                             categories={},
                             monthly_data={},
                             chart_data=_personal_chart_payload([]),
                             selected_range='all')

# ========== EXPORT ROUTES ==========
@app.route('/export')
@login_required
def export_page():
    memberships = RoomMember.query.filter_by(user_id=current_user.id).all()
    room_ids = [membership.room_id for membership in memberships]
    rooms = Room.query.filter(Room.id.in_(room_ids)).all() if room_ids else []
    return render_template('export.html', rooms=rooms)

@app.route('/export/room', methods=['POST'])
@login_required
def export_selected_room():
    room_id = request.form.get('room_id', type=int)
    if not room_id:
        flash('Please select a room to export.', 'error')
        return redirect(url_for('export_page'))
    return redirect(url_for('export_room', room_id=room_id))

@app.route('/export/<int:room_id>')
@login_required
def export_room(room_id):
    try:
        room = Room.query.get_or_404(room_id)
        membership = RoomMember.query.filter_by(
            room_id=room_id,
            user_id=current_user.id
        ).first()
        if not membership:
            flash('You can only export rooms you belong to.', 'error')
            return redirect(url_for('dashboard'))

        expenses = Expense.query.filter_by(room_id=room_id).all()
        
        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['Description', 'Amount', 'Paid By', 'Category', 'Date', 'Notes'])
        
        # Write data
        for exp in expenses:
            user = db.session.get(User, exp.paid_by)  # Fixed: Use db.session.get()
            writer.writerow([
                exp.description,
                exp.amount,
                user.username if user else 'Unknown',
                exp.category,
                exp.date.strftime('%Y-%m-%d %H:%M:%S'),
                exp.notes or ''
            ])
        
        # Prepare response
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'expensio_room_{room.name}.csv'
        )
    except Exception as e:
        flash(f'Error exporting data: {str(e)}', 'error')
        return redirect(url_for('view_room', room_id=room_id))

@app.route('/export/personal', methods=['GET', 'POST'])
@login_required
def export_personal():
    try:
        range_key = request.values.get('date_range') or request.args.get('range', 'all')
        if range_key not in {'week', 'month', 'quarter', 'year', 'all'}:
            range_key = 'all'

        expenses = _filter_personal_expenses(current_user.id, range_key)
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow(['Description', 'Amount', 'Category', 'Date'])
        
        for exp in expenses:
            writer.writerow([
                exp.description,
                exp.amount,
                exp.category,
                exp.date.strftime('%Y-%m-%d')
            ])
        
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'expensio_personal_expenses_{range_key}.csv'
        )
    except Exception as e:
        flash(f'Error exporting data: {str(e)}', 'error')
        return redirect(url_for('dashboard'))

# ========== ABOUT PAGE ==========
@app.route('/about')
def about():
    return render_template('about.html')

# ========== ERROR HANDLERS ==========
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(e):
    db.session.rollback()
    return render_template('500.html'), 500

# ========== CREATE TABLES ==========
def create_tables():
    with app.app_context():
        db.create_all()
        print("✅ Database tables created successfully!")
        
        # Create a sample user if none exists
        if not User.query.first():
            sample_user = User(
                username='demo',
                email='demo@expensio.com',
                password_hash=generate_password_hash('demo123')
            )
            db.session.add(sample_user)
            db.session.commit()
            print("👤 Sample user created: demo / demo123")

if __name__ == '__main__':
    create_tables()  # This will create tables when app runs
    app.run(debug=True, port=5000)
