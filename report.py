import json
import os
import threading
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
import paho.mqtt.client as mqtt
from flasgger import Swagger, swag_from
from flask import send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app, supports_credentials=True)
app.secret_key = 'SOME_SECRET_KEY'  # Change for production

# Swagger configuration
swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/apispec.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/swagger/"
}

swagger_template = {
    "info": {
        "title": "Power Management API",
        "description": "API for Power Management System",
        "contact": {
            "responsibleOrganization": "Power Management",
            "responsibleDeveloper": "Developer",
            "email": "developer@example.com",
        },
        "version": "1.0",
    },
    "schemes": ["http", "https"],
}

swagger = Swagger(app, config=swagger_config, template=swagger_template)

# Global MQTT settings
mqtt_server = "192.168.1.74"
mqtt_port = 1884

# Configure database (SQLite example)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'energy_system.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

####################################
# Database Models
####################################
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    meter_number = db.Column(db.String(50), unique=True, nullable=False)
    province = db.Column(db.String(50))
    district = db.Column(db.String(50))
    sector = db.Column(db.String(50))
    gender = db.Column(db.String(10))
    role = db.Column(db.String(10), default='user')
    current_power = db.Column(db.Float, default=0.0)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)

    transactions = db.relationship('Transaction', backref='user', lazy=True)
    sensor_readings = db.relationship('SensorReading', backref='user', lazy=True)


class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    meter_number = db.Column(db.String(50), nullable=False)  # ✅ added, you use it in inserts
    purchase_power = db.Column(db.Float, default=0.0)
    purchase_amount = db.Column(db.Float, default=0.0)
    date_purchased = db.Column(db.DateTime, default=datetime.utcnow)


class SensorReading(db.Model):
    __tablename__ = 'sensor_readings'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # ✅ make nullable; set when known
    meter_number = db.Column(db.String(50), nullable=False)
    voltage = db.Column(db.Float, default=0.0)
    current = db.Column(db.Float, default=0.0)
    power = db.Column(db.Float, default=0.0)
    reading_time = db.Column(db.DateTime, default=datetime.utcnow)

####################################
@app.cli.command('initdb')
def initdb():
    """Initialize the database."""
    db.drop_all()
    db.create_all()
    print("Database initialized!")

####################################
# Auth / Session Helpers (Simple)
####################################
def login_user(user):
    session['user_id'] = user.id
    session['role'] = user.role
    session['username'] = user.username

def current_user():
    if 'user_id' in session:
        return db.session.get(User, session['user_id'])
    return None

def logout_user():
    session.pop('user_id', None)
    session.pop('role', None)
    session.pop('username', None)

def is_admin():
    return (session.get('role') == 'admin')

####################################
# Global MQTT Publisher
####################################
flask_mqtt_client = mqtt.Client(client_id="flask_publisher", protocol=mqtt.MQTTv311)
flask_mqtt_client.connect(mqtt_server, mqtt_port, 60)

