# OP Assistant LINE Plugin

## Python-first routing (B1, 2026-05-27)

Inbound messages are dispatched through `wannavegtour.LineRouter.dispatch()` before
falling through to the Hermes agent loop. For any intent LineRouter handles
deterministically (availability / historical / aggregate / help / price_edit_refuse),
this completes in <2s without invoking LLM. Hermes agent path is reserved for
truly unknown cases or future LLM-assisted features.

This restores the standalone listener's fast path while keeping Hermes/Funnel
integration for cutover + future extensibility.
