import json
from web import app


async def test_info(test_client, loop):
    client = await test_client(app)
    resp = await client.get('/api/info')
    assert resp.status == 200

    text = await resp.text()
    j = json.loads(text)

    assert j['name'] == 'AirHead'
    assert j['greet_message'] == 'Welcome!'
    assert j['stream_url'] == 'http://127.0.0.1:8000/airhead'
