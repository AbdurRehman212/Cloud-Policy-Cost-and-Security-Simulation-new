"""JWT identity helpers.

PyJWT >= 2.10 requires the ``sub`` claim to be a string (RFC 7519), so tokens carry the user
id as text (see ``user_identity_loader`` in ``app/__init__.py``). Route code compares the
identity with integer columns, so this helper returns it as an ``int`` again. Routes import
``get_jwt_identity`` from here instead of from ``flask_jwt_extended``.
"""

from flask_jwt_extended import get_jwt_identity as _raw_identity


def get_jwt_identity():
    value = _raw_identity()
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value
