"""Persistent JSON-RPC connection to the existing Codex daemon."""

import json, threading, queue, socket, os, time
from pathlib import Path
import websocket


class Bridge:
    def __init__(self):
        self.pending = {}
        self.lock = threading.Lock()
        self.connect_lock = threading.Lock()
        self.serial = 0
        self.ws = None
        self.requests = {}
        self.items = {}
        self.states = {}
        self.attached = set()
        self.last_discovery = 0
        self.discovery_lock = threading.Lock()
        self.answer_lock = threading.Lock()

    def connect(self):
        with self.connect_lock:
            if self.ws and self.ws.connected:
                return
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(10)
            home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
            sock.connect(str(home / "app-server-control/app-server-control.sock"))
            self.ws = websocket.create_connection(
                "ws://localhost/", socket=sock, suppress_origin=True, timeout=10
            )
            self.ws.settimeout(None)
            threading.Thread(target=self.read, args=(self.ws,), daemon=True).start()
            try:
                self.call(
                    "initialize",
                    {
                        "clientInfo": {
                            "name": "codex_dashboard",
                            "title": "Codex Dashboard",
                            "version": "0.2.0",
                        }
                    },
                )
            except Exception:
                self.ws.close()
                raise
            self.attached.clear()
            self.write({"method": "initialized"})

    def write(self, data):
        with self.lock:
            self.ws.send(json.dumps(data))

    def read(self, ws):
        try:
            while ws.connected:
                raw = ws.recv()
                if not raw:
                    break
                m = json.loads(raw)
                if "id" in m and "method" not in m:
                    with self.lock:
                        q = self.pending.get(m["id"])
                    if q:
                        q.put(m)
                elif "id" in m and "method" in m:
                    with self.lock:
                        self.requests[str(m["id"])] = m
                else:
                    params = m.get("params", {})
                    method = m.get("method")
                    with self.lock:
                        if method == "serverRequest/resolved":
                            self.requests.pop(str(params.get("requestId")), None)
                        if method in ("item/started", "item/completed"):
                            item = params.get("item", {})
                            self.items[item.get("id")] = item
                        if method == "thread/status/changed":
                            self.states[params["threadId"]] = params.get("status", {})
        except (OSError, ValueError, websocket.WebSocketException):
            pass
        finally:
            ws.close()
            with self.lock:
                self.requests.clear()
                for q in self.pending.values():
                    q.put(
                        {
                            "error": {
                                "message": "Codex daemon disconnected. Check its status before retrying a message."
                            }
                        }
                    )

    def call(self, method, params):
        with self.lock:
            self.serial += 1
            identifier = self.serial
            q = queue.Queue()
            self.pending[identifier] = q
        try:
            self.write({"id": identifier, "method": method, "params": params})
            try:
                response = q.get(timeout=30)
            except queue.Empty:
                raise RuntimeError(
                    "Codex did not confirm the request. Refresh the session before retrying."
                )
            if "error" in response:
                raise RuntimeError(
                    response["error"].get("message", "Codex request failed")
                )
            return response.get("result", {})
        finally:
            with self.lock:
                self.pending.pop(identifier, None)

    def reply(self, identifier, message):
        self.connect()
        thread = self.attach(identifier)
        active = next(
            (
                t
                for t in reversed(thread.get("turns", []))
                if t.get("status") == "inProgress"
            ),
            None,
        )
        inputs = [{"type": "text", "text": message}]
        if active:
            result = self.call(
                "turn/steer",
                {
                    "threadId": identifier,
                    "expectedTurnId": active["id"],
                    "input": inputs,
                },
            )
        else:
            result = self.call("turn/start", {"threadId": identifier, "input": inputs})
        return {"accepted": True, "result": result}

    def attach(self, identifier):
        self.connect()
        thread = self.call("thread/resume", {"threadId": identifier})["thread"]
        with self.lock:
            self.attached.add(identifier)
            self.states[identifier] = thread.get("status", {})
        return thread

    def discover(self):
        if time.monotonic() - self.last_discovery < 10:
            return
        if not self.discovery_lock.acquire(blocking=False):
            return
        try:
            cursor = None
            while True:
                page = self.call("thread/loaded/list", {"cursor": cursor})
                for identifier in page.get("data", []):
                    if identifier not in self.attached:
                        try:
                            self.attach(identifier)
                        except RuntimeError as error:
                            if "no rollout found" not in str(error):
                                raise
                            # Ephemeral loaded threads have no resumable rollout.
                            continue
                cursor = page.get("nextCursor")
                if not cursor:
                    break
            self.last_discovery = time.monotonic()
        finally:
            self.discovery_lock.release()

    def snapshot(self):
        self.connect()
        self.discover()
        with self.lock:
            requests = []
            for key, m in self.requests.items():
                request = dict(m)
                request["key"] = key
                request["item"] = self.items.get(m.get("params", {}).get("itemId"))
                requests.append(request)
            return {
                "connected": bool(self.ws and self.ws.connected),
                "requests": requests,
                "states": dict(self.states),
            }

    def answer(self, key, answer):
        with self.answer_lock:
            return self._answer(key, answer)

    def _answer(self, key, answer):
        with self.lock:
            request = self.requests.get(key)
        if not request:
            raise ValueError("This prompt has already been resolved or disconnected")
        method = request["method"]
        params = request.get("params", {})
        if method in (
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
        ):
            if answer not in ("accept", "decline", "cancel"):
                raise ValueError("Invalid approval decision")
            available = params.get("availableDecisions")
            if available and answer not in available:
                raise ValueError("This decision is not available")
            result = {"decision": answer}
        elif method == "item/permissions/requestApproval":
            if answer not in ("accept", "decline"):
                raise ValueError("Invalid permissions decision")
            result = {
                "permissions": (
                    params.get("permissions", {}) if answer == "accept" else {}
                ),
                "scope": "turn",
            }
        elif method == "item/tool/requestUserInput":
            if not isinstance(answer, dict):
                raise ValueError("Answers required")
            result = {"answers": {}}
            for question in params.get("questions", []):
                value = answer.get(question["id"])
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("Answer every question")
                result["answers"][question["id"]] = {"answers": [value]}
        else:
            raise ValueError("Respond to this prompt in the original Codex client")
        self.write({"id": request["id"], "result": result})
        with self.lock:
            self.requests.pop(key, None)
        return {"accepted": True}


bridge = Bridge()