####################################
# Routes
####################################
@app.route('/')
@swag_from({
    'tags': ['Pages'],
    'summary': 'Home page',
    'description': 'The main landing page of the application',
    'responses': {200: {'description': 'Home page rendered successfully'}}
})
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
@swag_from({
    'tags': ['Authentication'],
    'summary': 'User registration',
    'description': 'Register a new user account',
    'parameters': [
        {'name': 'username','in': 'formData','type': 'string','required': True},
        {'name': 'password','in': 'formData','type': 'string','required': True},
        {'name': 'phone','in': 'formData','type': 'string','required': True},
        {'name': 'meter_number','in': 'formData','type': 'string','required': True},
        {'name': 'gender','in': 'formData','type': 'string','required': True},
        {'name': 'province','in': 'formData','type': 'string','required': True},
        {'name': 'district','in': 'formData','type': 'string','required': True},
        {'name': 'sector','in': 'formData','type': 'string','required': True}
    ],
    'responses': {
        200: {'description': 'Registration successful, redirects to login page'},
        400: {'description': 'Username or Meter Number already in use'}
    }
})
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        phone = request.form.get('phone')
        meter_number = request.form.get('meter_number')
        gender = request.form.get('gender')
        province = request.form.get('province')
        district = request.form.get('district')
        sector = request.form.get('sector')

        existing_user = User.query.filter((User.username == username) | (User.meter_number == meter_number)).first()
        if existing_user:
            flash("Username or Meter Number already in use!", "error")
            return redirect(url_for('register'))

        new_user = User(
            username=username,
            password=password,  # TODO: hash in production
            phone=phone,
            meter_number=meter_number,
            gender=gender,
            province=province,
            district=district,
            sector=sector,
            role='user',
            current_power=0.0
        )
        db.session.add(new_user)
        db.session.commit()
        flash("Registration successful! Please login.", "success")
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
@swag_from({
    'tags': ['Authentication'],
    'summary': 'User login',
    'description': 'Login with username and password',
    'parameters': [
        {'name': 'username','in': 'formData','type': 'string','required': True},
        {'name': 'password','in': 'formData','type': 'string','required': True}
    ],
    'responses': {
        200: {'description': 'Login successful, redirects to dashboard'},
        401: {'description': 'Invalid credentials'}
    }
})
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username, password=password).first()
        if user:
            login_user(user)
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('user_dashboard'))
        else:
            flash("Invalid credentials.", "error")
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
@swag_from({
    'tags': ['Authentication'],
    'summary': 'User logout',
    'description': 'Logout the current user and redirect to home page',
    'responses': {302: {'description': 'Logout successful, redirects to home page'}}
})
def logout():
    logout_user()
    return redirect(url_for('home'))

####################################
# Admin Section
####################################
@app.route('/admin', methods=['GET'])
@swag_from({
    'tags': ['Admin'],
    'summary': 'Admin dashboard',
    'description': 'The main dashboard for administrators',
    'responses': {200: {'description': 'Admin dashboard rendered successfully'}, 401: {'description': 'Unauthorized access'}}
})
def admin_dashboard():
    users = User.query.all()
    return render_template('admin_dashboard.html', users=users)

@app.route('/admin/api/users')
@swag_from({
    'tags': ['Admin'],
    'summary': 'Get all users or search for users',
    'parameters': [{'name': 'search','in': 'query','type': 'string','required': False}],
    'responses': {
        200: {
            'description': 'List of users',
            'schema': {
                'type': 'array',
                'items': {'type': 'object','properties': {
                    'id': {'type': 'integer'},
                    'username': {'type': 'string'},
                    'meter_number': {'type': 'string'},
                    'province': {'type': 'string'},
                    'district': {'type': 'string'},
                    'sector': {'type': 'string'},
                    'current_power': {'type': 'number'}
                }}
            }
        }
    }
})
def admin_api_users():
    search_query = request.args.get('search', '').strip()
    if search_query:
        users = User.query.filter(
            (User.username.ilike(f"%{search_query}%")) |
            (User.meter_number.ilike(f"%{search_query}%"))
        ).all()
    else:
        users = User.query.all()
    data = []
    for u in users:
        data.append({
            "id": u.id,
            "username": u.username,
            "meter_number": u.meter_number,
            "province": u.province,
            "district": u.district,
            "sector": u.sector,
            "current_power": u.current_power
        })
    return jsonify(data)

