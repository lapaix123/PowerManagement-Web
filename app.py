import json
import os
import threading
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
import paho.mqtt.client as mqtt
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from django.contrib.auth.decorators import login_required



app = Flask(__name__)
app.secret_key = 'SOME_SECRET_KEY'  # Change for production
CORS(app, supports_credentials=True)

# # Global MQTT settings
mqtt_server = "192.168.0.51"
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
    role = db.Column(db.String(10), default='user')  # 'admin' or 'user'
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

# ####################################
# # Global MQTT Publisher
# ####################################
# Create a global MQTT publisher for relay commands.
flask_mqtt_client = mqtt.Client(client_id="flask_publisher", protocol=mqtt.MQTTv311)
flask_mqtt_client.connect(mqtt_server, mqtt_port, 60)

####################################
# Routes
####################################
@app.route('/')
def home():
    return render_template('home.html')  # Basic home page

@app.route('/register', methods=['GET', 'POST'])
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
def logout():
    logout_user()
    return redirect(url_for('home'))

####################################
# Admin Section
####################################
@app.route('/admin', methods=['GET'])
def admin_dashboard():
    users = User.query.all()
    return render_template('admin_dashboard.html', users=users)

@app.route('/admin/api/users')
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
def admin_api_users_delete(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/admin/other_users', endpoint='other_admin_users')
def other_admin_users_page():
    return render_template('other_admin_users.html')

@app.route('/admin/view-meter', methods=['GET', 'POST'])
def admin_view_meter():
    meter_data = None
    if request.method == 'POST':
        meter_number = request.form.get('meter_number')
        meter_data = SensorReading.query.filter_by(meter_number=meter_number).order_by(SensorReading.id.desc()).first()
        if not meter_data:
            flash("No data found for that meter.", "error")
    return render_template('admin_view_meter.html', meter_data=meter_data)

@app.route('/admin/buy-electricity', methods=['GET','POST'])
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
def user_dashboard():
    user = current_user()
    if not user:
        flash("Please log in first.", "error")
        return redirect(url_for('login'))
    meter_data = SensorReading.query.filter_by(meter_number=user.meter_number).order_by(SensorReading.id.desc()).first()
    return render_template('user_dashboard.html', meter_data=meter_data, user=user)

@app.route('/user/buy-electricity', methods=['POST'])
def user_buy_electricity():
    user = current_user()
    if not user:
        flash("Please log in first.", "error")
        return redirect(url_for('login'))

    buy_for = request.form.get('buy_for')
    if buy_for == 'self':
        raw_amount = request.form.get('amount', '0')
        try:
            amount = round(float(raw_amount), 2)
        except ValueError:
            amount = 0.0
        purchased_watts = amount / 500.0
        user.current_power += purchased_watts
        db.session.add(Transaction(
            user_id=user.id,
            meter_number=user.meter_number,
            purchase_amount=amount
        ))
        db.session.commit()
        flash(f"You purchased {purchased_watts:.2f} W for yourself.", "success")
        return redirect(url_for('user_dashboard'))
    else:
        other_meter = request.form.get('other_meter_number')
        raw_amount = request.form.get('amount', '0')
        try:
            amount = round(float(raw_amount), 2)
        except ValueError:
            amount = 0.0
        other_user = User.query.filter_by(meter_number=other_meter).first()
        if not other_user:
            flash("Meter not found.", "error")
            return redirect(url_for('user_dashboard'))
        purchased_watts = amount / 500.0
        other_user.current_power += purchased_watts
        db.session.add(Transaction(
            user_id=other_user.id,
            meter_number=other_meter,
            purchase_amount=amount
        ))
        db.session.commit()
        flash(f"You purchased {purchased_watts:.2f} W for {other_user.username}.", "success")
        return redirect(url_for('user_dashboard'))



@app.route('/admin/check_meter')
def check_meter():
    meter = request.args.get('meter', '')
    user = User.query.filter_by(meter_number=meter).first()
    if user:
        return jsonify({'exists': True, 'username': user.username})
    else:
        return jsonify({'exists': False})

@app.route('/admin/users')
def admin_users_page():
    return render_template('admin_users.html')

####################################
# Report
####################################
@app.route('/api/port_report')
@login_required
def api_port_report():
    try:
        # Get the current logged-in user
        user = current_user
        
        if not user.meter_number:
            return jsonify({
                'success': False,
                'error': 'User does not have a meter number assigned'
            }), 400

        # Retrieve the latest transaction for this meter
        latest_transaction = Transaction.query.filter_by(meter_number=user.meter_number)\
                                .order_by(Transaction.date_purchased.desc()).first()
        # Retrieve the latest sensor reading for this meter
        latest_reading = SensorReading.query.filter_by(meter_number=user.meter_number)\
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
        consumed_power = purchased_power - current_power

        if latest_reading:
            latest_date = latest_reading.reading_time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            latest_date = "N/A"

        app.logger.info(f"Generated port report for user: {user.username} (meter: {user.meter_number})")
        
        return jsonify({
            'success': True,
            'meter_number': user.meter_number,
            'latest_purchased_power': round(purchased_power, 2),
            'current_power': round(current_power, 2),
            'consumed_power': round(consumed_power, 2),
            'purchased_date': purchased_date,
            'latest_date': latest_date
        })

    except Exception as e:
        app.logger.error(f"Error generating port report: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


####################################
# AJAX Endpoints 
####################################
@app.route('/api/latest-reading/<meter_number>')
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
@login_required
def relay_control():
    """
    Processes relay commands from the web.
    Expects JSON payload:
    {
      "state": "on" or "off"  # Only state is required
    }
    Uses the logged-in user's meter number automatically.
    """
    try:
        data = request.get_json()
        state = data.get('state')

        if state not in ["on", "off"]:
            return jsonify({
                'success': False,
                'error': 'Invalid request. State must be "on" or "off".'
            }), 400

        # Get meter number from logged-in user
        meter_number = current_user.meter_number
        if not meter_number:
            return jsonify({
                'success': False,
                'error': 'No meter number associated with this account'
            }), 400

        # Construct MQTT payload
        command_payload = json.dumps({
            "meter_number": meter_number,
            "command": state
        })

        # Publish to MQTT topic with error handling
        result = flask_mqtt_client.publish("relay/control", command_payload)
        status = result.rc  # 0 = Success

        if status == 0:
            app.logger.info(f"Relay command '{state}' sent to meter {meter_number}")
            return jsonify({
                'success': True,
                'message': f"Relay command '{state}' sent to your meter.",
                'meter_number': meter_number,
                'state': state
            })
        else:
            app.logger.error(f"MQTT publish failed for meter {meter_number}, status: {status}")
            return jsonify({
                'success': False,
                'error': 'Failed to send command to device',
                'status_code': status
            }), 500

    except Exception as e:
        app.logger.error(f"Relay control error: {str(e)}")
        return jsonify({
            'success': False,
            'error': f"Unexpected error: {str(e)}"
        }), 500
    
####################################
# MOBILE APP ENDPOINTS
####################################
# API Routes
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json()
    
    # Validation
    required_fields = ['username', 'password', 'phone', 'meter_number', 
                     'gender', 'province', 'district', 'sector']
    if not all(field in data for field in required_fields):
        return jsonify({"success": False, "error": "All fields are required"}), 400
    
    # Check existing user
    existing_user = User.query.filter(
        (User.username == data['username']) | 
        (User.meter_number == data['meter_number'])
    ).first()
    
    if existing_user:
        return jsonify({
            "success": False,
            "error": "Username or Meter Number already exists"
        }), 409

    # Create user with hashed password
    try:
        new_user = User(
            username=data['username'],
            password=generate_password_hash(data['password']),
            phone=data['phone'],
            meter_number=data['meter_number'],
            gender=data['gender'],
            province=data['province'],
            district=data['district'],
            sector=data['sector'],
            role='user',
            current_power=0.0
        )
        db.session.add(new_user)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Registration successful",
            "user": {
                "id": new_user.id,
                "username": new_user.username
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/login', methods=['POST'])
def api_login():
    try:
        data = request.get_json()
        
        # Debug logging
        app.logger.info(f"Login attempt with data: {data}")
        
        if not data:
            return jsonify({
                "success": False,
                "error": "Request body must be JSON",
                "received_data": str(request.data)  # For debugging
            }), 400
            
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            missing = []
            if not username: missing.append('username')
            if not password: missing.append('password')
            return jsonify({
                "success": False,
                "error": "Missing required fields",
                "missing_fields": missing
            }), 400

        user = User.query.filter_by(username=username).first()
        
        if not user:
            app.logger.warning(f"Login failed - user not found: {username}")
            return jsonify({
                "success": False,
                "error": "Invalid credentials"
            }), 401
            
        if not check_password_hash(user.password, password):
            app.logger.warning(f"Login failed - invalid password for user: {username}")
            return jsonify({
                "success": False,
                "error": "Invalid credentials"
            }), 401

        # Login successful
        login_user(user)
        app.logger.info(f"Login successful for user: {username}")
        
        return jsonify({
            "success": True,
            "message": "Login successful",
            "user": {
                "id": user.id,
                "username": user.username,
                "role": user.role,
                "meter_number": user.meter_number
            }
        })

    except Exception as e:
        app.logger.error(f"Login error: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({"success": True, "message": "Logged out"})

@app.route('/api/check_meter', methods=['GET'])
def api_check_meter():
    meter_number = request.args.get('meter_number')
    if not meter_number:
        return jsonify({"success": False, "error": "Meter number required"}), 400
    
    user = User.query.filter_by(meter_number=meter_number).first()
    return jsonify({
        "success": True,
        "exists": user is not None,
        "user": {
            "username": user.username if user else None,
            "meter_number": user.meter_number if user else None
        }
    })

# User endpoints
@app.route('/api/user', methods=['GET'])
def api_get_user():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404
    
    return jsonify({
        "success": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "phone": user.phone,
            "meter_number": user.meter_number,
            "current_power": user.current_power,
            "province": user.province,
            "district": user.district,
            "sector": user.sector
        }
    })

@app.route('/api/buy-electricity', methods=['POST'])
def api_buy_electricity():
    try:
        # Validate request format
        if not request.is_json:
            return jsonify({
                "success": False,
                "error": "Request must be JSON"
            }), 400

        data = request.get_json()
        user = current_user()

        # Authentication check
        if not user:
            return jsonify({
                "success": False,
                "error": "Authentication required"
            }), 401

        # Validate required fields
        if 'amount' not in data or not str(data['amount']).strip():
            return jsonify({
                "success": False,
                "error": "Amount is required"
            }), 400

        # Parse amount
        try:
            amount = round(float(data['amount']), 2)
            if amount <= 0:
                raise ValueError
        except ValueError:
            return jsonify({
                "success": False,
                "error": "Invalid amount"
            }), 400

        # Conversion rate (1 RWF = 500 W)
        CONVERSION_RATE = 500.0
        purchased_watts = amount / CONVERSION_RATE

        # Handle different purchase types
        if data.get('buy_for') == 'other':
            if 'meter_number' not in data:
                return jsonify({
                    "success": False,
                    "error": "Recipient meter number required"
                }), 400

            recipient = User.query.filter_by(meter_number=data['meter_number']).first()
            if not recipient:
                return jsonify({
                    "success": False,
                    "error": "Recipient meter not found"
                }), 404

            # Update recipient's balance
            recipient.current_power += purchased_watts
            target_user = recipient
        else:
            # Update current user's balance
            user.current_power += purchased_watts
            target_user = user

        # Record transaction
        transaction = Transaction(
            user_id=target_user.id,
            meter_number=target_user.meter_number,
            purchase_amount=amount,
            purchase_power=purchased_watts,
            date_purchased=datetime.utcnow()
        )

        db.session.add(transaction)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": f"Successfully purchased {purchased_watts:.2f} W",
            "data": {
                "transaction_id": transaction.id,
                "meter_number": target_user.meter_number,
                "amount": amount,
                "power": purchased_watts,
                "new_balance": target_user.current_power,
                "timestamp": transaction.date_purchased.isoformat()
            }
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False,
            "error": "Transaction failed",
            "details": str(e)
        }), 500
    
# Transaction endpoints
@app.route('/api/transactions', methods=['POST'])
def api_create_transaction():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    data = request.get_json()
    required_fields = ['meter_number', 'amount']
    if not all(field in data for field in required_fields):
        return jsonify({"success": False, "error": "Meter number and amount required"}), 400

    try:
        amount = float(data['amount'])
    except ValueError:
        return jsonify({"success": False, "error": "Invalid amount"}), 400

    user = User.query.filter_by(meter_number=data['meter_number']).first()
    if not user:
        return jsonify({"success": False, "error": "Meter not found"}), 404

    purchased_power = amount / 500.0  # Adjust this calculation as needed
    user.current_power += purchased_power
    
    transaction = Transaction(
        user_id=user.id,
        meter_number=user.meter_number,
        purchase_amount=amount,
        purchase_power=purchased_power
    )
    
    db.session.add(transaction)
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "Transaction completed",
        "transaction": {
            "id": transaction.id,
            "meter_number": transaction.meter_number,
            "amount": transaction.purchase_amount,
            "power": transaction.purchase_power,
            "date": transaction.date_purchased.isoformat()
        }
    })

