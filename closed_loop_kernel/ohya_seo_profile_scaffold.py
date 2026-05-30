from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


PROFILE_SPECS = [
    {
        "profile_id": "growth-coordinator",
        "display_name": "成長協調員",
        "role_summary": "接收 SEO 任務、建立 Task Record、派工給正確 profile。",
        "allowed_outputs": ["task_record", "route_status_summary"],
        "forbidden_actions": [
            "不得自行產出 SEO 結論。",
            "不得發布內容或回覆社群。",
            "不得讀取敏感設定或 production database。",
        ],
    },
    {
        "profile_id": "social-listener",
        "display_name": "社群聆聽工具",
        "role_summary": "只做公開社群、論壇、新聞與品牌提及海巡。",
        "allowed_outputs": ["social_listening_digest", "social_patrol_report", "brand_presence_signal"],
        "forbidden_actions": [
            "不得回覆、私訊或發布。",
            "不得把 raw social data 直接推進長期記憶。",
            "不得讀取未授權來源。",
        ],
    },
    {
        "profile_id": "social-reply-advisor",
        "display_name": "社群回文建議工具",
        "role_summary": "根據海巡報告與品牌規則產生可審核的回文建議。",
        "allowed_outputs": ["social_reply_recommendation"],
        "forbidden_actions": [
            "不得發布或傳送回覆。",
            "不得把建議包裝成已批准內容。",
            "不得跳過 reviewer 或 Gary approval。",
        ],
    },
]


@dataclass(frozen=True)
class ModelBaseline:
    default: str
    provider: str


def load_model_baseline(template_config_path: str | Path) -> ModelBaseline:
    path = Path(template_config_path)
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r"^model:\s*\n(?P<body>(?:[ \t]+[A-Za-z0-9_-]+:\s*[^\n]*\n?)+)",
        text,
        flags=re.MULTILINE,
    )
    if not match:
        raise ValueError(f"{path} is missing a top-level model block")

    values: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if ":" not in line:
            continue
        key, value = line.strip().split(":", 1)
        values[key] = value.strip().strip("'\"")

    default = values.get("default")
    provider = values.get("provider")
    if not default or not provider:
        raise ValueError(f"{path} model block must include default and provider")
    return ModelBaseline(default=default, provider=provider)


def load_registry_outputs(registry_path: str | Path) -> dict[str, set[str]]:
    data = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    outputs: dict[str, set[str]] = {}
    for profile in data.get("profiles", []):
        profile_id = profile["profile_id"]
        outputs[profile_id] = set(profile["data_flow_policy"]["writable_outputs"])
    return outputs


def validate_specs_against_registry(registry_path: str | Path) -> None:
    registry_outputs = load_registry_outputs(registry_path)
    for spec in PROFILE_SPECS:
        profile_id = spec["profile_id"]
        if profile_id not in registry_outputs:
            raise ValueError(f"{profile_id} is missing from registry")
        missing = sorted(set(spec["allowed_outputs"]) - registry_outputs[profile_id])
        if missing:
            raise ValueError(f"{profile_id} outputs not allowed by registry: {missing}")


def render_config(profile_id: str, baseline: ModelBaseline, profile_dir: Path) -> str:
    workspace_dir = profile_dir / "workspace"
    return f"""model:
  default: {baseline.default}
  provider: {baseline.provider}
providers: {{}}
fallback_providers: []
toolsets:
- hermes-cli
agent:
  max_turns: 80
  gateway_timeout: 1800
  api_max_retries: 3
  tool_use_enforcement: auto
  disabled_toolsets: []
terminal:
  backend: local
  modal_mode: auto
  cwd: {workspace_dir}
  timeout: 300
  env_passthrough: []
  shell_init_files: []
  auto_source_bashrc: true
metadata:
  profile_id: {profile_id}
  scaffold: ohya-ai-native-seo-clean-profile-v0
  contract: docs/ai-native-seo-module-v0.md
"""


