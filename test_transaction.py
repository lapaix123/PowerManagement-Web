from zion import app, db, Transaction, User
from datetime import datetime

# Create an application context
with app.app_context():
    # Check if a user with the meter number exists
    user = User.query.filter_by(meter_number='K000200030005').first()

    if not user:
        # Create a test user with a different meter number if needed
        user = User(
            username='test_user_' + datetime.now().strftime('%Y%m%d%H%M%S'),
            password='password',
            phone='1234567890',
            meter_number='K000200030005_TEST',
            province='Test Province',
            district='Test District',
            sector='Test Sector',
            gender='Male',
            role='user',
            current_power=0.0
        )
        db.session.add(user)
        db.session.commit()
        print(f"Created test user with ID: {user.id}")
    else:
        print(f"Using existing user with ID: {user.id} and meter number: {user.meter_number}")

    # Create a test transaction with payment_method
    transaction = Transaction(
        user_id=user.id,
        meter_number=user.meter_number,
        purchase_power=None,
        purchase_amount=100.0,
        payment_method='mtn',
        date_purchased=datetime.now()
    )

    # Add and commit the transaction
    db.session.add(transaction)
    db.session.commit()

    print(f"Transaction created successfully with ID: {transaction.id}")
    print(f"Payment method: {transaction.payment_method}")
