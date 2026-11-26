"""Socket.IO contract (Module 5 real-time updates, used by Modules 6 and 10–12).

Unit tests drive HTTP only, so a Flask / Flask-SocketIO incompatibility once broke every socket
event while all other tests passed. This exercises the /metrics namespace directly.
"""

from app import socketio


def test_join_room_and_receive_org_scoped_events(app):
    client = socketio.test_client(app, namespace='/metrics')
    assert client.is_connected('/metrics')
    client.emit('join_room', {'org_id': 7}, namespace='/metrics')
    socketio.emit('threats:update', {'org_id': 7}, room='org_7', namespace='/metrics')
    socketio.emit('threats:update', {'org_id': 8}, room='org_8', namespace='/metrics')
    received = [m for m in client.get_received('/metrics') if m['name'] == 'threats:update']
    assert [m['args'][0]['org_id'] for m in received] == [7]  # only its own organization's events
    client.disconnect(namespace='/metrics')


def test_switching_organization_leaves_the_previous_room(app):
    client = socketio.test_client(app, namespace='/metrics')
    client.emit('join_room', {'org_id': 1}, namespace='/metrics')
    client.emit('join_room', {'org_id': 2}, namespace='/metrics')
    socketio.emit('dashboard_update', {'org_id': 1}, room='org_1', namespace='/metrics')
    assert not [m for m in client.get_received('/metrics') if m['name'] == 'dashboard_update']
    client.disconnect(namespace='/metrics')
