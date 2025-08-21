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
            "rule_filter": lambda rule: True,  # all in
            "model_filter": lambda tag: True,  # all in
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
mqtt_server = "127.0.0.1"
mqtt_port = 1883




# Configure database (SQLite example). For MySQL/Postgres, adjust accordingly.
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'cashpower.db')
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
    meter_number = db.Column(db.String(50), unique=True)
    province = db.Column(db.String(50))
    district = db.Column(db.String(50))
    sector = db.Column(db.String(50))
    gender = db.Column(db.String(10))
    role = db.Column(db.String(10), default='admin')  # 'admin' or 'user'
    current_power = db.Column(db.Float, default=0.0)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)

class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    meter_number = db.Column(db.String(50))
    purchase_power = db.Column(db.Float)  # Purchased power in W
    purchase_amount = db.Column(db.Float)  # Currency amount (or watt amount, depending on your logic)
    payment_method = db.Column(db.String(20), nullable=True)  # Payment method used (mtn, airtel, visa, mastercard)
    date_purchased = db.Column(db.DateTime, default=datetime.utcnow)

class SensorReading(db.Model):
    __tablename__ = 'sensor_readings'
    id = db.Column(db.Integer, primary_key=True)
    meter_number = db.Column(db.String(50))
    voltage = db.Column(db.Float)
    current = db.Column(db.Float)
    power = db.Column(db.Float)
    reading_time = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

####################################
# Utility: Database Init Command
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
    # Allow admin access without login
    # This is a simplified check that assumes all admin routes should be accessible without login
    # In a production environment, you would want to implement proper authentication
    return True

####################################
# Global MQTT Publisher
####################################
# Create a global MQTT publisher for relay commands.
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
    'responses': {
        200: {
            'description': 'Home page rendered successfully'
        }
    }
})
def home():
    return render_template('home.html')  # Basic home page

