from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import paho.mqtt.client as mqtt

app = Flask(__name__)
app.secret_key = 'SOME_SECRET_KEY'  # Change for production

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
    purchase_power = db.Column(db.Float)  # Newly added column for the purchased power (in W)
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
# Utility: Database Init
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
    """Simple session-based login."""
    session['user_id'] = user.id
    session['role'] = user.role
    session['username'] = user.username

def current_user():
    """Return the currently logged in user object, or None."""
    if 'user_id' in session:
       return db.session.get(User, session['user_id'])
    return None

def logout_user():
    """Clear session."""
    session.pop('user_id', None)
    session.pop('role', None)
    session.pop('username', None)

def is_admin():
    return (session.get('role') == 'admin')


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
        
        # Check if meter_number or username already exist
        existing_user = User.query.filter((User.username == username)|(User.meter_number == meter_number)).first()
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
    """
    Returns a JSON list of users filtered by search query (username or meter_number).
    Example: /admin/api/users?search=john
    """
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
    """
    Receives JSON data to update user fields inline.
    e.g. { "username": "...", "meter_number": "...", "province": "...", "district": "...", "sector": "...", "current_power": "..." }
    """
    user = User.query.get_or_404(user_id)
    data = request.json

    # Validate/clean as needed
    user.username = data.get('username', user.username)
    user.meter_number = data.get('meter_number', user.meter_number)
    user.province = data.get('province', user.province)
    user.district = data.get('district', user.district)
    user.sector = data.get('sector', user.sector)
    
    # Convert current_power carefully
    try:
        user.current_power = float(data.get('current_power', user.current_power))
    except ValueError:
        pass

    db.session.commit()

    return jsonify({"success": True})


@app.route('/admin/api/users/<int:user_id>/delete', methods=['DELETE'])
def admin_api_users_delete(user_id):
    """
    Deletes the user with the given ID.
    """
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/admin/other_users', endpoint='other_admin_users')
def other_admin_users_page():
    return render_template('other_admin_users.html')

@app.route('/admin/view-meter', methods=['GET', 'POST'])
def admin_view_meter():
    """View meter data (Power, Current, Voltage) for a specific meter."""
   # if not is_admin():
      #  flash("Access denied.", "error")
     #   return redirect(url_for('home'))
    
    meter_data = None
    if request.method == 'POST':
        meter_number = request.form.get('meter_number')
        # Get the latest reading from sensor_readings
        meter_data = SensorReading.query.filter_by(meter_number=meter_number)\
                      .order_by(SensorReading.id.desc()).first()
        if not meter_data:
            flash("No data found for that meter.", "error")

    return render_template('admin_view_meter.html', meter_data=meter_data)

@app.route('/admin/buy-electricity', methods=['GET','POST'])
def admin_buy_electricity():
    # if not is_admin():
    #     flash("Access denied.", "error")
    #     return redirect(url_for('home'))
    
    if request.method == 'POST':
        meter_number = request.form.get('meter_number')
        amount_str = request.form.get('amount', '0')
        
        try:
            amount = float(amount_str)
        except ValueError:
            amount = 0.0
        
        user = User.query.filter_by(meter_number=meter_number).first()
        
        if user:
            # When someone pays 1000, they will get 2 watts (1000 / 500 = 2)
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
    # Must be logged in
    user = current_user()
    if not user:
        flash("Please log in first.", "error")
        return redirect(url_for('login'))
    
    # Return data for the user’s own meter
    meter_data = SensorReading.query.filter_by(meter_number=user.meter_number)\
                    .order_by(SensorReading.id.desc()).first()
    return render_template('user_dashboard.html', meter_data=meter_data, user=user)

@app.route('/user/buy-electricity', methods=['POST'])
def user_buy_electricity():
    user = current_user()
    if not user:
        flash("Please log in first.", "error")
        return redirect(url_for('login'))

    buy_for = request.form.get('buy_for')  # 'self' or 'other'
    if buy_for == 'self':
        amount = float(request.form.get('amount', 0))
        purchased_watts = amount * 500.0  # Example conversion
        user.current_power += purchased_watts
        db.session.add(Transaction(
            user_id=user.id,
            meter_number=user.meter_number,
            purchase_amount=amount
        ))
        db.session.commit()
        flash(f"You purchased {purchased_watts} W for yourself.", "success")
        return redirect(url_for('user_dashboard'))
    else:
        # buy for another user
        other_meter = request.form.get('other_meter_number')
        amount = float(request.form.get('amount', 0))
        other_user = User.query.filter_by(meter_number=other_meter).first()
        if not other_user:
            flash("Meter not found.", "error")
            return redirect(url_for('user_dashboard'))
        purchased_watts = amount * 500.0
        other_user.current_power += purchased_watts
        db.session.add(Transaction(
            user_id=other_user.id,
            meter_number=other_meter,
            purchase_amount=amount
        ))
        db.session.commit()
        flash(f"You purchased {purchased_watts} W for {other_user.username}.", "success")
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
# AJAX Endpoints
####################################
@app.route('/api/latest-reading/<meter_number>')
def api_latest_reading(meter_number):
    """Return latest sensor reading in JSON for the specified meter."""
    reading = SensorReading.query.filter_by(meter_number=meter_number)\
                  .order_by(SensorReading.id.desc()).first()
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
    """
    Endpoint for the ESP32 (or any device) to send real-time usage info:
    - meter_number
    - voltage
    - current
    - power_consumed_in_this_interval
    
    We'll subtract the consumed amount from user.current_power and log it.
    """
    data = request.json
    meter_number = data.get('meter_number')
    voltage = data.get('voltage')
    current = data.get('current')
    power_consumed = data.get('power_consumed', 0.0)  # in W
    
    user = User.query.filter_by(meter_number=meter_number).first()
    if user:
        # Subtract consumed power
        if user.current_power > 0:
            user.current_power -= power_consumed
            if user.current_power < 0:
                user.current_power = 0  # no negative

        # Store the reading in sensor_readings
        sr = SensorReading(
            meter_number=meter_number,
            voltage=voltage,
            current=current,
            power=power_consumed
        )
        db.session.add(sr)
        db.session.commit()

        return jsonify({
            'status': 'OK',
            'remaining_power': user.current_power
        })
    else:
        return jsonify({'error': 'Meter not found'}), 404


if __name__ == "__main__":
    app.run(debug=True)
   
