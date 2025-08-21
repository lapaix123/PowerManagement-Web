from zion import app

# Create a test client
client = app.test_client()

# Test accessing admin pages without login
with app.app_context():
    print("Testing admin access without login...")
    
    # Test admin dashboard
    response = client.get('/admin')
    print(f"Admin dashboard status: {response.status_code}")
    if response.status_code == 200:
        print("SUCCESS: Admin dashboard is accessible without login!")
    else:
        print(f"FAILURE: Admin dashboard returned status code {response.status_code}")
    
    # Test admin messages
    response = client.get('/admin/messages')
    print(f"Admin messages status: {response.status_code}")
    if response.status_code == 200:
        print("SUCCESS: Admin messages is accessible without login!")
    else:
        print(f"FAILURE: Admin messages returned status code {response.status_code}")
    
    # Test admin buy electricity
    response = client.get('/admin/buy-electricity')
    print(f"Admin buy electricity status: {response.status_code}")
    if response.status_code == 200:
        print("SUCCESS: Admin buy electricity is accessible without login!")
    else:
        print(f"FAILURE: Admin buy electricity returned status code {response.status_code}")
    
    print("\nAll tests completed.")