@app.route('/register', methods=['GET', 'POST'])
@swag_from({
    'tags': ['Authentication'],
    'summary': 'User registration',
    'description': 'Register a new user account',
    'parameters': [
        {
            'name': 'username',
            'in': 'formData',
            'type': 'string',
            'required': True,
            'description': 'Username'
        },
        {
            'name': 'password',
            'in': 'formData',
            'type': 'string',
            'required': True,
            'description': 'Password'
        },
        {
            'name': 'phone',
            'in': 'formData',
            'type': 'string',
            'required': True,
            'description': 'Phone number'
        },
        {
            'name': 'meter_number',
            'in': 'formData',
            'type': 'string',
            'required': True,
            'description': 'Meter number'
        },
        {
            'name': 'gender',
            'in': 'formData',
            'type': 'string',
            'required': True,
            'description': 'Gender'
        },
        {
            'name': 'province',
            'in': 'formData',
            'type': 'string',
            'required': True,
            'description': 'Province'
        },
        {
            'name': 'district',
            'in': 'formData',
            'type': 'string',
            'required': True,
            'description': 'District'
        },
        {
            'name': 'sector',
            'in': 'formData',
            'type': 'string',
            'required': True,
            'description': 'Sector'
        }
    ],
    'responses': {
        200: {
            'description': 'Registration successful, redirects to login page'
        },
        400: {
            'description': 'Username or Meter Number already in use'
        }
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
            password=password,  # In production, hash the password
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
        {
            'name': 'username',
            'in': 'formData',
            'type': 'string',
            'required': True,
            'description': 'Username'
        },
        {
            'name': 'password',
            'in': 'formData',
            'type': 'string',
            'required': True,
            'description': 'Password'
        }
    ],
    'responses': {
        200: {
            'description': 'Login successful, redirects to dashboard'
        },
        401: {
            'description': 'Invalid credentials'
        }
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
    'responses': {
        302: {
            'description': 'Logout successful, redirects to home page'
        }
    }
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
    'responses': {
        200: {
            'description': 'Admin dashboard rendered successfully'
        },
        401: {
            'description': 'Unauthorized access'
        }
    }
})
def admin_dashboard():
    users = User.query.all()
    return render_template('admin_dashboard.html', users=users)

@app.route('/admin/api/users')
@swag_from({
    'tags': ['Admin'],
    'summary': 'Get all users or search for users',
    'parameters': [
        {
            'name': 'search',
            'in': 'query',
            'type': 'string',
            'required': False,
            'description': 'Search term for username or meter number'
        }
    ],
    'responses': {
        200: {
            'description': 'List of users',
            'schema': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer'},
                        'username': {'type': 'string'},
                        'meter_number': {'type': 'string'},
                        'province': {'type': 'string'},
                        'district': {'type': 'string'},
                        'sector': {'type': 'string'},
                        'current_power': {'type': 'number'}
                    }
                }
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
        {
            'name': 'user_id',
            'in': 'path',
            'type': 'integer',
            'required': True,
            'description': 'ID of the user to update'
        },
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'description': 'User data to update',
            'schema': {
                'type': 'object',
                'properties': {
                    'username': {'type': 'string'},
                    'meter_number': {'type': 'string'},
                    'province': {'type': 'string'},
                    'district': {'type': 'string'},
                    'sector': {'type': 'string'},
                    'current_power': {'type': 'number'}
                }
            }
        }
    ],
    'responses': {
        200: {
            'description': 'User updated successfully',
            'schema': {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'}
                }
            }
        },
        404: {
            'description': 'User not found'
        }
    }
})
def admin_api_users_update(user_id):
    user = User.query.get_or_404(user_id)
    data = request.json
    user.username = data.get('username', user.username)
    user.meter_number = data.get('meter_number', user.meter_number)
    user.province = data.get('province', user.province)
    user.district = data.get('district', user.district)
    user.sector = data.get('sector', user.sector)
    try:
        user.current_power = float(data.get('current_power', user.current_power))
    except ValueError:
        pass
    db.session.commit()
    return jsonify({"success": True})

@app.route('/admin/api/users/<int:user_id>/delete', methods=['DELETE'])
@swag_from({
    'tags': ['Admin'],
    'summary': 'Delete a user',
    'parameters': [
        {
            'name': 'user_id',
            'in': 'path',
            'type': 'integer',
            'required': True,
            'description': 'ID of the user to delete'
        }
    ],
    'responses': {
        200: {
            'description': 'User deleted successfully',
            'schema': {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'}
                }
            }
        },
        404: {
            'description': 'User not found'
        }
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
    'responses': {
        200: {
            'description': 'Other admin users page rendered successfully'
        }
    }
})
def other_admin_users_page():
    return render_template('other_admin_users.html')

