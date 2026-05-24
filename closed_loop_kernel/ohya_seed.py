"""
OHYA team + agents seed。

把 `HermesRuntime/clients/ohya/profiles/` 底下的 11 個 agent 註冊到 ohya_kernel 的
agents 表，並建立 `ohya` team（好事發生數位 / OHYA — ohya.co 線上教育平台）。

可重跑：已存在就 skip、不會重複塞。

執行：
  KERNEL_DATABASE_URL=postgresql:///ohya_kernel python3 -m closed_loop_kernel.ohya_seed
"""
from __future__ import annotations

import json
import os
import uuid

from .store import KernelStore, json_param


OHYA_TEAM_NAME = "ohya"
OHYA_TEAM_DESCRIPTION = "好事發生數位 / OHYA — ohya.co 線上教育平台"

# 來源：`HermesRuntime/clients/ohya/profiles/` 底下實際存在的 11 個 agent
OHYA_AGENTS = [
    "coordinator",
    "article-editor",
    "cms-draft-executor",
    "higgsfield-video-producer",
    "link-finder",
    "media-asset-generator",
    "outline-planner",
    "seo-graph",
    "topic-researcher",
    "video-producer",
    "writer",
]


def seed_team(store: KernelStore, name: str, description: str | None = None) -> str:
    existing = store.fetch_one("SELECT id FROM teams WHERE name = ?", [name])
    if existing:
        return existing["id"]
    team_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO teams (id, name, description) VALUES (?, ?, ?)",
        [team_id, name, description],
    )
    return team_id


def seed_agent(store: KernelStore, name: str, team_id: str, profile: dict | None = None) -> str:
    existing = store.fetch_one("SELECT id FROM agents WHERE name = ?", [name])
    if existing:
        return existing["id"]
    agent_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO agents (id, name, team_id, profile) VALUES (?, ?, ?, ?)",
        [agent_id, name, team_id, json_param(profile or {})],
    )
    return agent_id


def seed_ohya(store: KernelStore) -> dict:
    team_id = seed_team(store, OHYA_TEAM_NAME, OHYA_TEAM_DESCRIPTION)
    agent_ids: dict[str, str] = {}
    profile_meta = {"source": "HermesRuntime/clients/ohya/profiles"}
    for name in OHYA_AGENTS:
        agent_ids[name] = seed_agent(store, name, team_id, profile_meta)
    return {"team_id": team_id, "agents": agent_ids}


def _database_url() -> str:
    url = os.environ.get("KERNEL_DATABASE_URL")
    if not url:
        raise RuntimeError("KERNEL_DATABASE_URL is required")
    return url


if __name__ == "__main__":
    store = KernelStore.from_url(_database_url())
    try:
        result = seed_ohya(store)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        store.close()
