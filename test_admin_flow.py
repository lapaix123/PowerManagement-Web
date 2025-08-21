from zion import app, db, User, Transaction
from flask import url_for

# Create a test client
client = app.test_client()

# Set up the application context
with app.app_context():
    # Log in as admin
    with client.session_transaction() as session:
        # Assuming there's an admin user with ID 1
        session['user_id'] = 1
        session['role'] = 'admin'
        session['username'] = 'admin'
    
    # Test the admin buy electricity flow
    print("Testing admin buy electricity flow...")
    
    # First, get the admin_buy_electricity page
    response = client.get('/admin/buy-electricity')
    print(f"GET /admin/buy-electricity status: {response.status_code}")
    
    # Submit the form with meter number and amount
    response = client.post('/admin/buy-electricity', data={
        'meter_number': 'K000200030005',  # Use a meter number that exists in your database
        'amount': '100'
    }, follow_redirects=False)
    
    # Check if it redirects to the payment page
    print(f"POST /admin/buy-electricity status: {response.status_code}")
    print(f"Redirect location: {response.location}")
    
    if response.status_code == 302 and 'payment' in response.location:
        print("SUCCESS: Admin flow correctly redirects to payment page!")
    else:
        print("FAILURE: Admin flow does not redirect to payment page.")