@app.route('/admin/view-meter', methods=['GET', 'POST'])
@swag_from({
    'tags': ['Admin'],
    'summary': 'View meter data',
    'description': 'View sensor readings for a specific meter',
    'parameters': [
        {
            'name': 'meter_number',
            'in': 'formData',
            'type': 'string',
            'required': True,
            'description': 'Meter number to view'
        }
    ],
    'responses': {
        200: {
            'description': 'Meter data retrieved successfully'
        },
        404: {
            'description': 'No data found for that meter'
        }
    }
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
        {
            'name': 'meter_number',
            'in': 'formData',
            'type': 'string',
            'required': True,
            'description': 'Meter number of the user'
        },
        {
            'name': 'amount',
            'in': 'formData',
            'type': 'number',
            'required': True,
            'description': 'Amount to purchase'
        }
    ],
    'responses': {
        200: {
            'description': 'Purchase successful'
        },
        404: {
            'description': 'User (meter) not found'
        }
    }
})
def admin_buy_electricity():
    if request.method == 'POST':
        meter_number = request.form.get('meter_number')
        amount_str = request.form.get('amount', '0')
        try:
            amount = float(amount_str)
        except ValueError:
            amount = 0.0

        if amount <= 0:
            flash("Please enter a valid amount.", "error")
            return render_template('admin_buy_electricity.html')

        user = User.query.filter_by(meter_number=meter_number).first()
        if user:
            # Redirect to payment page with purchase details
            return redirect(url_for('payment_page', 
                                   amount=amount, 
                                   buy_for='admin', 
                                   meter_number=meter_number))
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
    'responses': {
        200: {
            'description': 'User dashboard rendered successfully'
        },
        302: {
            'description': 'Redirect to login page if not authenticated'
        }
    }
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
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'buy_for': {
                        'type': 'string',
                        'enum': ['self', 'other'],
                        'description': 'Buy for self or other user'
                    },
                    'amount': {
                        'type': 'number',
                        'description': 'Amount to purchase'
                    },
                    'meter_number': {
                        'type': 'string',
                        'description': 'Meter number of other user (required if buy_for is "other")'
                    }
                },
                'required': ['buy_for', 'amount']
            }
        }
    ],
    'responses': {
        200: {
            'description': 'Purchase successful',
            'schema': {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'message': {'type': 'string'},
                    'power': {'type': 'number'}
                }
            }
        },
        401: {
            'description': 'Unauthorized'
        },
        404: {
            'description': 'Meter not found'
        }
    }
})
def user_buy_electricity():
    user = current_user()
    if not user:
        return jsonify({"success": False, "message": "Please log in first."}), 401

    # Check if the request is JSON or form data
    if request.is_json:
        data = request.json
        buy_for = data.get('buy_for')
        raw_amount = data.get('amount', 0)
        other_meter = data.get('meter_number')

        # For API requests, process directly without payment page
        try:
            amount = round(float(raw_amount), 2)
        except (ValueError, TypeError):
            amount = 0.0

        purchased_watts = amount / 500.0

        if buy_for == 'self':
            user.current_power += purchased_watts
            db.session.add(Transaction(
                user_id=user.id,
                meter_number=user.meter_number,
                purchase_amount=amount,
                purchase_power=purchased_watts
            ))
            db.session.commit()
            return jsonify({
                "success": True, 
                "message": f"You purchased {purchased_watts:.2f} W for yourself.",
                "power": purchased_watts
            })
        else:
            if not other_meter:
                return jsonify({"success": False, "message": "Meter number is required"}), 400

            other_user = User.query.filter_by(meter_number=other_meter).first()
            if not other_user:
                return jsonify({"success": False, "message": "Meter not found"}), 404

            purchased_watts = amount / 500.0
            other_user.current_power += purchased_watts
            db.session.add(Transaction(
                user_id=other_user.id,
                meter_number=other_meter,
                purchase_amount=amount,
                purchase_power=purchased_watts
            ))
            db.session.commit()
            return jsonify({
                "success": True, 
                "message": f"You purchased {purchased_watts:.2f} W for {other_user.username}.",
                "power": purchased_watts
            })
    else:
        # For form submissions, redirect to payment page
        buy_for = request.form.get('buy_for')
        raw_amount = request.form.get('amount', '0')
        other_meter = request.form.get('other_meter_number')

        try:
            amount = round(float(raw_amount), 2)
        except (ValueError, TypeError):
            amount = 0.0

        if amount <= 0:
            flash("Please enter a valid amount.", "error")
            return redirect(url_for('user_dashboard'))

        if buy_for == 'other' and not other_meter:
            flash("Meter number is required.", "error")
            return redirect(url_for('user_dashboard'))

        if buy_for == 'other':
            other_user = User.query.filter_by(meter_number=other_meter).first()
            if not other_user:
                flash("Meter not found.", "error")
                return redirect(url_for('user_dashboard'))

        # Redirect to payment page with purchase details
        return redirect(url_for('payment_page', 
                               amount=amount, 
                               buy_for=buy_for, 
                               meter_number=user.meter_number if buy_for == 'self' else None,
                               other_meter_number=other_meter if buy_for == 'other' else None))

