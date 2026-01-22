import os
from functools import wraps
from flask import Flask, request, jsonify, render_template, send_from_directory, session, redirect, url_for, make_response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta

basedir = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(basedir, 'uploads')

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'inventory.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['SECRET_KEY'] = os.environ.get('SESSION_SECRET') or os.urandom(24).hex()
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db = SQLAlchemy(app)

def require_admin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

class Item(db.Model):
    __tablename__ = 'items'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    barcode = db.Column(db.String(50), unique=True, nullable=False, index=True)
    category = db.Column(db.String(100))
    quantity = db.Column(db.Integer, nullable=False, default=0)
    low_stock_threshold = db.Column(db.Integer, default=10)
    image_filename = db.Column(db.String(200))
    reorder_url = db.Column(db.String(500))
    logs = db.relationship('UsageLog', backref='item_details', cascade="all, delete-orphan")

class UsageLog(db.Model):
    __tablename__ = 'usage_log'
    id = db.Column(db.Integer, primary_key=True)
    apartment_number = db.Column(db.String(20), nullable=False)
    employee_number = db.Column(db.String(20))
    quantity_used = db.Column(db.Integer, nullable=False, default=1)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    item_id = db.Column(db.Integer, db.ForeignKey('items.id'), nullable=False)

class OrderRequest(db.Model):
    __tablename__ = 'order_requests'
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('items.id'), nullable=False)
    apartment_number = db.Column(db.String(20), nullable=False)
    quantity_needed = db.Column(db.Integer, nullable=False)
    reorder_url = db.Column(db.String(500))
    status = db.Column(db.String(20), default='pending')
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    item = db.relationship('Item', backref='order_requests')

