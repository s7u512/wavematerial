# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The local web app shown in the WaveMaterial window.

The server binds to 127.0.0.1 on a random port. Every request must carry the per-launch
token: the window opens `/?token=...` once, which sets an HttpOnly, SameSite=Strict cookie
and redirects. Requests for any other Host are refused (DNS rebinding), and the SameSite
cookie keeps other web pages from making requests on the user's behalf.
"""

from __future__ import annotations

import hmac
import time

from flask import Flask, abort, g, redirect, request

from wavematerial import __version__
from wavematerial.web import format
from wavematerial.web.context import AppContext

COOKIE = "wavematerial_token"


def create_app(ctx: AppContext) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 2 << 20  # forms only; files are read from disk

    @app.before_request
    def guard():
        allowed = {f"127.0.0.1:{ctx.port}", f"localhost:{ctx.port}"}
        if ctx.port and request.host not in allowed:
            abort(400)
        offered = request.args.get("token")
        if offered is not None:
            if not hmac.compare_digest(offered, ctx.token):
                abort(403)
            resp = redirect(request.path)
            resp.set_cookie(COOKIE, ctx.token, httponly=True, samesite="Strict")
            return resp
        if not hmac.compare_digest(request.cookies.get(COOKIE, ""), ctx.token):
            abort(403)
        g.ctx = ctx
        ctx.last_seen = time.monotonic()

    @app.after_request
    def headers(resp):
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; frame-ancestors 'none'"
        )
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(403)
    def forbidden(_):
        return (
            "<p style='font-family:sans-serif'>Open WaveMaterial from its own window.</p>",
            403,
        )

    @app.context_processor
    def globals_():
        return {
            "ctx": ctx,
            "version": __version__,
            "title_of": lambda job: format.title(job.name, job.source),
        }

    from wavematerial.web import views

    views.register(app)
    return app