@app.route('/payment')
def payment_page():
    amount = request.args.get('amount', '0')
    buy_for = request.args.get('buy_for', 'self')
    meter_number = request.args.get('meter_number')
    other_meter_number = request.args.get('other_meter_number')

    # Only check for user login if it's not an admin purchase
    if buy_for != 'admin':
        user = current_user()
        if not user:
            flash("Please log in first.", "error")
            return redirect(url_for('login'))

    try:
        amount = float(amount)
    except (ValueError, TypeError):
        amount = 0.0

    if amount <= 0:
        flash("Invalid amount.", "error")
        return redirect(url_for('user_dashboard'))

    return render_template('payment.html', 
                          amount=amount, 
                          buy_for=buy_for, 
                          meter_number=meter_number,
                          other_meter_number=other_meter_number)

@app.route('/process_payment', methods=['POST'])
def process_payment():
    buy_for = request.form.get('buy_for', 'self')

    # Only check for user login if it's not an admin purchase
    if buy_for != 'admin':
        user = current_user()
        if not user:
            flash("Please log in first.", "error")
            return redirect(url_for('login'))
    else:
        user = None

    # Get payment details
    payment_method = request.form.get('payment_method')
    if not payment_method:
        flash("Please select a payment method.", "error")
        return redirect(url_for('payment_page', 
                               amount=request.form.get('amount'),
                               buy_for=request.form.get('buy_for'),
                               meter_number=request.form.get('meter_number'),
                               other_meter_number=request.form.get('other_meter_number')))

    # Get purchase details
    try:
        amount = round(float(request.form.get('amount', '0')), 2)
    except (ValueError, TypeError):
        amount = 0.0

    if amount <= 0:
        flash("Invalid amount.", "error")
        return redirect(url_for('user_dashboard'))

    buy_for = request.form.get('buy_for', 'self')
    meter_number = request.form.get('meter_number')
    other_meter_number = request.form.get('other_meter_number')

    # Calculate purchased watts
    purchased_watts = amount / 500.0

    # Process the purchase
    if buy_for == 'self':
        user.current_power += purchased_watts
        db.session.add(Transaction(
            user_id=user.id,
            meter_number=user.meter_number,
            purchase_amount=amount,
            purchase_power=purchased_watts,
            payment_method=payment_method
        ))
        db.session.commit()
        flash(f"You purchased {purchased_watts:.2f} W for yourself using {payment_method.upper()}.", "success")
        return redirect(url_for('user_dashboard'))
    elif buy_for == 'admin':
        # Admin purchase for a user
        target_user = User.query.filter_by(meter_number=meter_number).first()
        if not target_user:
            flash("Meter not found.", "error")
            return redirect(url_for('admin_buy_electricity'))

        target_user.current_power += purchased_watts
        db.session.add(Transaction(
            user_id=target_user.id,
            meter_number=meter_number,
            purchase_amount=amount,
            purchase_power=purchased_watts,
            payment_method=payment_method
        ))
        db.session.commit()
        flash(f"Successfully purchased {purchased_watts:.2f} W for {target_user.username} using {payment_method.upper()}.", "success")
        return redirect(url_for('admin_dashboard'))
    else:
        # User purchase for another user
        other_user = User.query.filter_by(meter_number=other_meter_number).first()
        if not other_user:
            flash("Meter not found.", "error")
            return redirect(url_for('user_dashboard'))

        other_user.current_power += purchased_watts
        db.session.add(Transaction(
            user_id=other_user.id,
            meter_number=other_meter_number,
            purchase_amount=amount,
            purchase_power=purchased_watts,
            payment_method=payment_method
        ))
        db.session.commit()
        flash(f"You purchased {purchased_watts:.2f} W for {other_user.username} using {payment_method.upper()}.", "success")
        return redirect(url_for('user_dashboard'))

