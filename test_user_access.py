from zion import app

# Create a test client
client = app.test_client()

# Test accessing user pages without login
with app.app_context():
    print("Testing user access without login...")
    
    # Test user dashboard
    response = client.get('/user')
    print(f"User dashboard status: {response.status_code}")
    if response.status_code == 302:  # Redirect to login
        print("SUCCESS: User dashboard requires login!")
    else:
        print(f"FAILURE: User dashboard returned status code {response.status_code}")
    
    # Test user messages
    response = client.get('/user/messages')
    print(f"User messages status: {response.status_code}")
    if response.status_code == 302:  # Redirect to login
        print("SUCCESS: User messages requires login!")
    else:
        print(f"FAILURE: User messages returned status code {response.status_code}")
    
    print("\nAll tests completed.")