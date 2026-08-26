import requests
s = requests.Session()
base = 'http://127.0.0.1:8000'
login = s.post(base + '/api/users/login/', json={'identifier':'murugan-s','password':'demo123'})
print('LOGIN', login.status_code)
try:
    print('LOGIN JSON', login.json())
except Exception as e:
    print('LOGIN JSON ERR', e)
resp = s.get(base + '/api/tasks/assigned/')
print('TASKS', resp.status_code)
try:
    data = resp.json()
    if isinstance(data, list):
        print('TASKS DATA LENGTH', len(data))
        if data:
            print('SAMPLE TITLE:', data[0].get('title'), 'assigned_to=', data[0].get('assigned_to'))
    else:
        print('TASKS DATA:', data)
except Exception as e:
    print('TASKS JSON ERR', e)
