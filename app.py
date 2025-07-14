import json
import os
import threading
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
import paho.mqtt.client as mqtt
from flasgger import Swagger, swag_from

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
mqtt_server = "192.168.1.72"
mqtt_port = 1884

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
    date_purchased = db.Column(db.DateTime, default=datetime.utcnow)

class SensorReading(db.Model):
    __tablename__ = 'sensor_readings'
    id = db.Column(db.Integer, primary_key=True)
    meter_number = db.Column(db.String(50))
    voltage = db.Column(db.Float)
    current = db.Column(db.Float)
    power = db.Column(db.Float)
    reading_time = db.Column(db.DateTime, default=datetime.utcnow)

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
    return (session.get('role') == 'admin')

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
        user = User.query.filter_by(meter_number=meter_number).first()
        if user:
            purchased_watts = amount / 500.0
            user.current_power += purchased_watts
            new_transaction = Transaction(
                user_id=user.id,
                meter_number=meter_number,
                purchase_amount=amount
            )
            db.session.add(new_transaction)
            db.session.commit()
            flash(f"Successfully purchased {purchased_watts} W for {user.username}.", "success")
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
            meter_number=user.meter_number,
            purchase_amount=amount,
            purchase_power=purchased_watts
        ))
        db.session.commit()

        if request.is_json:
            return jsonify({
                "success": True, 
                "message": f"You purchased {purchased_watts:.2f} W for yourself.",
                "power": purchased_watts
            })
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
            meter_number=other_meter,
            purchase_amount=amount,
            purchase_power=purchased_watts
        ))
        db.session.commit()

        if request.is_json:
            return jsonify({
                "success": True, 
                "message": f"You purchased {purchased_watts:.2f} W for {other_user.username}.",
                "power": purchased_watts
            })
        else:
            flash(f"You purchased {purchased_watts:.2f} W for {other_user.username}.", "success")
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
# Report
####################################
@app.route('/api/port_report/<meter_number>')
@swag_from({
    'tags': ['Meter Reports'],
    'summary': 'Get power report for a specific meter',
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
            'description': 'Power report for the meter',
            'schema': {
                'type': 'object',
                'properties': {
                    'meter_number': {'type': 'string'},
                    'latest_purchased_power': {'type': 'number'},
                    'current_power': {'type': 'number'},
                    'consumed_power': {'type': 'number'},
                    'purchased_date': {'type': 'string'},
                    'latest_date': {'type': 'string'}
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
def api_port_report(meter_number):
    user = User.query.filter_by(meter_number=meter_number).first()
    if not user:
        return jsonify({'error': 'Meter not found'}), 404

    # Retrieve the latest transaction for this meter
    latest_transaction = Transaction.query.filter_by(meter_number=meter_number)\
                            .order_by(Transaction.date_purchased.desc()).first()
    # Retrieve the latest sensor reading for this meter
    latest_reading = SensorReading.query.filter_by(meter_number=meter_number)\
                        .order_by(SensorReading.reading_time.desc()).first()

    if latest_transaction and latest_transaction.purchase_power is not None:
        purchased_power = latest_transaction.purchase_power
        purchased_date = latest_transaction.date_purchased.strftime("%Y-%m-%d %H:%M:%S")
    else:
        purchased_power = 0.0
        purchased_date = "N/A"

    # Ensure current_power is a float (default to 0.0 if None)
    current_power = user.current_power if user.current_power is not None else 0.0

    # Calculate consumed power as purchased power minus current power.
    # Adjust this logic as needed.
    consumed_power = purchased_power - current_power

    if latest_reading:
        latest_date = latest_reading.reading_time.strftime("%Y-%m-%d %H:%M:%S")
    else:
        latest_date = "N/A"

    return jsonify({
        'meter_number': meter_number,
        'latest_purchased_power': round(purchased_power, 2),
        'current_power': round(current_power, 2),
        'consumed_power': round(consumed_power, 2),
        'purchased_date': purchased_date,
        'latest_date': latest_date
    })


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
# Relay Control Endpoint
####################################
@app.route('/api/relay_control', methods=['POST'])
@swag_from({
    'tags': ['Relay Control'],
    'summary': 'Control relay state for a meter',
    'description': 'Processes relay commands from the web and sends them via MQTT',
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'description': 'Relay control data',
            'schema': {
                'type': 'object',
                'required': ['meter_number', 'state'],
                'properties': {
                    'meter_number': {'type': 'string'},
                    'state': {'type': 'string', 'enum': ['on', 'off']}
                }
            }
        }
    ],
    'responses': {
        200: {
            'description': 'Relay command sent successfully',
            'schema': {
                'type': 'object',
                'properties': {
                    'message': {'type': 'string'}
                }
            }
        },
        400: {
            'description': 'Invalid request parameters',
            'schema': {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'}
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
        },
        500: {
            'description': 'Server error',
            'schema': {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'},
                    'status_code': {'type': 'integer'}
                }
            }
        }
    }
})
def relay_control():
    """
    Processes relay commands from the web.
    Expects JSON payload:
    {
      "meter_number": "12345678",
      "state": "on" or "off"
    }
    """
    try:
        data = request.get_json()
        meter_number = data.get('meter_number')
        state = data.get('state')

        if not meter_number or state not in ["on", "off"]:
            return jsonify({'error': 'Invalid request. Ensure meter_number and state are correct.'}), 400

        # Verify meter exists in database
        user = User.query.filter_by(meter_number=meter_number).first()
        if not user:
            return jsonify({'error': 'Meter number not found'}), 404

        # Construct MQTT payload
        command_payload = json.dumps({
            "meter_number": meter_number,
            "command": state
        })

        # Publish to MQTT topic with error handling
        result = flask_mqtt_client.publish("relay/control", command_payload)
        status = result.rc  # 0 = Success

        if status == 0:
            return jsonify({'message': f"Relay command '{state}' sent to meter {meter_number}."})
        else:
            return jsonify({'error': 'MQTT publish failed', 'status_code': status}), 500

    except Exception as e:
        return jsonify({'error': f"Unexpected error: {str(e)}"}), 500

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

    # Run Flask app (using threaded mode)
    print("Starting Flask app...")
    print("Swagger UI available at: http://localhost:5000/swagger/")
    app.run(debug=True, threaded=True)
