from flask import Blueprint, jsonify

from app.data.learning_content import LEARNING_CONTENT

learning_bp = Blueprint('learning', __name__)


@learning_bp.route('/content/<action_key>', methods=['GET'])
def get_learning_content(action_key):
    content = LEARNING_CONTENT.get((action_key or '').strip().lower())
    if not content:
        return jsonify({'error': {'message': 'Learning content not found'}}), 404
    return jsonify({
        'status': 'success',
        'data': {
            'action_key': action_key,
            **content,
        },
    }), 200