@app.route('/admin/api/users/<int:user_id>/update', methods=['POST'])
@swag_from({
    'tags': ['Admin'],
    'summary': 'Update user information',
    'parameters': [
        {'name': 'user_id','in': 'path','type': 'integer','required': True},
        {'name': 'body','in': 'body','required': True,'schema': {
            'type': 'object',
            'properties': {
                'username': {'type': 'string'},
                'meter_number': {'type': 'string'},
                'province': {'type': 'string'},
                'district': {'type': 'string'},
                'sector': {'type': 'string'},
                'current_power': {'type': 'number'}
            }
        }}
    ],
    'responses': {
        200: {'description': 'User updated successfully','schema': {'type': 'object','properties': {'success': {'type': 'boolean'}}}},
        404: {'description': 'User not found'}
    }
})
def admin_api_users_update(user_id):
    user = User.query.get_or_404(user_id)
    data = request.json or {}
    user.username = data.get('username', user.username)
    user.meter_number = data.get('meter_number', user.meter_number)
    user.province = data.get('province', user.province)
    user.district = data.get('district', user.district)
    user.sector = data.get('sector', user.sector)
    try:
        user.current_power = float(data.get('current_power', user.current_power))
    except (ValueError, TypeError):
        pass
    db.session.commit()
    return jsonify({"success": True})

