"""One-off probe for forgot-password POST behaviour."""
import re
import logging

logging.basicConfig(level=logging.INFO)

from app import create_app

app = create_app()
client = app.test_client()

r = client.get('/auth/forgot-password')
print('GET', r.status_code)
html = r.get_data(as_text=True)
m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
csrf = m.group(1) if m else None
print('csrf_found', bool(csrf))

r2 = client.post(
    '/auth/forgot-password',
    data={'email': 'mwangingari2@gmail.com', 'csrf_token': csrf},
    follow_redirects=False,
)
print('POST ok csrf', r2.status_code, 'Location', r2.headers.get('Location'))

r3 = client.post(
    '/auth/forgot-password',
    data={'email': 'mwangingari2@gmail.com', 'csrf_token': 'bad'},
    follow_redirects=False,
)
print('POST bad csrf', r3.status_code, 'Location', r3.headers.get('Location'))

with client.session_transaction() as sess:
    flashes = sess.get('_flashes')
    print('flashes after bad csrf', flashes)
