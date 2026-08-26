import requests
BASE='http://127.0.0.1:8000'
res = requests.post(f'{BASE}/api/users/login/', json={'identifier':'ravi-kumar','password':'demo123'})
print(res.status_code)
try:
    print(res.json())
except Exception:
    print(res.text)