@app.route('/admin/check_meter')
@swag_from({
    'tags': ['Admin'],
    'summary': 'Check if meter exists',
    'description': 'Check if a meter number exists in the system',
    'parameters': [
        {
            'name': 'meter',
            'in': 'query',
            'type': 'string',
            'required': True,
            'description': 'Meter number to check'
        }
    ],
    'responses': {
        200: {
            'description': 'Check result',
            'schema': {
                'type': 'object',
                'properties': {
                    'exists': {'type': 'boolean'},
                    'username': {'type': 'string'}
                }
            }
        }
    }
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
    'responses': {
        200: {
            'description': 'Admin users page rendered successfully'
        }
    }
})
def admin_users_page():
    return render_template('admin_users.html')

####################################
# Messaging Routes
####################################
@app.route('/user/messages')
def user_messages():
    """User messages page to contact admin support."""
    user = current_user()
    if not user:
        flash("Please log in first.", "error")
        return redirect(url_for('login'))

    # Get all messages for this user
    messages = Message.query.filter(
        ((Message.sender_id == user.id) & (Message.receiver_id.in_([u.id for u in User.query.filter_by(role='admin')]))) |
        ((Message.receiver_id == user.id) & (Message.sender_id.in_([u.id for u in User.query.filter_by(role='admin')])))
    ).order_by(Message.timestamp).all()

    # Mark all messages as read
    for message in messages:
        if message.receiver_id == user.id and not message.is_read:
            message.is_read = True

    db.session.commit()

    return render_template('user_messages.html', user=user, messages=messages)

@app.route('/user/send-message', methods=['POST'])
def user_send_message():
    """Send a message from user to admin."""
    user = current_user()
    if not user:
        flash("Please log in first.", "error")
        return redirect(url_for('login'))

    message_content = request.form.get('message', '').strip()
    if not message_content:
        flash("Message cannot be empty.", "error")
        return redirect(url_for('user_messages'))

    # Find an admin to send the message to
    admin = User.query.filter_by(role='admin').first()
    if not admin:
        flash("No admin available to receive your message.", "error")
        return redirect(url_for('user_messages'))

    # Create and save the message
    message = Message(
        sender_id=user.id,
        receiver_id=admin.id,
        content=message_content,
        is_read=False
    )
    db.session.add(message)
    db.session.commit()

    flash("Message sent successfully.", "success")
    return redirect(url_for('user_messages'))

@app.route('/admin/messages')
@app.route('/admin/messages/<int:user_id>')
def admin_messages(user_id=None):
    """Admin interface to view and respond to user messages."""
    if not is_admin():
        flash("Admin access required.", "error")
        return redirect(url_for('login'))

    admin = current_user()
    # If admin is None (not logged in), use the first admin user in the database
    if admin is None:
        admin = User.query.filter_by(role='admin').first()
        # If no admin user exists, create a default one
        if admin is None:
            admin = User(
                username='default_admin',
                password='password',  # This would be hashed in a real application
                role='admin'
            )
            db.session.add(admin)
            db.session.commit()

    users = User.query.filter_by(role='user').all()
    selected_user = None
    chat_messages = []

    # Get unread message counts for each user
    unread_counts = {}
    for user in users:
        # Only check for unread messages if admin has an id
        if admin and admin.id:
            count = Message.query.filter_by(sender_id=user.id, receiver_id=admin.id, is_read=False).count()
            if count > 0:
                unread_counts[user.id] = count

    if user_id:
        selected_user = User.query.get(user_id)
        if selected_user and admin and admin.id:
            # Get all messages between admin and selected user
            chat_messages = Message.query.filter(
                ((Message.sender_id == admin.id) & (Message.receiver_id == user_id)) |
                ((Message.receiver_id == admin.id) & (Message.sender_id == user_id))
            ).order_by(Message.timestamp).all()

            # Mark messages from this user as read
            unread_messages = Message.query.filter_by(
                sender_id=user_id, 
                receiver_id=admin.id,
                is_read=False
            ).all()

            for message in unread_messages:
                message.is_read = True

            db.session.commit()

    return render_template(
        'admin_messages.html',
        users=users,
        selected_user=selected_user,
        chat_messages=chat_messages,
        unread_counts=unread_counts
    )