def render_soul(spec: dict) -> str:
    outputs = ", ".join(f"`{output}`" for output in spec["allowed_outputs"])
    forbidden = "\n".join(f"- {item}" for item in spec["forbidden_actions"])
    return f"""# {spec["display_name"]} ({spec["profile_id"]})

你是好事發生數位 AI Native SEO 模組的乾淨 Hermes profile。

## 角色

{spec["role_summary"]}

## 可以產出的正式紀錄

{outputs}

白話說：你交出的任何結果都必須包成 Agent Output Envelope，包含來源、產物、機器紀錄與內容雜湊，不能只留自然語言結論。

## 禁止事項

{forbidden}

## 工作規則

1. 先確認任務是否屬於自己的 role。
2. 只使用公開或已授權來源。
3. 每個判斷都要留下 source_refs。
4. 不把原始資料直接當公司記憶。
5. 需要發布、回覆或高風險動作時，交給 reviewer 與 Gary approval。

## 底層原則

Code is Law。流程控制、權限、重試、發布、審核與寫入資料庫都由程式規則決定，不由 prompt 自行決定。
"""


def render_report(output_dir: Path, baseline: ModelBaseline) -> str:
    lines = [
        "# OHYA AI Native SEO Clean Profile Scaffold Report",
        "",
        "白話說：這份 scaffold 只建立乾淨 profile 檔案，沒有改 live HermesRuntime。",
        "",
        "## Model Baseline",
        "",
        f"- `model.default`: `{baseline.default}` — 白話：沿用 approved Hermes template 的主要模型。",
        f"- `model.provider`: `{baseline.provider}` — 白話：沿用 approved Hermes template 的模型供應方式。",
        "",
        "## Profiles",
        "",
    ]
    for spec in PROFILE_SPECS:
        lines.extend(
            [
                f"### `{spec['profile_id']}`",
                "",
                f"- 這是什麼：{spec['display_name']}",
                f"- 白話功能：{spec['role_summary']}",
                f"- 產出位置：`{output_dir / 'profiles' / spec['profile_id']}`",
                f"- 允許產物：{', '.join(spec['allowed_outputs'])}",
                "",
            ]
        )
    lines.extend(
        [
            "## Safety",
            "",
            "- 未啟動任何 agent。",
            "- 未呼叫外部 API。",
            "- 未寫入 live HermesRuntime。",
            "- 未複製舊狀態資料。",
        ]
    )
    return "\n".join(lines) + "\n"


def generate_scaffold(
    template_config_path: str | Path,
    registry_path: str | Path,
    output_dir: str | Path,
) -> dict:
    output_path = Path(output_dir)
    baseline = load_model_baseline(template_config_path)
    validate_specs_against_registry(registry_path)

    profiles_root = output_path / "profiles"
    profiles_root.mkdir(parents=True, exist_ok=True)
    generated_profiles = []
    for spec in PROFILE_SPECS:
        profile_dir = profiles_root / spec["profile_id"]
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "workspace").mkdir(exist_ok=True)
        (profile_dir / "config.yaml").write_text(
            render_config(spec["profile_id"], baseline, profile_dir),
            encoding="utf-8",
        )
        (profile_dir / "SOUL.md").write_text(render_soul(spec), encoding="utf-8")
        generated_profiles.append(spec["profile_id"])

    report = render_report(output_path, baseline)
    (output_path / "REPORT.md").write_text(report, encoding="utf-8")
    manifest = {
        "scaffold": "ohya-ai-native-seo-clean-profile-v0",
        "model": {"default": baseline.default, "provider": baseline.provider},
        "profiles": generated_profiles,
        "contract": "docs/ai-native-seo-module-v0.md",
        "writes_live_runtime": False,
    }
    (output_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate isolated OHYA AI Native SEO clean profile scaffold.")
    parser.add_argument("--template-config", required=True)
    parser.add_argument("--registry", default="data/agent-profile-registry-v0.json")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)

    manifest = generate_scaffold(
        template_config_path=args.template_config,
        registry_path=args.registry,
        output_dir=args.output_dir,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
