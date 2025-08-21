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

# Check if the payment_method column already exists
cursor.execute("PRAGMA table_info(transactions)")
columns = cursor.fetchall()
column_names = [column[1] for column in columns]

if 'payment_method' not in column_names:
    print("Adding payment_method column to transactions table...")
    try:
        # Add the payment_method column
        cursor.execute("ALTER TABLE transactions ADD COLUMN payment_method TEXT")
        conn.commit()
        print("Column added successfully.")
    except sqlite3.Error as e:
        print(f"Error adding column: {e}")
        conn.rollback()
else:
    print("payment_method column already exists in transactions table.")

# Close the connection
conn.close()
print("Database migration completed.")