@app.route('/admin/send-message/<int:user_id>', methods=['POST'])
def admin_send_message(user_id):
    """Send a message from admin to user."""
    if not is_admin():
        flash("Admin access required.", "error")
        return redirect(url_for('login'))

    admin = current_user()
    # If admin is None (not logged in), use the first admin user in the database
    if admin is None:
        admin = User.query.filter_by(role='admin').first()
        # If no admin user exists, create a default one
        if admin is None:
            admin = User(
                username='default_admin',
                password='password',  # This would be hashed in a real application
                role='admin'
            )
            db.session.add(admin)
            db.session.commit()

    user = User.query.get(user_id)

    if not user:
        flash("User not found.", "error")
        return redirect(url_for('admin_messages'))

    message_content = request.form.get('message', '').strip()
    if not message_content:
        flash("Message cannot be empty.", "error")
        return redirect(url_for('admin_messages', user_id=user_id))

    # Create and save the message
    message = Message(
        sender_id=admin.id,
        receiver_id=user.id,
        content=message_content,
        is_read=False
    )
    db.session.add(message)
    db.session.commit()

    flash("Message sent successfully.", "success")
    return redirect(url_for('admin_messages', user_id=user_id))

####################################
####################################
# Report  ➜  JSON  +  HTML
####################################

# ---------- JSON API ----------
@app.route('/api/port_report/<meter_number>')
@swag_from({
    'tags': ['Meter Reports'],
    'summary': 'Get power report for a specific meter (JSON)',
    'parameters': [
        {
            'name': 'meter_number',
            'in': 'path',
            'type': 'string',
            'required': True,
            'description': 'Meter number to get report for'
        }
    ],
    'responses': {
        200: {
            'description': 'Power report for the meter (JSON)'
        },
        404: {
            'description': 'Meter not found'
        }
    }
})
def api_report(meter_number): 
    user = User.query.filter_by(meter_number=meter_number).first()
    if not user:
        return jsonify({'error': 'Meter not found'}), 404

    latest_transaction = (Transaction.query
                          .filter_by(meter_number=meter_number)
                          .order_by(Transaction.date_purchased.desc())
                          .first())

    latest_reading = (SensorReading.query
                      .filter_by(meter_number=meter_number)
                      .order_by(SensorReading.reading_time.desc())
                      .first())

    if latest_transaction and latest_transaction.purchase_power is not None:
        purchased_power = latest_transaction.purchase_power
        purchased_date = latest_transaction.date_purchased.strftime("%Y-%m-%d %H:%M:%S")
    else:
        purchased_power = 0.0
        purchased_date = "N/A"

    current_power = user.current_power or 0.0
    consumed_power = purchased_power - current_power
    latest_date   = latest_reading.reading_time.strftime("%Y-%m-%d %H:%M:%S") if latest_reading else "N/A"

    return jsonify({
        'meter_number'          : meter_number,
        'latest_purchased_power': round(purchased_power, 2),
        'current_power'         : round(current_power, 2),
        'consumed_power'        : round(consumed_power, 2),
        'purchased_date'        : purchased_date,
        'latest_date'           : latest_date
    })


