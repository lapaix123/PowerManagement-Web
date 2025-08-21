import sqlite3
import os

# Path to the database file
db_path = 'cashpower.db'

# Check if the database file exists
if not os.path.exists(db_path):
    print(f"Database file {db_path} not found.")
    exit(1)

# Connect to the database
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check if the messages table already exists
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
table_exists = cursor.fetchone()

if not table_exists:
    print("Creating messages table...")
    try:
        # Create the messages table
        cursor.execute('''
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            is_read BOOLEAN DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sender_id) REFERENCES users (id),
            FOREIGN KEY (receiver_id) REFERENCES users (id)
        )
        ''')
        conn.commit()
        print("Messages table created successfully.")
    except sqlite3.Error as e:
        print(f"Error creating messages table: {e}")
        conn.rollback()
else:
    print("Messages table already exists.")

# Close the connection
conn.close()
print("Database migration completed.")