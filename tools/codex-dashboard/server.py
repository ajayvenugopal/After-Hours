import json, os, sqlite3, secrets, re
from bridge import bridge

TOKEN = secrets.token_urlsafe(32)
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve()


def database():
    paths = list(HOME.glob("state_*.sqlite"))
    if not paths:
        raise RuntimeError("No Codex session database found")
    db = max(paths, key=lambda p: int(p.stem.split("_")[-1]))
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def sessions():
    with database() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT id,title,cwd,updated_at,archived,model FROM threads ORDER BY updated_at DESC"
            )
        ]


def readable_output(value, depth=0):
    if depth > 12:
        return "[Nested tool result]"
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return value
        if isinstance(parsed, (dict, list)):
            return readable_output(parsed, depth + 1)
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (readable_output(v, depth + 1) for v in value)))
    if isinstance(value, dict):
        for key in ("output", "stdout", "content", "text", "result"):
            if key in value:
                text = readable_output(value[key], depth + 1)
                if key == "stdout" and value.get("stderr"):
                    text += "\n" + readable_output(value["stderr"], depth + 1)
                return text
        if "error" in value:
            return readable_output(value["error"], depth + 1)
        if "message" in value:
            return str(value["message"])
        return "Tool completed."
    return "" if value is None else str(value)


def history(identifier):
    with database() as c:
        row = c.execute(
            "SELECT rollout_path FROM threads WHERE id=?", (identifier,)
        ).fetchone()
    if not row:
        raise FileNotFoundError("Session not found")
    path = Path(row[0]).resolve()
    if not path.is_relative_to(HOME):
        raise ValueError("Session file outside Codex directory")
    messages = []
    with path.open() as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            p = e.get("payload", {})
            if e.get("type") == "response_item" and p.get("type") in (
                "function_call",
                "custom_tool_call",
                "function_call_output",
                "custom_tool_call_output",
            ):
                kind = p.get("type")
                output = kind.endswith("_output")
                text = (
                    p.get("output")
                    if output
                    else p.get("arguments", p.get("input", ""))
                )
                if output:
                    text = readable_output(text)
                    if (
                        text.startswith(
                            ("Script completed", "Script running with cell ID")
                        )
                        and "\nOutput:\n" in text
                    ):
                        text = text.split("\nOutput:\n", 1)[1].lstrip("\n")
                elif not isinstance(text, str):
                    text = json.dumps(text, indent=2)
                if not output:
                    try:
                        args = json.loads(text)
                        text = args.get(
                            "cmd",
                            args.get(
                                "command",
                                args.get(
                                    "code",
                                    args.get("title", p.get("name", "Tool call")),
                                ),
                            ),
                        )
                        if not isinstance(text, str):
                            text = json.dumps(text, indent=2)
                    except (ValueError, TypeError):
                        pass
                messages.append(
                    {
                        "role": "tool",
                        "name": ("Output" if output else p.get("name", "Tool")),
                        "text": text or "",
                        "time": e.get("timestamp", ""),
                    }
                )
            if (
                e.get("type") == "response_item"
                and p.get("type") == "message"
                and p.get("role") in ("user", "assistant")
            ):
                if p.get("channel") == "analysis":
                    continue
                parts = []
                for item in p.get("content", []):
                    if item.get("text"):
                        parts.append(item["text"])
                    elif item.get("type") in ("input_image", "image"):
                        parts.append("[Image attachment]")
                if parts:
                    text = "\n".join(parts)
                    text = re.sub(
                        r"<image\b[^>]*>([\s\S]*?)</image>",
                        lambda m: "[Image "
                        + (
                            re.search(r"Image #?(\d+)", m.group(0)).group(1)
                            if re.search(r"Image #?(\d+)", m.group(0))
                            else "1"
                        )
                        + "]",
                        text,
                    )
                    is_tool = text.startswith(
                        ("Script completed", "Script running with cell ID")
                    ) or text.lstrip().startswith(
                        ("text(await tools.", "const results = await")
                    )
                    messages.append(
                        {
                            "role": "tool" if is_tool else p["role"],
                            "name": "Tool result" if is_tool else "",
                            "text": text,
                            "time": e.get("timestamp", ""),
                        }
                    )
    return messages


