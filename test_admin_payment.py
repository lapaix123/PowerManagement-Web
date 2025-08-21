from zion import app
from flask import url_for

# Create a test client
client = app.test_client()

# Test the admin payment flow
with app.app_context():
    # Test accessing the payment page directly with admin parameters
    print("Testing direct access to payment page with admin parameters...")
    
    response = client.get('/payment?amount=100&buy_for=admin&meter_number=K000200030005')
    
    # Check if the payment page is rendered (not redirected to login)
    print(f"Response status code: {response.status_code}")
    
    if response.status_code == 200:
        print("SUCCESS: Payment page is rendered directly for admin!")
        # Check if the page contains payment options
        if b'MTN Mobile Money' in response.data and b'Airtel Money' in response.data:
            print("Payment options are displayed correctly.")
        else:
            print("WARNING: Payment options might not be displayed correctly.")
    else:
        print(f"FAILURE: Got status code {response.status_code} instead of 200")
        if response.location and 'login' in response.location:
            print("Still redirecting to login page!")