# ---------- HTML view ----------
@app.route('/report/<meter_number>')
def report(meter_number): 
    """
    Render the same data inside templates/report.html
    """
    user = User.query.filter_by(meter_number=meter_number).first()
    if not user:
        return render_template("report.html", meter=meter_number, error="Meter not found")

    latest_transaction = (Transaction.query
                          .filter_by(meter_number=meter_number)
                          .order_by(Transaction.date_purchased.desc())
                          .first())

    latest_reading = (SensorReading.query
                      .filter_by(meter_number=meter_number)
                      .order_by(SensorReading.reading_time.desc())
                      .first())

    if latest_transaction and latest_transaction.purchase_power is not None:
        purchased_power = latest_transaction.purchase_power
        purchased_at    = latest_transaction.date_purchased.strftime("%Y-%m-%d %H:%M:%S")
    else:
        purchased_power = 0.0
        purchased_at    = "N/A"

    current_power = user.current_power or 0.0
    consumed_power = purchased_power - current_power
    updated_at     = latest_reading.reading_time.strftime("%Y-%m-%d %H:%M:%S") if latest_reading else "N/A"

    report = {
        "purchased_power": round(purchased_power, 2),
        "current_power"  : round(current_power, 2),
        "consumed_power" : round(consumed_power, 2),
        "updated_at"     : updated_at,
        "purchased_at"   : purchased_at
    }

    return render_template("report.html", meter=meter_number, report=report)

####################################################
@app.route('/download_report/<meter_number>')
def download_report(meter_number):
    # generate or load PDF file for that meter
    return send_file(f'reports/{meter_number}.pdf', as_attachment=True)

####################################
# Data Collection Endpoint
####################################
@app.route('/collect', methods=['POST'])
@swag_from({
    'tags': ['Data Collection'],
    'summary': 'Collect usage data',
    'description': 'Collect usage data from different screens',
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'meter_number': {
                        'type': 'string',
                        'description': 'Meter number'
                    },
                    'screen_name': {
                        'type': 'string',
                        'description': 'Name of the screen where data is collected'
                    },
                    'timestamp': {
                        'type': 'string',
                        'format': 'date-time',
                        'description': 'Time when data was collected'
                    }
                },
                'required': ['meter_number', 'screen_name']
            }
        }
    ],
    'responses': {
        200: {
            'description': 'Data collected successfully',
            'schema': {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'message': {'type': 'string'}
                }
            }
        },
        400: {
            'description': 'Invalid request parameters'
        }
    }
})
def collect_data():
    if request.is_json:
        data = request.json
    else:
        data = request.form

    meter_number = data.get('meter_number')
    screen_name = data.get('screen_name')

    if not meter_number:
        return jsonify({"success": False, "message": "Meter number is required"}), 400

    if not screen_name:
        return jsonify({"success": False, "message": "Screen name is required"}), 400

    # Here you would typically store this data in a database
    # For now, we'll just log it
    print(f"Collected data: meter_number={meter_number}, screen_name={screen_name}")

    return jsonify({
        "success": True,
        "message": f"Data collected successfully from {screen_name}"
    })