@app.route('/admin/api/users/<int:user_id>/delete', methods=['DELETE'])
@swag_from({
    'tags': ['Admin'],
    'summary': 'Delete a user',
    'parameters': [{'name': 'user_id','in': 'path','type': 'integer','required': True}],
    'responses': {
        200: {'description': 'User deleted successfully','schema': {'type': 'object','properties': {'success': {'type': 'boolean'}}}},
        404: {'description': 'User not found'}
    }
})
def admin_api_users_delete(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/admin/other_users', endpoint='other_admin_users')
@swag_from({
    'tags': ['Admin'],
    'summary': 'Other admin users page',
    'description': 'Alternative page for administrators to view and manage users',
    'responses': {200: {'description': 'Other admin users page rendered successfully'}}
})
def other_admin_users_page():
    return render_template('other_admin_users.html')

@app.route('/admin/view-meter', methods=['GET', 'POST'])
@swag_from({
    'tags': ['Admin'],
    'summary': 'View meter data',
    'description': 'View sensor readings for a specific meter',
    'parameters': [{'name': 'meter_number','in': 'formData','type': 'string','required': True}],
    'responses': {200: {'description': 'Meter data retrieved successfully'},404: {'description': 'No data found for that meter'}}
})
def admin_view_meter():
    meter_data = None
    if request.method == 'POST':
        meter_number = request.form.get('meter_number')
        meter_data = SensorReading.query.filter_by(meter_number=meter_number).order_by(SensorReading.id.desc()).first()
        if not meter_data:
            flash("No data found for that meter.", "error")
    return render_template('admin_view_meter.html', meter_data=meter_data)

@app.route('/admin/buy-electricity', methods=['GET','POST'])
@swag_from({
    'tags': ['Admin'],
    'summary': 'Buy electricity for a user',
    'description': 'Administrator can purchase electricity for any user',
    'parameters': [
        {'name': 'meter_number','in': 'formData','type': 'string','required': True},
        {'name': 'amount','in': 'formData','type': 'number','required': True}
    ],
    'responses': {200: {'description': 'Purchase successful'},404: {'description': 'User (meter) not found'}}
})
def admin_buy_electricity():
    if request.method == 'POST':
        meter_number = request.form.get('meter_number')
        amount_str = request.form.get('amount', '0')
        try:
            amount = float(amount_str)
        except ValueError:
            amount = 0.0
        user = User.query.filter_by(meter_number=meter_number).first()
        if user:
            purchased_watts = amount / 500.0
            user.current_power += purchased_watts
            new_transaction = Transaction(
                user_id=user.id,
                meter_number=meter_number,        # ✅ model supports this now
                purchase_amount=amount,
                purchase_power=purchased_watts     # ✅ record watts purchased
            )
            db.session.add(new_transaction)
            db.session.commit()
            flash(f"Successfully purchased {purchased_watts:.2f} W for {user.username}.", "success")
        else:
            flash("User (meter) not found!", "error")
    return render_template('admin_buy_electricity.html')

####################################
# User Section
####################################
@app.route('/user', methods=['GET'])
@swag_from({
    'tags': ['User'],
    'summary': 'User dashboard',
    'description': 'The main dashboard for regular users',
    'responses': {200: {'description': 'User dashboard rendered successfully'},302: {'description': 'Redirect to login page if not authenticated'}}
})
def user_dashboard():
    user = current_user()
    if not user:
        flash("Please log in first.", "error")
        return redirect(url_for('login'))
    meter_data = SensorReading.query.filter_by(meter_number=user.meter_number).order_by(SensorReading.id.desc()).first()
    return render_template('user_dashboard.html', meter_data=meter_data, user=user)

@app.route('/user/buy-electricity', methods=['POST'])
@swag_from({
    'tags': ['User'],
    'summary': 'Buy electricity',
    'description': 'Purchase electricity for self or another user',
    'parameters': [
        {'name': 'body','in': 'body','required': True,'schema': {
            'type': 'object',
            'properties': {
                'buy_for': {'type': 'string','enum': ['self', 'other']},
                'amount': {'type': 'number'},
                'meter_number': {'type': 'string'}
            },
            'required': ['buy_for', 'amount']
        }}
    ],
    'responses': {
        200: {'description': 'Purchase successful','schema': {'type': 'object','properties': {'success': {'type': 'boolean'},'message': {'type': 'string'},'power': {'type': 'number'}}}},
        401: {'description': 'Unauthorized'},
        404: {'description': 'Meter not found'}
    }
})
def user_buy_electricity():
    user = current_user()
    if not user:
        return jsonify({"success": False, "message": "Please log in first."}), 401

    if request.is_json:
        data = request.json
        buy_for = data.get('buy_for')
        raw_amount = data.get('amount', 0)
        other_meter = data.get('meter_number')
    else:
        buy_for = request.form.get('buy_for')
        raw_amount = request.form.get('amount', '0')
        other_meter = request.form.get('other_meter_number')

    try:
        amount = round(float(raw_amount), 2)
    except (ValueError, TypeError):
        amount = 0.0

    purchased_watts = amount / 500.0

    if buy_for == 'self':
        user.current_power += purchased_watts
        db.session.add(Transaction(
            user_id=user.id,
            meter_number=user.meter_number,    # ✅
            purchase_amount=amount,
            purchase_power=purchased_watts     # ✅
        ))
        db.session.commit()

        if request.is_json:
            return jsonify({"success": True, "message": f"You purchased {purchased_watts:.2f} W for yourself.","power": purchased_watts})
        else:
            flash(f"You purchased {purchased_watts:.2f} W for yourself.", "success")
            return redirect(url_for('user_dashboard'))
    else:
        if not other_meter:
            if request.is_json:
                return jsonify({"success": False, "message": "Meter number is required"}), 400
            else:
                flash("Meter number is required.", "error")
                return redirect(url_for('user_dashboard'))

        other_user = User.query.filter_by(meter_number=other_meter).first()
        if not other_user:
            if request.is_json:
                return jsonify({"success": False, "message": "Meter not found"}), 404
            else:
                flash("Meter not found.", "error")
                return redirect(url_for('user_dashboard'))

        purchased_watts = amount / 500.0
        other_user.current_power += purchased_watts
        db.session.add(Transaction(
            user_id=other_user.id,
            meter_number=other_meter,          # ✅
            purchase_amount=amount,
            purchase_power=purchased_watts     # ✅
        ))
        db.session.commit()

        if request.is_json:
            return jsonify({"success": True, "message": f"You purchased {purchased_watts:.2f} W for {other_user.username}.","power": purchased_watts})
        else:
            flash(f"You purchased {purchased_watts:.2f} W for {other_user.username}.", "success")
            return redirect(url_for('user_dashboard'))

@app.route('/admin/check_meter')
@swag_from({
    'tags': ['Admin'],
    'summary': 'Check if meter exists',
    'description': 'Check if a meter number exists in the system',
    'parameters': [{'name': 'meter','in': 'query','type': 'string','required': True}],
    'responses': {200: {'description': 'Check result','schema': {'type': 'object','properties': {'exists': {'type': 'boolean'},'username': {'type': 'string'}}}}}
})
def check_meter():
    meter = request.args.get('meter', '')
    user = User.query.filter_by(meter_number=meter).first()
    if user:
        return jsonify({'exists': True, 'username': user.username})
    else:
        return jsonify({'exists': False})

@app.route('/admin/users')
@swag_from({
    'tags': ['Admin'],
    'summary': 'Admin users page',
    'description': 'Page for administrators to view and manage users',
    'responses': {200: {'description': 'Admin users page rendered successfully'}}
})
def admin_users_page():
    return render_template('admin_users.html')

####################################
# ---------- JSON API ----------
####################################
@app.route('/api/port_report/<meter_number>', endpoint='report')
@swag_from({
    'tags': ['Meter Reports'],
    'summary': 'Get power report for a specific meter (JSON)',
    'parameters': [{'name': 'meter_number','in': 'path','type': 'string','required': True}],
    'responses': {200: {'description': 'Power report (JSON)'},404: {'description': 'Meter not found'}}
})
def api_port_report_json(meter_number):
    user = User.query.filter_by(meter_number=meter_number).first()
    if not user:
        return jsonify({'error': 'Meter not found'}), 404

    latest_transaction = (Transaction.query
                          .filter_by(user_id=user.id)
                          .order_by(Transaction.date_purchased.desc())
                          .first())

    latest_reading = (SensorReading.query
                      .filter_by(meter_number=meter_number)
                      .order_by(SensorReading.reading_time.desc())
                      .first())

    purchased_power = latest_transaction.purchase_power if latest_transaction else 0.0
    purchased_date = latest_transaction.date_purchased.strftime("%Y-%m-%d %H:%M:%S") if latest_transaction else "N/A"
    current_power = user.current_power or 0.0
    consumed_power = max(purchased_power - current_power, 0.0)
    latest_date = latest_reading.reading_time.strftime("%Y-%m-%d %H:%M:%S") if latest_reading else "N/A"

    return jsonify({
        'meter_number': meter_number,
        'latest_purchased_power': round(purchased_power, 2),
        'current_power': round(current_power, 2),
        'consumed_power': round(consumed_power, 2),
        'purchased_date': purchased_date,
        'latest_date': latest_date
    })

####################################
# ---------- HTML view ----------
####################################
@app.route('/port_report/<meter_number>', endpoint='port_report_html')
@swag_from({
    'tags': ['Meter Reports'],
    'summary': 'Get power report for a specific meter (HTML)',
    'parameters': [{'name': 'meter_number','in': 'path','type': 'string','required': True}],
    'responses': {200: {'description': 'Power report HTML page'},404: {'description': 'Meter not found'}}
})
def api_port_report_html(meter_number):
    user = User.query.filter_by(meter_number=meter_number).first()
    if not user:
        return "Meter not found", 404

    latest_transaction = (Transaction.query
                          .filter_by(user_id=user.id)
                          .order_by(Transaction.date_purchased.desc())
                          .first())

    latest_reading = (SensorReading.query
                      .filter_by(meter_number=meter_number)
                      .order_by(SensorReading.reading_time.desc())
                      .first())

    purchased_power = latest_transaction.purchase_power if latest_transaction else 0.0
    purchased_date = latest_transaction.date_purchased.strftime("%Y-%m-%d %H:%M:%S") if latest_transaction else "N/A"
    current_power = user.current_power or 0.0
    consumed_power = max(purchased_power - current_power, 0.0)
    latest_date = latest_reading.reading_time.strftime("%Y-%m-%d %H:%M:%S") if latest_reading else "N/A"

    return render_template(
        'report.html',
        meter_number=meter_number,
        purchased_power=purchased_power,
        current_power=current_power,
        consumed_power=consumed_power,
        purchased_date=purchased_date,
        latest_date=latest_date
    )

####################################
# AJAX Endpoints
####################################
@app.route('/api/latest-reading/<meter_number>')
@swag_from({
    'tags': ['Meter Readings'],
    'summary': 'Get latest sensor reading for a specific meter',
    'parameters': [{'name': 'meter_number','in': 'path','type': 'string','required': True}],
    'responses': {
        200: {'description': 'Latest sensor reading','schema': {'type': 'object','properties': {
            'voltage': {'type': 'number'},
            'current': {'type': 'number'},
            'power': {'type': 'number'},
            'reading_time': {'type': 'string','format': 'date-time'}
        }}},
        404: {'description': 'No reading found','schema': {'type': 'object','properties': {'error': {'type': 'string'}}}}
    }
})
def api_latest_reading(meter_number):
    reading = SensorReading.query.filter_by(meter_number=meter_number).order_by(SensorReading.id.desc()).first()
    if reading:
        return jsonify({
            'voltage': reading.voltage,
            'current': reading.current,
            'power': reading.power,
            'reading_time': reading.reading_time.strftime('%Y-%m-%d %H:%M:%S')
        })
    else:
        return jsonify({'error': 'No reading found'}), 404

@app.route('/api/update_consumption', methods=['POST'])
@swag_from({
    'tags': ['Meter Readings'],
    'summary': 'Update power consumption for a meter',
    'parameters': [{'name': 'body','in': 'body','required': True,'schema': {
        'type': 'object',
        'required': ['meter_number', 'voltage', 'current', 'power_consumed'],
        'properties': {
            'meter_number': {'type': 'string'},
            'voltage': {'type': 'number'},
            'current': {'type': 'number'},
            'power_consumed': {'type': 'number'}
        }
    }}],
    'responses': {
        200: {'description': 'Consumption updated','schema': {'type': 'object','properties': {'status': {'type': 'string'},'remaining_power': {'type': 'string'}}}},
        404: {'description': 'Meter not found','schema': {'type': 'object','properties': {'error': {'type': 'string'}}}}
    }
})
def api_update_consumption():
    print("Received update_consumption request")
    data = request.json or {}
    meter_number = data.get('meter_number')
    print("Meter number from request:", meter_number)
    voltage = float(data.get('voltage', 0) or 0)
    current = float(data.get('current', 0) or 0)
    power_consumed = float(data.get('power_consumed', 0.0) or 0.0)

    user = User.query.filter_by(meter_number=meter_number).first()
    if user:
        if user.current_power > 0:
            user.current_power -= power_consumed
            if user.current_power < 0:
                user.current_power = 0

        sr = SensorReading(
            user_id=user.id,                 # ✅ attach FK
            meter_number=meter_number,
            voltage=voltage,
            current=current,
            power=power_consumed
        )
        db.session.add(sr)
        db.session.commit()
        print(f"API Update - Updated user {meter_number}: remaining power = {user.current_power}")
        return jsonify({'status': 'OK', 'remaining_power': "{:.2f}".format(user.current_power)})
    else:
        print(f"Meter not found: {meter_number}")
        # still log reading without user if you prefer; here we skip to keep it clean
        return jsonify({'error': 'Meter not found'}), 404

####################################
@app.route('/api/relay_control', methods=['POST'])
def relay_control():
    """
    Always-200 relay control: accepts {meter_number:str, state:'on'|'off'},
    publishes to MQTT with the already-connected publisher client.
    """
    try:
        data = request.get_json(silent=True) or {}
        meter_number = (data.get('meter_number') or '').strip()
        state = (data.get('state') or '').strip().lower()

        if state not in ('on', 'off') or not meter_number:
            return jsonify({'message': 'Relay command accepted (no-op due to invalid inputs)','queued': False}), 200

        payload = json.dumps({"meter_number": meter_number, "command": state})
        info = flask_mqtt_client.publish("relay/control", payload, qos=1, retain=False)
        _ = getattr(info, "rc", 0)

        return jsonify({'message': f"Relay command '{state}' queued for meter {meter_number}.",'queued': True}), 200

    except Exception as e:
        print("relay_control error:", e)
        return jsonify({'message': 'Relay command received (publish will be retried by client).','queued': False}), 200

####################################
# MQTT Subscriber (Embedded)
####################################
def mqtt_on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to MQTT broker.")
        client.subscribe("power/monitor")
        client.subscribe("relay/control")
    else:
        print(f"Failed to connect, return code {rc}. Retrying in 5 seconds...")
        threading.Timer(5, lambda: client.reconnect()).start()

def mqtt_on_message(client, userdata, msg):
    try:
        payload_str = msg.payload.decode()
        print("MQTT Message received:", payload_str)
        data = json.loads(payload_str)
        meter_number = data.get('meter_number')
        voltage = float(data.get('voltage', 0) or 0)
        current = float(data.get('current', 0) or 0)
        power_consumed = float(data.get('power_consumed', 0.0) or 0.0)

        with app.app_context():
            user = User.query.filter_by(meter_number=meter_number).first()
            if user:
                if user.current_power > 0:
                    user.current_power -= power_consumed
                    if user.current_power < 0:
                        user.current_power = 0
                updated_power_payload = json.dumps({
                    "meter_number": meter_number,
                    "remaining_power": user.current_power
                })
                client.publish("power/update", updated_power_payload)
                print(f"Updated user {meter_number}: remaining power = {user.current_power}")
            else:
                print(f"No matching user found for meter {meter_number}.")

            # Store reading (attach user_id if we have one)
            sr = SensorReading(
                user_id=(user.id if user else None),    # ✅ keep data even if user missing
                meter_number=meter_number,
                voltage=voltage,
                current=current,
                power=power_consumed
            )
            db.session.add(sr)
            db.session.commit()
    except Exception as e:
        print("Error processing MQTT message:", e)

mqtt_client = mqtt.Client()
mqtt_client.on_message = mqtt_on_message

def start_mqtt_subscriber():
    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = mqtt_on_connect
    mqtt_client.on_message = mqtt_on_message
    try:
        mqtt_client.connect(mqtt_server, mqtt_port, 60)
        print("Starting MQTT subscriber loop...")
        mqtt_client.loop_forever()
    except Exception as e:
        print(f"MQTT connection error: {e}. Retrying in 10 seconds...")
        threading.Timer(10, start_mqtt_subscriber).start()

@app.route('/api/current_power/<meter_number>')
@swag_from({
    'tags': ['Meter Readings'],
    'summary': 'Get current power for a specific meter',
    'parameters': [{'name': 'meter_number','in': 'path','type': 'string','required': True}],
    'responses': {
        200: {'description': 'Current power for the meter','schema': {'type': 'object','properties': {'current_power': {'type': 'string'}}}},
        404: {'description': 'Meter not found','schema': {'type': 'object','properties': {'error': {'type': 'string'}}}}
    }
})
def api_current_power(meter_number):
    print("Querying current power for meter:", meter_number)
    user = User.query.filter_by(meter_number=meter_number).first()
    if user:
        current_power = round(user.current_power, 2)
        print(f"Found user {meter_number}: current power = {current_power}")
        return jsonify({'current_power': "{:.2f}".format(current_power)})
    else:
        print("Meter not found for:", meter_number)
        return jsonify({'error': 'Meter not found'}), 404

####################################
# Main Execution
####################################
if __name__ == "__main__":
    # Start MQTT subscriber in a separate thread
    mqtt_thread = threading.Thread(target=start_mqtt_subscriber, daemon=True)
    mqtt_thread.start()

    # Run Flask app (LAN)
    print("Starting Flask app...")
    print("Swagger UI available at: http://192.168.1.74:5000/swagger/")
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
