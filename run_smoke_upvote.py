import requests
import sys

BASE = 'http://127.0.0.1:8000'
session = requests.Session()
session.headers.update({'Accept': 'application/json'})

print('Performing dev-login (ravi-kumar)')
dev_login = session.post(f'{BASE}/api/users/dev-login/', json={'identifier': 'ravi-kumar'})
print('Dev-login status:', dev_login.status_code)
try:
    print('Dev-login response:', dev_login.json().get('message'))
except Exception:
    print('Dev-login text:', dev_login.text)

if dev_login.status_code != 200:
    print('Dev-login failed; aborting smoke test.')
    sys.exit(2)

print('\nFetching issues...')
res = session.get(f'{BASE}/api/issues/')
print('Issues fetch status:', res.status_code)
if res.status_code != 200:
    try:
        print('Error:', res.json())
    except Exception:
        print('Error text:', res.text[:200])
    sys.exit(1)

issues = res.json()
if not issues:
    print('No issues available to test upvote.')
    sys.exit(1)

issue = issues[0]
issue_id = issue.get('id') or issue.get('_id') or issue.get('object_id') or issue.get('pk')
if not issue_id:
    issue_id = issue.get('id') if isinstance(issue, dict) else None

print('Using issue id:', issue_id)

print('\nAttempting upvote after dev-login...')
upvote_res = session.post(f'{BASE}/api/issues/{issue_id}/upvote/')
print('Upvote status:', upvote_res.status_code)
try:
    out = upvote_res.json()
    print('Upvote response:', out)
    if upvote_res.status_code == 200 and out.get('upvote_count') is not None:
        print('\nSmoke test succeeded: upvote recorded. New count =', out.get('upvote_count'))
        sys.exit(0)
    else:
        print('\nSmoke test failed: unexpected response')
        sys.exit(3)
except Exception:
    print('Upvote response text (truncated):', upvote_res.text[:200])
    sys.exit(4)
