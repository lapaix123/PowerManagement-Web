import json
import os
import threading
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
import paho.mqtt.client as mqtt

app = Flask(__name__)
app.secret_key = 'SOME_SECRET_KEY'  # Change for production

# Global MQTT settings
mqtt_server = "192.168.0.51"
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
@app.route('/api/port_report/<meter_number>')
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
def relay_control():
    """
    Processes relay commands from the web.
    Expects JSON payload:
    {
      "meter_number": "12345678",
      "state": "on" or "off"
    }
    """
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

    # Publish to MQTT topic
    try:
        flask_mqtt_client.publish("relay/control", command_payload)
        return jsonify({'message': f"Relay command '{state}' sent to meter {meter_number}."})
    except Exception as e:
        return jsonify({'error': f"MQTT publish failed: {str(e)}"}), 500


####################################
# MQTT Subscriber (Embedded)
####################################
def mqtt_on_connect(client, userdata, flags, rc):
    print("Connected to MQTT broker with result code " + str(rc))
    client.subscribe("power/monitor")
    client.subscribe("relay/control")

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

def start_mqtt_subscriber():
    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = mqtt_on_connect
    mqtt_client.on_message = mqtt_on_message
    mqtt_client.connect(mqtt_server, mqtt_port, 60)
    print("Starting MQTT subscriber loop...")
    mqtt_client.loop_forever()

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

####################################
# Main Execution: Start Flask and MQTT Subscriber
####################################
if __name__ == "__main__":
    # Start MQTT subscriber in a separate thread
    mqtt_thread = threading.Thread(target=start_mqtt_subscriber)
    mqtt_thread.daemon = True
    mqtt_thread.start()
    
    # Run Flask app (using threaded mode)
    app.run(debug=True, threaded=True)
