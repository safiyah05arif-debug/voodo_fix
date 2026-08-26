"""
Quick MongoDB Atlas TLS diagnostic.
Attempts connections with different TLS options and prints exceptions.
Run: python diagnose_mongo.py
"""
import os
from dotenv import load_dotenv
import certifi
from pymongo import MongoClient

# Load .env so MONGODB_URI from project file is available
load_dotenv()

uri = os.getenv('MONGODB_URI')
if not uri:
    print('No MONGODB_URI in environment')
    raise SystemExit(1)

print('Testing URI:', uri)

configs = [
    {'desc': 'SRV default with certifi', 'kwargs': {'tls': True, 'tlsCAFile': certifi.where()}},
    {'desc': 'SRV allow invalid certs (diagnostic only)', 'kwargs': {'tls': True, 'tlsCAFile': certifi.where(), 'tlsAllowInvalidCertificates': True}},
    {'desc': 'No TLS (direct mongodb:// fallback)', 'kwargs': {}},
]

for cfg in configs:
    print('\n---')
    print('Config:', cfg['desc'])
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000, **cfg['kwargs'])
        info = client.server_info()
        print('Connected OK:', info.get('version'))
    except Exception as e:
        print('Error:', type(e).__name__, str(e))

print('\nDiagnostics complete')
