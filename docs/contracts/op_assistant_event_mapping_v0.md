# OP Assistant Event Mapping v0

This is a mapping document, not a new company contract.

Canonical failure semantics come from:

```text
docs/company-data-contract-v0.md §9
```

OP assistant events must map into the company kernel contract instead of defining OP-only canonical enums.

## Scope

This document covers first-iteration OP assistant logging for:

- outbound decision logs
- OP-specific failure evidence
- OP domain failure codes
- trigger reasons

It does not define a new source of truth.

## Canonical Failure Type Mapping

`failure_type` must use the company contract enum from `docs/company-data-contract-v0.md §9`.

OP-specific detail goes into:

```text
context.domain_failure_code
context.trigger_reason
```

| OP scenario | Contract `failure_type` | `context.domain_failure_code` |
|---|---|---|
| User message appears actionable, but parser/router misses it. | `outcome_failure` | `missed_actionable_intent` |
| Bot replies, then user strongly indicates the reply was wrong. | `human_rejection` | `reply_mismatch` |
| Bot replies when it should not have replied. | `quality_regression` | `false_positive_reply` |
| Router chooses `SILENT` for a message that appears actionable. | `outcome_failure` | `unexpected_silent` |
| Replay or verifier proves current behavior regressed. | `verification_failure` | matching domain code |
| Bot violates a documented company/kernel contract. | `contract_violation` | matching domain code |
| Runtime hard error prevents normal handling. | `hard_failure` | matching domain code |

## `domain_failure_code` enum (STRICT — 2026-05-28 Gary 鎖定)

**Fixed 4 values. No `other` catchall. New values require explicit doc review (v0.2 → v0.3 governance flow).**

```text
missed_actionable_intent
reply_mismatch
false_positive_reply
unexpected_silent
```

These are OP domain observations. They are not canonical company `failure_type` values.

Adapter writers MUST reject `domain_failure_code` values outside this set. If a new failure mode is observed in production, the writer should fall back to `failure_type` enum from contract §9 with no `domain_failure_code`, and the case escalates to Gary via `manual_review` trigger for the next governance round.

## `trigger_reason` enum (2026-05-28 Gary 鎖定 — 移除自動糾正偵測)

```text
parser_returned_unclear
fallback_reply_sent
gary_marked_bad
manual_review
```

`trigger_reason` explains why the detector wrote or suggested a failure.

`negative_followup_pattern` was **removed** per Gary 2026-05-28: 糾正信號改由定時 events audit + manual_review 處理,不寫自動 detector。

`trigger_reason` does not replace contract fields such as `detected_by` or `detection_timing`.

## Outbound Decision Event

Decision logs are written as kernel events with:

```text
event_type = "outbound_decision"
```

Payload example:

```json
{
  "contract_version": "v0",
  "profile_id": "op-assistant-line",
  "task_id": "task_20260528_abc123",
  "run_id": "run_20260528_def456",
  "inbound_event_id": "evt_20260528_line_789",
  "source_refs": ["evt_20260528_line_789"],
  "artifact_refs": [],
  "content_hash": "sha256:...",
  "sensitivity_level": "confidential",
  "retention_policy": "365d",
  "router_action": "REPLY",
  "reply_kind": "availability_reply",
  "parser_result": {
    "intent": "availability_check",
    "matched_rule": "availability_keyword"
  },
  "context": {
    "line_user_hash": "user:...",
    "conversation_hash": "conversation:..."
  }
}
```

## Failure Context Example

Failure rows are written to the kernel `failures` table.

Payload/context should include OP-specific fields without changing the canonical `failure_type`.

```json
{
  "failure_type": "outcome_failure",
  "profile_id": "op-assistant-line",
  "task_id": "task_20260528_abc123",
  "run_id": "run_20260528_def456",
  "detected_by": "agent",
  "severity": "medium",
  "context": {
    "domain_failure_code": "missed_actionable_intent",
    "trigger_reason": "parser_returned_unclear",
    "inbound_event_id": "evt_20260528_line_789",
    "outbound_decision_event_id": "evt_20260528_decision_123",
    "redacted_preview": "明天 18:00 [phone:...]",
    "message_hash": "..."
  }
}
```

## Non-goals

- This document does not add new company-level failure types.
- This document does not define a new kernel contract.
- This document does not authorize raw LINE text in proposer input.
- This document does not define candidate materialization.
