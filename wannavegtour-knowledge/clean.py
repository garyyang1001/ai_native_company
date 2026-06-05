"""清洗判準(deterministic · code is rule)—— 決定一則訊息是不是 noise。"""
from __future__ import annotations

import re

# LINE 系統佔位訊息(沒有文字內容,必清)
_SYSTEM_PLACEHOLDERS = {
    "照片已傳送", "貼圖已傳送", "檔案已傳送", "影片已傳送", "語音訊息已傳送",
    "圖片已傳送", "位置資訊已傳送", "已收回訊息", "通話已結束", "未接來電",
    "貼圖", "照片", "已傳送一張圖片",
}

# 純寒暄 / 無資訊回覆(訓練/知識價值低)
_PLEASANTRIES = {
    "好", "好的", "好喔", "收到", "謝謝", "感謝", "ok", "OK", "嗯", "嗯嗯",
    "哈哈", "haha", "👍", "🙏", "是", "對", "對呀", "對啊", "了解", "知道了",
    "好喔收到", "嗯嗯對呀", "謝謝您", "麻煩了",
}

_EMOJI_ONLY = re.compile(
    r"^[\s\W☀-➿\U0001F000-\U0001FAFF　-〿]+$"
)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def is_noise(text: str) -> bool:
    t = normalize(text)
    if not t:
        return True
    if t in _SYSTEM_PLACEHOLDERS:
        return True
    if any(p in t for p in ("已傳送", "已收回訊息")) and len(t) <= 12:
        return True
    if t in _PLEASANTRIES:
        return True
    if _EMOJI_ONLY.match(t):
        return True
    if len(t) <= 1:
        return True
    return False
