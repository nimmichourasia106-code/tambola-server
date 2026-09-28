import json
import random
import secrets
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

games = {}

def new_code():
    while True:
        code = f"{random.randint(0, 999999):06d}"
        if code not in games:
            return code

def response(handler, data, status=200):
    raw = json.dumps(data).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)

def read_json(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length == 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))

def state(game):
    return {
        "called": game["called"],
        "selected": game["selected"],
        "fixed": game["fixed"],
        "admin_connected": game["admin_token"] is not None
    }

def choose_next(game):
    position = len(game["called"]) + 1

    if str(position) in game["fixed"]:
        number = game["fixed"][str(position)]
    elif game["selected"] is not None:
        number = game["selected"]
    else:
        available = [n for n in range(1, 91) if n not in game["called"]]
        if not available:
            raise ValueError("All 90 numbers called")
        number = random.choice(available)

    if number in game["called"]:
        raise ValueError("That number has already been called")
    return number

def do_next(game):
    if len(game["called"]) >= 90:
        raise ValueError("All 90 numbers called")
    number = choose_next(game)
    game["called"].append(number)
    game["selected"] = None
    return number

def do_undo(game):
    if game["called"]:
        game["called"].pop()
    game["selected"] = None

def do_reset(game):
    game["called"] = []
    game["selected"] = None
    # Fixed future calls remain until CLEAR ALL FIXED CALLS is pressed.

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print("%s - %s" % (self.address_string(), format % args))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path.startswith("/api/state/"):
            code = path.split("/")[-1]
            game = games.get(code)
            if not game:
                response(self, {"error": "Invalid code"}, 404)
                return
            response(self, state(game))
            return

        response(self, {"ok": True, "service": "Tambola Server"})

    def do_POST(self):
        path = urlparse(self.path).path

        try:
            data = read_json(self)
        except Exception:
            response(self, {"error": "Invalid JSON"}, 400)
            return

        if path == "/api/display/create":
            code = new_code()
            games[code] = {
                "called": [],
                "selected": None,
                "admin_token": None,
                "fixed": {}
            }
            response(self, {
                "code": code,
                "called": [],
                "selected": None,
                "fixed": {},
                "admin_connected": False
            })
            return

        if path == "/api/admin/join":
            code = str(data.get("code", "")).strip()

            if len(code) != 6 or code not in games:
                response(self, {"error": "Invalid code"}, 404)
                return

            game = games[code]

            if game["admin_token"] is not None:
                response(self, {"error": "Display already has an Admin"}, 409)
                return

            token = secrets.token_urlsafe(24)
            game["admin_token"] = token

            response(self, {
                "token": token,
                "state": state(game)
            })
            return

        # ---------- DISPLAY COMMANDS ----------
        if path in (
            "/api/display/next",
            "/api/display/undo",
            "/api/display/reset"
        ):
            code = str(data.get("code", "")).strip()

            if code not in games:
                response(self, {"error": "Invalid code"}, 404)
                return

            game = games[code]

            try:
                if path == "/api/display/next":
                    number = do_next(game)
                    response(self, {
                        "number": number,
                        "state": state(game),
                        "called": game["called"]
                    })
                    return

                if path == "/api/display/undo":
                    do_undo(game)
                    response(self, {
                        "ok": True,
                        "state": state(game),
                        "called": game["called"]
                    })
                    return

                if path == "/api/display/reset":
                    do_reset(game)
                    response(self, {
                        "ok": True,
                        "state": state(game),
                        "called": game["called"]
                    })
                    return

            except ValueError as e:
                response(self, {"error": str(e)}, 400)
                return

        # ---------- ADMIN AUTH ----------
        code = str(data.get("code", "")).strip()
        token = str(data.get("token", "")).strip()

        if code not in games:
            response(self, {"error": "Invalid code"}, 404)
            return

        game = games[code]

        if token != game["admin_token"]:
            response(self, {"error": "Unauthorized"}, 401)
            return

        if path == "/api/admin/select":
            try:
                number = int(data.get("number", 0))
            except Exception:
                number = 0

            if number < 1 or number > 90:
                response(self, {"error": "Number must be 1-90"}, 400)
                return

            if number in game["called"]:
                response(self, {"error": "Number already called"}, 400)
                return

            position = len(game["called"]) + 1

            if str(position) in game["fixed"]:
                response(self, {
                    "error": f"Call #{position} is fixed to {game['fixed'][str(position)]}"
                }, 400)
                return

            game["selected"] = number
            response(self, {"ok": True, "state": state(game)})
            return

        if path == "/api/admin/fix":
            try:
                position = int(data.get("position", 0))
                number = int(data.get("number", 0))
            except Exception:
                position = 0
                number = 0

            next_position = len(game["called"]) + 1

            if position < 1 or position > 90:
                response(self, {"error": "Position must be 1-90"}, 400)
                return

            if number < 1 or number > 90:
                response(self, {"error": "Number must be 1-90"}, 400)
                return

            if position < next_position:
                response(self, {"error": "That call position has already passed"}, 400)
                return

            if number in game["called"]:
                response(self, {"error": "That number has already been called"}, 400)
                return

            for p, n in game["fixed"].items():
                if p != str(position) and n == number:
                    response(self, {
                        "error": "That number is already fixed to another position"
                    }, 400)
                    return

            game["fixed"][str(position)] = number

            if game["selected"] == number:
                game["selected"] = None

            response(self, {"ok": True, "state": state(game)})
            return

        if path == "/api/admin/clear_schedule":
            game["fixed"] = {}
            response(self, {"ok": True, "state": state(game)})
            return

        if path == "/api/admin/next":
            try:
                number = do_next(game)
                response(self, {
                    "number": number,
                    "state": state(game),
                    "called": game["called"]
                })
            except ValueError as e:
                response(self, {"error": str(e)}, 400)
            return

        if path == "/api/admin/undo":
            do_undo(game)
            response(self, {
                "ok": True,
                "state": state(game),
                "called": game["called"]
            })
            return

        if path == "/api/admin/reset":
            do_reset(game)
            response(self, {
                "ok": True,
                "state": state(game)
            })
            return

        response(self, {"error": "Unknown endpoint"}, 404)

print("====================================")
print("          TAMBOLA SERVER")
print("====================================")
print("Server starting...")

port = int(os.environ.get("PORT", 8000))
ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
    
