"""意圖標記 —— 本機 gpt-oss:120b,走 /api/chat(reasoning 模型正確接法)。
只讀去識別後的文字 + 貼標籤,不進任何即時控制流。"""
from __future__ import annotations

import json
import urllib.request

from config import LABEL_MODEL, OLLAMA_URL

INTENTS = [
    "availability_check", "historical_lookup", "price_inquiry",
    "itinerary_detail", "booking_action", "complaint", "unclear", "noise",
]
PARSER_KNOWN = {"availability_check", "historical_lookup"}

_SYSTEM = (
    "你是阿玩旅遊客服訊息分類器。輸入一句客人訊息,只輸出一個 JSON 物件,無多餘文字。\n"
    f"欄位: intent(必為其一 {INTENTS})、is_noise(true/false)、"
    "confidence(0~1 數字)、reason(簡短中文)。\n"
    "純寒暄/系統訊息/無查詢意圖 → is_noise=true 且 intent=noise。"
)


def _chat(text: str, timeout: float = 60.0) -> str:
    body = json.dumps({
        "model": LABEL_MODEL,
        "messages": [{"role": "system", "content": _SYSTEM},
                     {"role": "user", "content": text}],
        "stream": False, "options": {"temperature": 0},
    }).encode()
    req = urllib.request.Request(OLLAMA_URL, data=body, method="POST",
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["message"]["content"]


def _coerce(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"):]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        s, e = raw.find("{"), raw.rfind("}")
        if s >= 0 and e > s:
            return json.loads(raw[s:e + 1])
        raise


def label(text: str) -> dict:
    """回 {intent, is_noise, confidence, parser_missed, model}。失敗退 unclear。"""
    try:
        d = _coerce(_chat(text))
        intent = d.get("intent", "unclear")
        if intent not in INTENTS:
            intent = "unclear"
        is_noise = bool(d.get("is_noise", False)) or intent == "noise"
        if is_noise:
            intent = "noise"
        conf = float(d.get("confidence", 0.0))
    except Exception as e:  # noqa: BLE001
        intent, is_noise, conf = "unclear", False, 0.0
    parser_missed = (not is_noise) and intent not in PARSER_KNOWN and intent != "unclear"
    return {"intent": intent, "is_noise": is_noise, "confidence": conf,
            "parser_missed": parser_missed, "model": LABEL_MODEL}
