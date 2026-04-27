from dataclasses import dataclass
from threading import Lock
import time

from .service import (
    InvalidSymbolError,
    NoDataError,
    SourceUnavailableError,
    StockAnalysisService,
)


@dataclass
class CacheEntry:
    expires_at: float
    payload: dict


class ResponseCache:
    def __init__(self, ttl_seconds: int = 60):
        self.ttl_seconds = ttl_seconds
        self._entries: dict[tuple, CacheEntry] = {}
        self._lock = Lock()

    def get(self, key: tuple) -> dict | None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return None
            if entry.expires_at <= now:
                self._entries.pop(key, None)
                return None
            return entry.payload

    def set(self, key: tuple, payload: dict) -> None:
        with self._lock:
            self._entries[key] = CacheEntry(
                expires_at=time.monotonic() + self.ttl_seconds,
                payload=payload,
            )


def create_app():
    from flask import Flask, jsonify, render_template, request

    app = Flask(__name__)
    service = StockAnalysisService()
    cache = ResponseCache(ttl_seconds=60)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "cacheTtlSeconds": cache.ttl_seconds})

    @app.get("/api/analyze")
    def analyze():
        symbol = request.args.get("symbol", "").strip()
        cost_raw = request.args.get("cost", "").strip()
        target_raw = request.args.get("target", "").strip()
        stop_raw = request.args.get("stop", "").strip()
        cost_basis = None
        target_price = None
        stop_price = None
        if cost_raw:
            try:
                cost_basis = float(cost_raw)
            except ValueError:
                return jsonify({"error": "成本價格式錯誤", "code": "INVALID_COST"}), 400
        if target_raw:
            try:
                target_price = float(target_raw)
            except ValueError:
                return jsonify({"error": "目標價格式錯誤", "code": "INVALID_TARGET"}), 400
        if stop_raw:
            try:
                stop_price = float(stop_raw)
            except ValueError:
                return jsonify({"error": "停損價格式錯誤", "code": "INVALID_STOP"}), 400

        cache_key = (
            symbol.upper(),
            cost_basis,
            target_price,
            stop_price,
        )
        cached = cache.get(cache_key)
        if cached is not None:
            cached_payload = dict(cached)
            cached_payload["meta"] = {"cached": True, "cacheTtlSeconds": cache.ttl_seconds}
            return jsonify(cached_payload)

        try:
            result = service.analyze(symbol, cost_basis=cost_basis, target_price=target_price, stop_price=stop_price)
        except InvalidSymbolError as exc:
            return jsonify({"error": str(exc), "code": "INVALID_SYMBOL"}), 404
        except NoDataError as exc:
            return jsonify({"error": str(exc), "code": "NO_DATA"}), 404
        except SourceUnavailableError as exc:
            return jsonify({"error": str(exc), "code": "SOURCE_UNAVAILABLE"}), 503

        cache.set(cache_key, result)
        result["meta"] = {"cached": False, "cacheTtlSeconds": cache.ttl_seconds}
        return jsonify(result)

    return app