class Handler(BaseHTTPRequestHandler):
    def valid_host(self):
        allowed = {"127.0.0.1:8765", "localhost:8765"}
        if os.environ.get("DASHBOARD_TAILSCALE_IP"):
            allowed.add(os.environ["DASHBOARD_TAILSCALE_IP"] + ":8765")
        allowed.update(
            filter(None, os.environ.get("DASHBOARD_ALLOWED_HOSTS", "").split(","))
        )
        if self.headers.get("Host", "") not in allowed:
            self.send_error(403, "Host not allowed")
            return False
        return True

    def do_GET(self):
        if not self.valid_host():
            return
        route = urlparse(self.path)
        try:
            if route.path == "/api/token":
                payload = json.dumps({"token": TOKEN}).encode()
                mime = "application/json"
            elif route.path == "/api/state":
                try:
                    snapshot = bridge.snapshot()
                except Exception as error:
                    snapshot = {
                        "connected": False,
                        "requests": [],
                        "states": {},
                        "error": str(error),
                    }
                payload = json.dumps(snapshot).encode()
                mime = "application/json"
            elif route.path == "/api/sessions":
                payload = json.dumps(sessions()).encode()
                mime = "application/json"
            elif route.path == "/api/history":
                payload = json.dumps(
                    history(parse_qs(route.query).get("id", [""])[0])
                ).encode()
                mime = "application/json"
            elif route.path == "/":
                payload = Path(__file__).with_name("index.html").read_bytes()
                mime = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
        except FileNotFoundError:
            self.send_error(404, "Session history unavailable")
            return
        except Exception:
            self.send_error(500, "Unable to read Codex data")
            return
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if not self.valid_host():
            return
        if self.path not in ("/api/reply", "/api/answer", "/api/attach"):
            self.send_error(404)
            return
        if not secrets.compare_digest(self.headers.get("X-Dashboard-Token", ""), TOKEN):
            self.send_error(403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError("Message too large or empty")
            body = json.loads(self.rfile.read(length))
            if self.path == "/api/answer":
                result = bridge.answer(str(body.get("key")), body.get("answer"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
                return
            identifier = body.get("id")
            message = body.get("message")
            if self.path == "/api/attach":
                if not isinstance(identifier, str):
                    raise ValueError("Select a session")
                result = {"thread": bridge.attach(identifier)}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({"status": result["thread"].get("status", {})}).encode()
                )
                return
            if not isinstance(message, str) or not message.strip():
                raise ValueError("Enter a message")
            if not isinstance(identifier, str):
                raise ValueError("Select a session")
            with database() as c:
                row = c.execute(
                    "SELECT archived FROM threads WHERE id=?", (identifier,)
                ).fetchone()
            if not row:
                raise ValueError("Session not found")
            if row[0]:
                raise ValueError("Unarchive this session in Codex before replying")
            result = bridge.reply(identifier, message.strip())
            status = 200
        except (ValueError, RuntimeError, OSError) as e:
            result = {"error": str(e)}
            status = 400
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("Codex dashboard: http://127.0.0.1:8765", flush=True)
    local_server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    tailscale_ip = os.environ.get("DASHBOARD_TAILSCALE_IP")
    if tailscale_ip:
        import ipaddress, threading

        if ipaddress.ip_address(tailscale_ip) not in ipaddress.ip_network(
            "100.64.0.0/10"
        ):
            raise ValueError("DASHBOARD_TAILSCALE_IP must be a Tailscale IPv4 address")
        remote_server = ThreadingHTTPServer((tailscale_ip, 8765), Handler)
        threading.Thread(target=remote_server.serve_forever, daemon=True).start()
        print(f"Private Tailscale dashboard: http://{tailscale_ip}:8765", flush=True)
    local_server.serve_forever()
