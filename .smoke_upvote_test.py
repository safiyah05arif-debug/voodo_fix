import requests
import sys

BASE = 'http://127.0.0.1:8000'
session = requests.Session()

print('Fetching issues...')
res = session.get(f'{BASE}/api/issues/')
if res.status_code != 200:
    print('Failed to fetch issues:', res.status_code, res.text)
    sys.exit(1)

issues = res.json()
if not issues:
    print('No issues available to test upvote.')
    sys.exit(1)

issue = issues[0]
issue_id = issue.get('id') or issue.get('_id') or issue.get('object_id') or issue.get('pk')
if not issue_id:
    # try nested
    issue_id = issue.get('id') if isinstance(issue, dict) else None

print('Using issue id:', issue_id)

# Try upvote as anonymous
print('\nAttempting anonymous upvote...')
upvote_res = session.post(f'{BASE}/api/issues/{issue_id}/upvote/')
print('Status:', upvote_res.status_code)
try:
    print('Response:', upvote_res.json())
except Exception:
    print('Response text:', upvote_res.text)

if upvote_res.status_code == 401:
    print('Anonymous upvote correctly rejected (401). Proceeding to dev-login...')
else:
    print('Anonymous upvote did not return 401; continuing anyway.')

# Perform dev-login
print('\nCalling dev-login for ravi-kumar...')
dev_login = session.post(f'{BASE}/api/users/dev-login/', json={'identifier': 'ravi-kumar'})
print('Dev-login status:', dev_login.status_code)
try:
    print('Dev-login response:', dev_login.json())
except Exception:
    print('Dev-login text:', dev_login.text)

if dev_login.status_code != 200:
    print('Dev-login failed; aborting smoke test.')
    sys.exit(2)

# Retry upvote
print('\nRetrying upvote after dev-login...')
upvote_res2 = session.post(f'{BASE}/api/issues/{issue_id}/upvote/')
print('Status:', upvote_res2.status_code)
try:
    out = upvote_res2.json()
    print('Response:', out)
    if upvote_res2.status_code == 200 and out.get('upvote_count') is not None:
        print('\nSmoke test succeeded: upvote recorded. New count =', out.get('upvote_count'))
        sys.exit(0)
    else:
        print('\nSmoke test failed: unexpected response after login')
        sys.exit(3)
except Exception as e:
    print('Upvote retry response text:', upvote_res2.text)
    sys.exit(4)
