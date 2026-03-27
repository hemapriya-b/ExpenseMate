from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import csv
import io
import os
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///expensio.db')
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

class PersonalExpense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), default='Other')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    budget_month = db.Column(db.String(7))  # YYYY-MM format

# Now define relationships
User.rooms = db.relationship('RoomMember', backref='member', lazy=True)
User.personal_expenses = db.relationship('PersonalExpense', backref='user', lazy=True)
User.expenses_paid = db.relationship('Expense', foreign_keys='Expense.paid_by', backref='payer', lazy=True)
User.expense_shares = db.relationship('ExpenseShare', backref='share_user', lazy=True)
Room.expenses = db.relationship('Expense', backref='room', lazy=True)
Room.members = db.relationship('RoomMember', backref='room', lazy=True)
Room.activities = db.relationship('RoomActivity', backref='activity_room', lazy=True)
Expense.shares = db.relationship('ExpenseShare', backref='expense', lazy=True, cascade='all, delete-orphan')

# Ensure newly added tables exist even when app is imported (not only run as __main__).
with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))  # Fixed: Use db.session.get()

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
        month_key = now.strftime('%Y-%m')
        monthly_personal_expenses = [
            exp for exp in PersonalExpense.query.filter_by(user_id=current_user.id).all()
            if exp.date.strftime('%Y-%m') == month_key
        ]
        monthly_spent = round(sum(exp.amount for exp in monthly_personal_expenses), 2)
        personal_budget = 0.0  # Not configured yet
        budget_progress_pct = int((monthly_spent / personal_budget) * 100) if personal_budget > 0 else 0

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
        room_name = request.form.get('room_name')
        room_code = request.form.get('room_code')
        
        room = Room.query.filter_by(name=room_name, room_code=room_code).first()
        
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
            flash('Invalid room name or code', 'error')
    
    return render_template('room/join.html')

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
        
        return render_template('room/view.html',
                             room=room,
                             expenses=expenses,
                             members=member_data,
                             is_admin=member.is_admin,
                             settlements=settlements,
                             activities=activities,
                             room_members=room_members)
    except Exception as e:
        flash(f'Error loading room: {str(e)}', 'error')
        return redirect(url_for('dashboard'))

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
        description = request.form.get('description')
        amount = float(request.form.get('amount'))
        category = request.form.get('category')
        date_str = request.form.get('date')
        
        try:
            if date_str:
                date = datetime.strptime(date_str, '%Y-%m-%d')
            else:
                date = datetime.utcnow()
            
            new_expense = PersonalExpense(
                description=description,
                amount=amount,
                category=category,
                user_id=current_user.id,
                date=date
            )
            
            db.session.add(new_expense)
            db.session.commit()
            flash('Personal expense added!', 'success')
            return redirect(url_for('dashboard'))
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
    month_key = now.strftime('%Y-%m')
    month_expenses = [exp for exp in expenses if exp.date.strftime('%Y-%m') == month_key]
    month_total = round(sum(exp.amount for exp in month_expenses), 2)
    month_count = len(month_expenses)
    month_avg = round((month_total / month_count), 2) if month_count else 0
    budget_limit = 0.0
    budget_progress_pct = int((month_total / budget_limit) * 100) if budget_limit > 0 else 0
    
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
        budget_progress_pct=budget_progress_pct
    )

# ========== CHART ROUTES ==========
@app.route('/charts')
@login_required
def charts():
    try:
        # Get data for charts
        personal_expenses = PersonalExpense.query.filter_by(
            user_id=current_user.id
        ).all()
        
        # Prepare data for pie chart (categories)
        categories = {}
        for exp in personal_expenses:
            categories[exp.category] = categories.get(exp.category, 0) + exp.amount
        
        # Prepare data for bar chart (monthly expenses)
        monthly_data = {}
        for exp in personal_expenses:
            month = exp.date.strftime('%Y-%m')
            monthly_data[month] = monthly_data.get(month, 0) + exp.amount
        
        return render_template('charts.html',
                             categories=categories,
                             monthly_data=monthly_data)
    except Exception as e:
        print(f"Charts error: {e}")
        return render_template('charts.html',
                             categories={},
                             monthly_data={})

# ========== EXPORT ROUTES ==========
@app.route('/export/<int:room_id>')
@login_required
def export_room(room_id):
    try:
        room = Room.query.get_or_404(room_id)
        expenses = Expense.query.filter_by(room_id=room_id).all()
        
        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['Description', 'Amount', 'Paid By', 'Category', 'Date'])
        
        # Write data
        for exp in expenses:
            user = db.session.get(User, exp.paid_by)  # Fixed: Use db.session.get()
            writer.writerow([
                exp.description,
                exp.amount,
                user.username if user else 'Unknown',
                exp.category,
                exp.date.strftime('%Y-%m-%d %H:%M:%S')
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

@app.route('/export/personal')
@login_required
def export_personal():
    try:
        expenses = PersonalExpense.query.filter_by(user_id=current_user.id).all()
        
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
            download_name='expensio_personal_expenses.csv'
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