class ToolTracking(db.Model):
    __tablename__ = 'tool_tracking'
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('items.id'), nullable=False)
    employee_name = db.Column(db.String(100), nullable=False)
    action = db.Column(db.String(20), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    item = db.relationship('Item', backref='tool_tracking')

class AdminUser(db.Model):
    __tablename__ = 'admin_users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_superadmin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@app.route('/')
def landing():
    response = render_template('landing.html')
    response = make_response(response)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/scanner')
def scanner():
    response = render_template('scanner.html')
    response = make_response(response)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/service-worker.js')
def service_worker():
    return send_from_directory('static', 'service-worker.js', mimetype='application/javascript')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin_user = AdminUser.query.filter_by(username=username).first()
        
        if admin_user and admin_user.check_password(password):
            session['admin_logged_in'] = True
            session['admin_id'] = admin_user.id
            session['admin_username'] = admin_user.username
            session['is_superadmin'] = admin_user.is_superadmin
            session.permanent = True
            admin_user.last_login = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('admin'))
        else:
            return render_template('login.html', error='Invalid username or password')
    
    if session.get('admin_logged_in'):
        return redirect(url_for('admin'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('landing'))

@app.route('/admin')
@require_admin
def admin():
    response = render_template('admin.html')
    response = make_response(response)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/api/items', methods=['GET'])
def get_items():
    try:
        items = Item.query.order_by(Item.name.asc()).all()
        item_list = [{
            'id': i.id,
            'name': i.name,
            'barcode': i.barcode,
            'category': i.category,
            'quantity': i.quantity,
            'low_stock_threshold': i.low_stock_threshold,
            'is_low_stock': i.quantity <= i.low_stock_threshold if i.low_stock_threshold is not None else False,
            'image_filename': i.image_filename,
            'reorder_url': i.reorder_url
        } for i in items]
        return jsonify(item_list)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/item', methods=['POST'])
def add_item():
    try:
        name = request.form.get('name')
        barcode = request.form.get('barcode')
        category = request.form.get('category', '')
        quantity = request.form.get('quantity', 0)
        low_stock_threshold = request.form.get('low_stock_threshold', 10)
        
        if not name or not barcode:
            return jsonify({'error': 'Name and barcode are required'}), 400
        
        existing = Item.query.filter_by(barcode=barcode).first()
        if existing:
            return jsonify({'error': 'Item with this barcode already exists'}), 400
        
        image_filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                image_filename = f"{timestamp}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
        
        new_item = Item(
            name=name,
            barcode=barcode,
            category=category,
            quantity=int(quantity),
            low_stock_threshold=int(low_stock_threshold),
            image_filename=image_filename,
            reorder_url=request.form.get('reorder_url', '')
        )
        db.session.add(new_item)
        db.session.commit()
        
        return jsonify({
            'message': 'Item added successfully',
            'id': new_item.id
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/item/<barcode>', methods=['GET'])
def get_item_by_barcode(barcode):
    try:
        item = Item.query.filter_by(barcode=barcode).first()
        if not item:
            return jsonify({'error': 'Item not found'}), 404
        
        return jsonify({
            'id': item.id,
            'name': item.name,
            'barcode': item.barcode,
            'category': item.category,
            'quantity': item.quantity,
            'low_stock_threshold': item.low_stock_threshold,
            'is_low_stock': item.quantity <= item.low_stock_threshold if item.low_stock_threshold is not None else False,
            'image_filename': item.image_filename,
            'reorder_url': item.reorder_url
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/item/<int:item_id>', methods=['PUT'])
def update_item(item_id):
    try:
        item = Item.query.get(item_id)
        if not item:
            return jsonify({'error': 'Item not found'}), 404
        
        item.name = request.form.get('name', item.name)
        item.category = request.form.get('category', item.category)
        item.barcode = request.form.get('barcode', item.barcode)
        item.quantity = int(request.form.get('quantity', item.quantity))
        item.reorder_url = request.form.get('reorder_url', item.reorder_url)
        
        if 'low_stock_threshold' in request.form:
            item.low_stock_threshold = int(request.form.get('low_stock_threshold'))
        
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                image_filename = f"{timestamp}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
                item.image_filename = image_filename
        
        db.session.commit()
        return jsonify({'message': 'Item updated successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/item/<int:item_id>', methods=['DELETE'])
def delete_item(item_id):
    try:
        item = Item.query.get(item_id)
        if not item:
            return jsonify({'error': 'Item not found'}), 404
        
        db.session.delete(item)
        db.session.commit()
        return jsonify({'message': 'Item deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/search_items', methods=['GET'])
def search_items():
    try:
        query = request.args.get('q', '')
        if len(query) < 2:
            return jsonify([])
        
        items = Item.query.filter(
            db.or_(
                Item.name.ilike(f'%{query}%'),
                Item.category.ilike(f'%{query}%'),
                Item.barcode.ilike(f'%{query}%')
            )
        ).all()
        
        return jsonify([{
            'id': i.id,
            'name': i.name,
            'barcode': i.barcode,
            'quantity': i.quantity,
            'is_low_stock': i.quantity <= i.low_stock_threshold if i.low_stock_threshold is not None else False
        } for i in items])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/log_usage', methods=['POST'])
def log_usage():
    try:
        data = request.get_json()
        barcode = data.get('barcode')
        apartment = data.get('apartment')
        employee_number = data.get('employee_number', '')
        quantity = int(data.get('quantity', 1))
        
        if not barcode or not apartment:
            return jsonify({'error': 'Barcode and apartment are required'}), 400
        
        item = Item.query.filter_by(barcode=barcode).first()
        if not item:
            return jsonify({'error': 'Item not found'}), 404
        
        if item.quantity < quantity:
            return jsonify({'error': f'Insufficient inventory. Only {item.quantity} available.'}), 400
        
        item.quantity -= quantity
        
        log_entry = UsageLog(
            apartment_number=apartment,
            employee_number=employee_number,
            quantity_used=quantity,
            item_id=item.id
        )
        db.session.add(log_entry)
        db.session.commit()
        
        return jsonify({
            'message': f'Usage logged successfully. Remaining: {item.quantity}',
            'remaining_quantity': item.quantity
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/low_stock_alerts', methods=['GET'])
def get_low_stock_alerts():
    try:
        items = Item.query.all()
        low_stock_items = [
            {
                'id': i.id,
                'name': i.name,
                'barcode': i.barcode,
                'category': i.category,
                'quantity': i.quantity,
                'low_stock_threshold': i.low_stock_threshold,
                'reorder_url': i.reorder_url
            }
            for i in items 
            if i.low_stock_threshold is not None and i.quantity <= i.low_stock_threshold
        ]
        
        return jsonify(low_stock_items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/history')
@require_admin
def history():
    response = render_template('history.html')
    response = make_response(response)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/api/usage_history', methods=['GET'])
def get_usage_history():
    try:
        limit = request.args.get('limit', 100, type=int)
        apartment = request.args.get('apartment', '')
        employee_number = request.args.get('employee_number', '')
        item_name = request.args.get('item_name', '')
        
        query = db.session.query(UsageLog, Item).join(Item, UsageLog.item_id == Item.id)
        
        if apartment:
            query = query.filter(UsageLog.apartment_number.ilike(f'%{apartment}%'))
        if employee_number:
            query = query.filter(UsageLog.employee_number.ilike(f'%{employee_number}%'))
        if item_name:
            query = query.filter(Item.name.ilike(f'%{item_name}%'))
        
        logs = query.order_by(UsageLog.timestamp.desc()).limit(limit).all()
        
        return jsonify([{
            'id': log.id,
            'apartment_number': log.apartment_number,
            'employee_number': log.employee_number,
            'quantity_used': log.quantity_used,
            'timestamp': log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'item_name': item.name,
            'item_category': item.category,
            'item_barcode': item.barcode
        } for log, item in logs])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/order_request', methods=['POST'])
def create_order_request():
    try:
        data = request.get_json()
        item_id = data.get('item_id')
        apartment_number = data.get('apartment_number')
        quantity_needed = data.get('quantity_needed')
        reorder_url = data.get('reorder_url')
        
        if not all([item_id, apartment_number, quantity_needed]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        item = Item.query.get(item_id)
        if not item:
            return jsonify({'error': 'Item not found'}), 404
        
        order_request = OrderRequest(
            item_id=item_id,
            apartment_number=apartment_number,
            quantity_needed=int(quantity_needed),
            reorder_url=reorder_url,
            status='pending'
        )
        db.session.add(order_request)
        db.session.commit()
        
        return jsonify({
            'message': 'Order request submitted successfully',
            'id': order_request.id
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/order_requests', methods=['GET'])
def get_order_requests():
    try:
        status_filter = request.args.get('status', '')
        
        query = db.session.query(OrderRequest, Item).join(Item, OrderRequest.item_id == Item.id)
        
        if status_filter:
            query = query.filter(OrderRequest.status == status_filter)
        
        requests_data = query.order_by(OrderRequest.timestamp.desc()).all()
        
        return jsonify([{
            'id': req.id,
            'item_id': req.item_id,
            'item_name': item.name,
            'item_barcode': item.barcode,
            'apartment_number': req.apartment_number,
            'quantity_needed': req.quantity_needed,
            'reorder_url': req.reorder_url,
            'status': req.status,
            'timestamp': req.timestamp.isoformat()
        } for req, item in requests_data])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/order_request/<int:request_id>/status', methods=['PUT'])
def update_order_request_status(request_id):
    try:
        data = request.get_json()
        new_status = data.get('status')
        
        if not new_status:
            return jsonify({'error': 'Status is required'}), 400
        
        order_request = OrderRequest.query.get(request_id)
        if not order_request:
            return jsonify({'error': 'Order request not found'}), 404
        
        order_request.status = new_status
        db.session.commit()
        
        return jsonify({'message': 'Status updated successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/log_tool_action', methods=['POST'])
def log_tool_action():
    try:
        data = request.get_json()
        item_id = data.get('item_id')
        employee_name = data.get('employee_name')
        action = data.get('action')
        
        if not all([item_id, employee_name, action]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        if action not in ['checkout', 'return']:
            return jsonify({'error': 'Action must be "checkout" or "return"'}), 400
        
        item = Item.query.get(item_id)
        if not item:
            return jsonify({'error': 'Item not found'}), 404
        
        tool_log = ToolTracking(
            item_id=item_id,
            employee_name=employee_name,
            action=action
        )
        db.session.add(tool_log)
        db.session.commit()
        
        return jsonify({
            'message': f'Tool {action} logged successfully',
            'id': tool_log.id,
            'timestamp': tool_log.timestamp.isoformat()
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/tool_tracking', methods=['GET'])
def get_tool_tracking():
    try:
        item_name = request.args.get('item_name', '')
        employee_name = request.args.get('employee_name', '')
        limit = request.args.get('limit', 100, type=int)
        
        query = db.session.query(ToolTracking, Item).join(Item, ToolTracking.item_id == Item.id)
        
        if item_name:
            query = query.filter(Item.name.ilike(f'%{item_name}%'))
        if employee_name:
            query = query.filter(ToolTracking.employee_name.ilike(f'%{employee_name}%'))
        
        logs = query.order_by(ToolTracking.timestamp.desc()).limit(limit).all()
        
        return jsonify([{
            'id': log.id,
            'employee_name': log.employee_name,
            'action': log.action,
            'timestamp': log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'item_name': item.name,
            'item_barcode': item.barcode
        } for log, item in logs])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    with app.app_context():
        admin_count = AdminUser.query.count()
        if admin_count > 0:
            return redirect(url_for('login'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not username or not password:
            return render_template('setup.html', error='Username and password are required')
        
        if password != confirm_password:
            return render_template('setup.html', error='Passwords do not match')
        
        if len(password) < 4:
            return render_template('setup.html', error='Password must be at least 4 characters')
        
        admin = AdminUser(username=username, is_superadmin=True)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        
        return redirect(url_for('login'))
    
    return render_template('setup.html')

@app.route('/api/admins', methods=['GET'])
@require_admin
def get_admins():
    try:
        admins = AdminUser.query.order_by(AdminUser.created_at.desc()).all()
        return jsonify([{
            'id': a.id,
            'username': a.username,
            'is_superadmin': a.is_superadmin,
            'created_at': a.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'last_login': a.last_login.strftime('%Y-%m-%d %H:%M:%S') if a.last_login else None
        } for a in admins])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admins', methods=['POST'])
@require_admin
def add_admin():
    try:
        if not session.get('is_superadmin'):
            return jsonify({'error': 'Only superadmins can add new administrators'}), 403
        
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        is_superadmin = data.get('is_superadmin', False)
        
        if not username or not password:
            return jsonify({'error': 'Username and password are required'}), 400
        
        existing = AdminUser.query.filter_by(username=username).first()
        if existing:
            return jsonify({'error': 'Username already exists'}), 400
        
        admin = AdminUser(username=username, is_superadmin=is_superadmin)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        
        return jsonify({'message': 'Admin added successfully', 'id': admin.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/admins/<int:admin_id>', methods=['DELETE'])
@require_admin
def delete_admin(admin_id):
    try:
        if not session.get('is_superadmin'):
            return jsonify({'error': 'Only superadmins can delete admins'}), 403
        
        if admin_id == session.get('admin_id'):
            return jsonify({'error': 'Cannot delete yourself'}), 400
        
        admin = AdminUser.query.get(admin_id)
        if not admin:
            return jsonify({'error': 'Admin not found'}), 404
        
        superadmin_count = AdminUser.query.filter_by(is_superadmin=True).count()
        if admin.is_superadmin and superadmin_count <= 1:
            return jsonify({'error': 'Cannot delete the last superadmin'}), 400
        
        db.session.delete(admin)
        db.session.commit()
        
        return jsonify({'message': 'Admin deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/admin/users')
@require_admin
def admin_users():
    if not session.get('is_superadmin'):
        return redirect(url_for('admin'))
    response = render_template('admin_users.html')
    response = make_response(response)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response

@app.route('/api/change_password', methods=['POST'])
@require_admin
def change_password():
    try:
        data = request.get_json()
        current_password = data.get('current_password')
        new_password = data.get('new_password')
        
        if not current_password or not new_password:
            return jsonify({'error': 'Current and new passwords are required'}), 400
        
        if len(new_password) < 4:
            return jsonify({'error': 'New password must be at least 4 characters'}), 400
        
        admin = AdminUser.query.get(session.get('admin_id'))
        if not admin:
            return jsonify({'error': 'Admin not found'}), 404
        
        if not admin.check_password(current_password):
            return jsonify({'error': 'Current password is incorrect'}), 400
        
        admin.set_password(new_password)
        db.session.commit()
        
        return jsonify({'message': 'Password changed successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/change_username', methods=['POST'])
@require_admin
def change_username():
    try:
        data = request.get_json()
        new_username = data.get('new_username')
        password = data.get('password')
        
        if not new_username or not password:
            return jsonify({'error': 'New username and password are required'}), 400
        
        admin = AdminUser.query.get(session.get('admin_id'))
        if not admin:
            return jsonify({'error': 'Admin not found'}), 404
        
        if not admin.check_password(password):
            return jsonify({'error': 'Password is incorrect'}), 400
        
        existing = AdminUser.query.filter_by(username=new_username).first()
        if existing and existing.id != admin.id:
            return jsonify({'error': 'Username already taken'}), 400
        
        admin.username = new_username
        db.session.commit()
        session['username'] = new_username
        
        return jsonify({'message': 'Username changed successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/change-password')
@require_admin
def change_password_page():
    response = render_template('change_password.html')
    response = make_response(response)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response

def init_db():
    db.create_all()
    admin_count = AdminUser.query.count()
    if admin_count == 0:
        print("No admin users found. Please visit /setup to create the first admin.")

if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
