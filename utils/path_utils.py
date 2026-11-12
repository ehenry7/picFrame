"""Path helpers for building URL-safe static filenames.

On Windows, filesystem paths use backslashes (``\\``), which Flask's
``url_for('static', filename=...)`` percent-encodes to ``%5C``. That produces
broken URLs and 404s for prepared images. These helpers normalize any path-like
value to forward slashes before it is handed to ``url_for``.
"""

from pathlib import PurePath


def to_static_url_path(value):
    """Return *value* as a string using forward slashes.

    Accepts a ``str`` or ``os.PathLike``/``pathlib.Path``. Backslashes are
    converted to ``/`` so the result is safe to pass as the ``filename``
    argument of ``url_for('static', ...)`` on every platform.
    """
    if isinstance(value, PurePath):
        return value.as_posix()
    return str(value).replace("\\", "/")
