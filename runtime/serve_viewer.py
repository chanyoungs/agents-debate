#!/usr/bin/env python3
"""Serve the local debate viewer and JSON API."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from debate_state import load_debate, paired_paths, save_debate, set_paused, set_pending_note, validate_state


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VIEWER_ROOT = PROJECT_ROOT / "viewer"


class DebateViewerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, debate_path: Path | None = None, **kwargs):
        self.default_debate_path = debate_path
        super().__init__(*args, directory=str(VIEWER_ROOT), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/config":
            self.serve_config_api()
            return
        if parsed.path == "/api/debate":
            self.serve_debate_api(parsed)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/control":
            self.serve_control_api(parsed)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "unknown endpoint")

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def serve_config_api(self) -> None:
        payload = json.dumps(
            {
                "default_path": str(self.default_debate_path) if self.default_debate_path is not None else "",
            },
            ensure_ascii=True,
        ).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def serve_debate_api(self, parsed: urllib.parse.ParseResult) -> None:
        params = urllib.parse.parse_qs(parsed.query)
        path_value = params.get("path", [None])[0]
        if path_value is None and self.default_debate_path is not None:
            path_value = str(self.default_debate_path)
        if not path_value:
            self.send_error(HTTPStatus.BAD_REQUEST, "missing query parameter: path")
            return
        try:
            debate_path = Path(path_value).expanduser().resolve()
            print(f"[agents-debate] api/debate path={debate_path}", file=sys.stderr, flush=True)
            state = load_debate(debate_path)
            json_path, markdown_path = paired_paths(debate_path)
            errors = validate_state(state)
            if errors:
                print(f"[agents-debate] api/debate validation errors={errors}", file=sys.stderr, flush=True)
                self.write_json(HTTPStatus.BAD_REQUEST, {"errors": errors})
                return
            save_debate(state, json_path, markdown_path)
            print(
                f"[agents-debate] api/debate ok topic={state.get('topic')} status={state.get('state', {}).get('status')}",
                file=sys.stderr,
                flush=True,
            )
            self.write_json(HTTPStatus.OK, state)
        except Exception as exc:  # noqa: BLE001
            print(f"[agents-debate] api/debate exception={exc}", file=sys.stderr, flush=True)
            self.write_json(HTTPStatus.BAD_REQUEST, {"errors": [str(exc)]})

    def serve_control_api(self, parsed: urllib.parse.ParseResult) -> None:
        params = urllib.parse.parse_qs(parsed.query)
        path_value = params.get("path", [None])[0]
        if path_value is None and self.default_debate_path is not None:
            path_value = str(self.default_debate_path)
        if not path_value:
            self.write_json(HTTPStatus.BAD_REQUEST, {"errors": ["missing query parameter: path"]})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(raw_body.decode("utf-8"))
            action = str(payload.get("action", "")).strip()
            debate_path = Path(path_value).expanduser().resolve()
            state = load_debate(debate_path)
            json_path, markdown_path = paired_paths(debate_path)

            if action == "pause":
                state = set_paused(state, True)
            elif action == "resume":
                state = set_paused(state, False)
            elif action == "note":
                note = str(payload.get("note", "")).strip()
                if not note:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"errors": ["note must not be empty"]})
                    return
                state = set_pending_note(state, note)
                if payload.get("pause_after_note"):
                    state = set_paused(state, True)
            else:
                self.write_json(HTTPStatus.BAD_REQUEST, {"errors": [f"unsupported action: {action}"]})
                return

            errors = validate_state(state)
            if errors:
                self.write_json(HTTPStatus.BAD_REQUEST, {"errors": errors})
                return
            save_debate(state, json_path, markdown_path)
            self.write_json(HTTPStatus.OK, state)
        except Exception as exc:  # noqa: BLE001
            print(f"[agents-debate] api/control exception={exc}", file=sys.stderr, flush=True)
            self.write_json(HTTPStatus.BAD_REQUEST, {"errors": [str(exc)]})

    def write_json(self, status: HTTPStatus, payload_obj: dict) -> None:
        payload = json.dumps(payload_obj, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--path", help="Optional default debate path for the viewer")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    default_path = Path(args.path).resolve() if args.path else None
    server = ThreadingHTTPServer(
        (args.host, args.port),
        lambda *handler_args, **handler_kwargs: DebateViewerHandler(
            *handler_args,
            debate_path=default_path,
            **handler_kwargs,
        ),
    )
    print(f"viewer: http://{args.host}:{args.port}/")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
