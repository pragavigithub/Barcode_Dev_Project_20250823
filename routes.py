from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import logging
import json

from app import app, db, login_manager
from models import User, SerialNumberTransfer, SerialNumberTransferItem, SerialNumberTransferSerial
from sap_integration import SAPIntegration
from sqlalchemy import or_

# API Routes for Basic Functionality

@app.route('/api/get-warehouses', methods=['GET'])
def get_warehouses():
    """Get all warehouses for dropdown selection"""
    try:
        sap = SAPIntegration()
        
        # Try to get warehouses from SAP B1
        if sap.ensure_logged_in():
            try:
                url = f"{sap.base_url}/b1s/v1/Warehouses"
                response = sap.session.get(url, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    warehouses = data.get('value', [])
                    logging.info(f"Retrieved {len(warehouses)} warehouses from SAP B1")
                    return jsonify({
                        'success': True,
                        'warehouses': warehouses
                    })
            except Exception as e:
                logging.error(f"Error getting warehouses from SAP: {str(e)}")
        
        # Return mock data for offline mode or on error
        return jsonify({
            'success': True,
            'warehouses': [
                {'WarehouseCode': 'WH001', 'WarehouseName': 'Main Warehouse'},
                {'WarehouseCode': 'WH002', 'WarehouseName': 'Secondary Warehouse'},
                {'WarehouseCode': 'WH003', 'WarehouseName': 'Storage Warehouse'}
            ]
        })
            
    except Exception as e:
        logging.error(f"Error in get_warehouses API: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/get-item-name', methods=['GET'])
def get_item_name():
    """Get item name from SAP for item code"""
    try:
        item_code = request.args.get('item_code')
        
        if not item_code:
            return jsonify({'success': False, 'error': 'Item code required'}), 400
        
        sap = SAPIntegration()
        
        # Try to get item details from SAP B1
        try:
            if sap.ensure_logged_in():
                item_data = sap.get_item_details(item_code)
                if item_data:
                    return jsonify({
                        'success': True,
                        'item_name': item_data.get('ItemName', f'Item {item_code}'),
                        'uom': item_data.get('SalesUnit', 'EA')
                    })
        except Exception as e:
            logging.error(f"Error getting item from SAP: {str(e)}")
        
        # Return fallback data
        return jsonify({
            'success': True,
            'item_name': f'Item {item_code}',
            'uom': 'EA',
            'fallback': True
        })
        
    except Exception as e:
        logging.error(f"Error in get_item_name API: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        branch_id = request.form.get('branch_id', '').strip()
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            if user.active:
                # Update branch - use provided branch, default branch, or 'HQ001'
                if branch_id:
                    user.branch_id = branch_id
                elif user.default_branch_id:
                    user.branch_id = user.default_branch_id
                elif not user.branch_id:
                    user.branch_id = 'HQ001'  # Default to head office
                
                # Update last login
                user.last_login = datetime.utcnow()
                db.session.commit()
                
                login_user(user)
                
                # Check if password change is required
                if user.must_change_password:
                    flash('You must change your password before continuing.', 'warning')
                    return redirect(url_for('change_password'))
                
                flash('Logged in successfully!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Account is deactivated. Please contact administrator.', 'error')
        else:
            flash('Invalid username or password.', 'error')
    
    # Get available branches for login form
    try:
        branches = db.session.execute(db.text("SELECT branch_code as id, branch_name as name FROM branches WHERE active = TRUE ORDER BY branch_name")).fetchall()
    except Exception as e:
        logging.warning(f"Branches query failed, using default: {e}")
        branches = [{'id': '01', 'name': 'Main Branch'}]
    return render_template('login.html', branches=branches)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        # Get dashboard statistics for available modules only
        serial_transfer_count = SerialNumberTransfer.query.filter_by(user_id=current_user.id).count()
        
        stats = {
            'serial_transfer_count': serial_transfer_count
        }
        
        # Get recent activity - live data from database
        recent_activities = []
        
        # Get recent serial transfers
        recent_serial_transfers = SerialNumberTransfer.query.filter_by(user_id=current_user.id).order_by(SerialNumberTransfer.created_at.desc()).limit(10).all()
        for transfer in recent_serial_transfers:
            recent_activities.append({
                'type': 'Serial Transfer',
                'description': f"Transfer: {transfer.transfer_number}",
                'created_at': transfer.created_at,
                'status': transfer.status
            })
        
        # Sort recent activities by date
        recent_activities.sort(key=lambda x: x['created_at'], reverse=True)
        recent_activities = recent_activities[:10]  # Limit to 10 most recent
        
        return render_template('dashboard.html', 
                             stats=stats, 
                             recent_activities=recent_activities)
    except Exception as e:
        logging.error(f"Error in dashboard: {e}")
        stats = {'serial_transfer_count': 0}
        recent_activities = []
        return render_template('dashboard.html', 
                             stats=stats, 
                             recent_activities=recent_activities)

# Serial Transfer Routes
@app.route('/inventory-transfer-serial')
@login_required
def inventory_transfer_serial():
    """Main Serial Transfer listing page"""
    if not current_user.has_permission('serial_transfer'):
        flash('Access denied. You do not have permission to access Serial Transfer screen.', 'error')
        return redirect(url_for('dashboard'))
    
    try:
        # Get all serial transfers for current user
        serial_transfers = SerialNumberTransfer.query.filter_by(user_id=current_user.id)\
            .order_by(SerialNumberTransfer.created_at.desc()).all()
        
        return render_template('serial_transfer_index.html', 
                             serial_transfers=serial_transfers)
    except Exception as e:
        logging.error(f"Error in inventory_transfer_serial: {e}")
        flash('Database error occurred', 'error')
        return redirect(url_for('dashboard'))

# User Management Routes
@app.route('/user_management')
@login_required
def user_management():
    if not current_user.has_permission('user_management'):
        flash('Access denied. You do not have permission to access User Management screen.', 'error')
        return redirect(url_for('dashboard'))
    
    try:
        search_term = request.args.get('search', '').strip()
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        
        query = User.query
        
        if search_term:
            query = query.filter(
                or_(
                    User.username.contains(search_term),
                    User.first_name.contains(search_term),
                    User.last_name.contains(search_term),
                    User.email.contains(search_term),
                    User.role.contains(search_term)
                )
            )
        
        users_pagination = query.order_by(User.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        users = users_pagination.items
        
    except Exception as e:
        logging.error(f"Database error in user_management: {e}")
        users = []
        users_pagination = None
        search_term = request.args.get('search', '')
        per_page = request.args.get('per_page', 10, type=int)
        flash('Database error occurred', 'warning')
    
    return render_template('user_management.html', 
                         users=users,
                         pagination=users_pagination,
                         search_term=search_term,
                         per_page=per_page)

@app.route('/create_user', methods=['POST'])
@login_required
def create_user():
    if not current_user.has_permission('user_management'):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        role = request.form.get('role')
        branch_id = request.form.get('branch_id')
        
        # Validation
        if not all([username, email, password, role]):
            flash('All required fields must be filled.', 'error')
            return redirect(url_for('user_management'))
        
        # Check for existing user
        existing_user = User.query.filter(
            or_(User.username == username, User.email == email)
        ).first()
        
        if existing_user:
            flash('Username or email already exists.', 'error')
            return redirect(url_for('user_management'))
        
        # Create new user
        new_user = User()
        new_user.username = username
        new_user.email = email
        new_user.password_hash = generate_password_hash(password) if password else generate_password_hash('defaultpass')
        new_user.first_name = first_name
        new_user.last_name = last_name
        new_user.role = role
        new_user.branch_id = branch_id
        new_user.must_change_password = True
        
        db.session.add(new_user)
        db.session.commit()
        
        flash(f'User {username} created successfully.', 'success')
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating user: {e}")
        flash('Error creating user. Please try again.', 'error')
    
    return redirect(url_for('user_management'))

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not current_password or not check_password_hash(current_user.password_hash, current_password):
            flash('Current password is incorrect.', 'error')
        elif new_password != confirm_password:
            flash('New passwords do not match.', 'error')
        elif not new_password or len(new_password) < 6:
            flash('Password must be at least 6 characters long.', 'error')
        else:
            current_user.password_hash = generate_password_hash(new_password)
            current_user.must_change_password = False
            db.session.commit()
            
            flash('Password changed successfully!', 'success')
            return redirect(url_for('dashboard'))
    
    return render_template('change_password.html')

if __name__ == '__main__':
    app.run(debug=True)