# Sensor data endpoints
@app.route('/api/sensor_readings', methods=['POST'])
def api_create_reading():
    data = request.get_json()
    required_fields = ['meter_number', 'voltage', 'current', 'power']
    if not all(field in data for field in required_fields):
        return jsonify({"success": False, "error": "Missing required fields"}), 400

    try:
        reading = SensorReading(
            meter_number=data['meter_number'],
            voltage=float(data['voltage']),
            current=float(data['current']),
            power=float(data['power'])
        )
        db.session.add(reading)
        
        # Update user's current power
        user = User.query.filter_by(meter_number=data['meter_number']).first()
        if user and user.current_power > 0:
            user.current_power = max(0, user.current_power - float(data['power']))
        
        db.session.commit()
        return jsonify({"success": True, "message": "Reading recorded"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/sensor_readings/latest', methods=['GET'])
def api_get_latest_reading():
    meter_number = request.args.get('meter_number')
    if not meter_number:
        return jsonify({"success": False, "error": "Meter number required"}), 400
    
    reading = SensorReading.query.filter_by(meter_number=meter_number)\
                .order_by(SensorReading.reading_time.desc()).first()
    
    if not reading:
        return jsonify({"success": False, "error": "No readings found"}), 404
    
    return jsonify({
        "success": True,
        "reading": {
            "voltage": reading.voltage,
            "current": reading.current,
            "power": reading.power,
            "timestamp": reading.reading_time.isoformat()
        }
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)



# ####################################
# # MQTT Subscriber (Embedded)
# ####################################

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

# ####################################
# # Main Execution: Start Flask and MQTT Subscriber
# ####################################
if __name__ == "__main__":
    # Start MQTT subscriber in a separate thread
    mqtt_thread = threading.Thread(target=start_mqtt_subscriber)
    mqtt_thread.daemon = True
    mqtt_thread.start()
    
    # Run Flask app (using threaded mode)
    app.run(debug=True, threaded=True)
