import sys
import os

# IMPORTANT: Change 'yourusername' to your actual PythonAnywhere username
# Change 'inventory-app' to your actual folder name on PythonAnywhere

project_home = '/home/yourusername/inventory-app'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Set environment variables (optional - for production)
# os.environ['ADMIN_PASSWORD'] = 'your-secure-admin-password'
# os.environ['SESSION_SECRET'] = 'your-secure-session-secret'

from app import app as application
