"""Small requests-compatible HTTP subset used by the Notion report scripts.

The bundled Codex Python runtime does not ship the third-party ``requests``
package.  This module keeps the existing Notion workflow runnable with the
standard library.  It intentionally implements only the calls used in
``notion_push_lib.py`` and the report verifier.
"""

from __future__ import annotations

import json as _json
import socket
import ssl
import urllib.error
import urllib.request
import uuid


class RequestException(Exception):
    pass


class SSLError(RequestException):
    pass


class ConnectionError(RequestException):
    pass


class Timeout(RequestException):
    pass


class HTTPError(RequestException):
    pass


class _Exceptions:
    RequestException = RequestException
    SSLError = SSLError
    ConnectionError = ConnectionError
    Timeout = Timeout
    HTTPError = HTTPError


exceptions = _Exceptions()


class Response:
    def __init__(self, status_code: int, body: bytes, headers=None):
        self.status_code = status_code
        self.content = body
        self.headers = headers or {}

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return _json.loads(self.text)

    def raise_for_status(self):
        if not 200 <= self.status_code < 300:
            detail = self.text[:500]
            raise HTTPError(f"HTTP {self.status_code}: {detail}")


def _multipart(files):
    boundary = "----codex-" + uuid.uuid4().hex
    chunks = []
    for field, spec in files.items():
        name, handle, content_type = spec
        body = handle.read()
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{field}"; '
                    f'filename="{name}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                body,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _request(method, url, headers=None, data=None, files=None, timeout=30, **_):
    hdrs = dict(headers or {})
    if files:
        data, content_type = _multipart(files)
        hdrs["Content-Type"] = content_type
    elif isinstance(data, str):
        data = data.encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Response(r.status, r.read(), dict(r.headers))
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.read(), dict(exc.headers or {}))
    except (socket.timeout, TimeoutError) as exc:
        raise Timeout(str(exc)) from exc
    except ssl.SSLError as exc:
        raise SSLError(str(exc)) from exc
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, ssl.SSLError):
            raise SSLError(str(reason)) from exc
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise Timeout(str(reason)) from exc
        raise ConnectionError(str(reason)) from exc
    except OSError as exc:
        raise ConnectionError(str(exc)) from exc


def get(url, **kwargs):
    return _request("GET", url, **kwargs)


def post(url, **kwargs):
    return _request("POST", url, **kwargs)


def patch(url, **kwargs):
    return _request("PATCH", url, **kwargs)