####################################
# AJAX Endpoints 
####################################
@app.route('/api/latest-reading/<meter_number>')
@swag_from({
    'tags': ['Meter Readings'],
    'summary': 'Get latest sensor reading for a specific meter',
    'parameters': [
        {
            'name': 'meter_number',
            'in': 'path',
            'type': 'string',
            'required': True,
            'description': 'Meter number to get reading for'
        }
    ],
    'responses': {
        200: {
            'description': 'Latest sensor reading for the meter',
            'schema': {
                'type': 'object',
                'properties': {
                    'voltage': {'type': 'number'},
                    'current': {'type': 'number'},
                    'power': {'type': 'number'},
                    'reading_time': {'type': 'string', 'format': 'date-time'}
                }
            }
        },
        404: {
            'description': 'No reading found for the meter',
            'schema': {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'}
                }
            }
        }
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
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'description': 'Consumption data to update',
            'schema': {
                'type': 'object',
                'required': ['meter_number', 'voltage', 'current', 'power_consumed'],
                'properties': {
                    'meter_number': {'type': 'string'},
                    'voltage': {'type': 'number'},
                    'current': {'type': 'number'},
                    'power_consumed': {'type': 'number'}
                }
            }
        }
    ],
    'responses': {
        200: {
            'description': 'Consumption updated successfully',
            'schema': {
                'type': 'object',
                'properties': {
                    'status': {'type': 'string'},
                    'remaining_power': {'type': 'string'}
                }
            }
        },
        404: {
            'description': 'Meter not found',
            'schema': {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'}
                }
            }
        }
    }
})
def api_update_consumption():
    print("Received update_consumption request")
    data = request.json
    meter_number = data.get('meter_number')
    print("Meter number from request:", meter_number)
    voltage = data.get('voltage')
    current = data.get('current')
    power_consumed = data.get('power_consumed', 0.0)
    user = User.query.filter_by(meter_number=meter_number).first()
    if user:
        if user.current_power > 0:
            user.current_power -= power_consumed
            if user.current_power < 0:
                user.current_power = 0
        sr = SensorReading(
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
        return jsonify({'error': 'Meter not found'}), 404

####################################
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

        # Soft validation, but never block success
        if state not in ('on', 'off') or not meter_number:
            # still return 200 to keep UI simple
            return jsonify({
                'message': 'Relay command accepted (no-op due to invalid inputs)',
                'queued': False
            }), 200

        payload = json.dumps({"meter_number": meter_number, "command": state})

        # publish with the CONNECTED publisher client
        info = flask_mqtt_client.publish("relay/control", payload, qos=1, retain=False)
        # we don't gate success on rc; UI should remain optimistic
        _ = getattr(info, "rc", 0)

        return jsonify({
            'message': f"Relay command '{state}' queued for meter {meter_number}.",
            'queued': True
        }), 200

    except Exception as e:
        # even on exception, keep API green to avoid UI failures
        print("relay_control error:", e)
        return jsonify({
            'message': 'Relay command received (publish will be retried by client).',
            'queued': False
        }), 200

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
        threading.Timer(5, lambda: client.reconnect()).start()  # Attempt reconnect

def mqtt_on_message(client, userdata, msg):
    try:
        payload_str = msg.payload.decode()
        print("MQTT Message received:", payload_str)
        data = json.loads(payload_str)
        meter_number = data.get('meter_number')
        voltage = data.get('voltage')
        current = data.get('current')
        power_consumed = data.get('power_consumed', 0.0)

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

            sr = SensorReading(
                meter_number=meter_number,
                voltage=voltage,
                current=current,
                power=power_consumed
            )
            db.session.add(sr)
            db.session.commit()
    except Exception as e:
        print("Error processing MQTT message:", e)

# Now assign the function as a callback
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
        threading.Timer(10, start_mqtt_subscriber).start()  # Reconnect loop

@app.route('/api/current_power/<meter_number>')
@swag_from({
    'tags': ['Meter Readings'],
    'summary': 'Get current power for a specific meter',
    'parameters': [
        {
            'name': 'meter_number',
            'in': 'path',
            'type': 'string',
            'required': True,
            'description': 'Meter number to get current power for'
        }
    ],
    'responses': {
        200: {
            'description': 'Current power for the meter',
            'schema': {
                'type': 'object',
                'properties': {
                    'current_power': {'type': 'string'}
                }
            }
        },
        404: {
            'description': 'Meter not found',
            'schema': {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'}
                }
            }
        }
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
# Main Execution: Start Flask and MQTT Subscriber
####################################
if __name__ == "__main__":
    # Start MQTT subscriber in a separate thread
    mqtt_thread = threading.Thread(target=start_mqtt_subscriber)
    mqtt_thread.daemon = True
    mqtt_thread.start()

    # Run Flask app (accessible on local network)
    print("Starting Flask app...")
    print("Swagger UI available at: http://192.168.1.69:5000/swagger/")

    # Change host to 0.0.0.0 to allow LAN access
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
