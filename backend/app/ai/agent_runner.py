"""Run a KPI/incident Agent through the user's model fallback chain.

Mirrors llm/runner.py's chat_with_fallback: same chain resolution, same limit
gate up front, same per-attempt metering and fallback-on-error — but drives an
agents-SDK Agent (tools, structured output) instead of one chat call, for every
OpenAI-compatible provider in the registry (openai, xai, google, ollama).

Anthropic is the one exception. The Agents SDK needs an adapter package to talk
to a non-OpenAI-compatible provider, and both options available for it proved
unusable in this environment:
  - `litellm` (the SDK's own extension) needs to compile a tokenizer from Rust
    source — no prebuilt wheel exists yet for Python 3.14, and this machine has
    no Rust toolchain installed.
  - `any-llm-sdk` (the lighter alternative) installs, but drags in
    starlette>=1.3 as a transitive dependency, which breaks this app's pinned
    fastapi==0.115.6/starlette==0.41.3 combo outright (confirmed by installing
    it and watching `include_router` break).
So when the model being tried is Anthropic, this falls back to the original
single-shot prompt path (prompts.py + llm/providers.chat) for THAT attempt
only — same governance, same metering, same severity floor, just no tool use
for that one provider. Every other provider in the chain still runs fully
agentic. If a Rust toolchain or a starlette-2.x upgrade ever becomes available,
swap this one branch for a real LitellmModel — nothing else needs to change.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from agents import AsyncOpenAI, OpenAIChatCompletionsModel, Runner
from sqlalchemy.orm import Session

from ..db.models import User
from ..llm import settings as llm_settings
from ..llm import usage
from ..llm.access import effective_allowed_models, effective_priority
from ..llm.providers import DEFAULT_OLLAMA_URL, ChatResult, LLMError, base_url as provider_base_url, chat as direct_chat
from ..llm.registry import ModelSpec, get_model
from . import knowledge, kpi_agents, models as ai_models, prompts

log = logging.getLogger("backend.ai.agent_runner")


@dataclass
class AgentOutcome:
    data: dict                       # normalized fields — same keys regardless of path
    model_id: str
    attempts: list[dict] = field(default_factory=list)
    agentic: bool = True             # False only for the Anthropic direct-call fallback


def _chain_for(user: User) -> list[str]:
    chain = effective_priority(user)
    if chain:
        return chain
    allowed = effective_allowed_models(user)
    return allowed[:1]


def _sdk_model(spec: ModelSpec, api_key: str | None, ollama_url: str, timeout: float):
    client = AsyncOpenAI(
        base_url=provider_base_url(spec, ollama_url),
        api_key=api_key or "ollama",  # Ollama ignores the key but the SDK needs a value
        timeout=timeout,
        max_retries=1,
    )
    return OpenAIChatCompletionsModel(model=spec.model, openai_client=client)


def _run_agent_sync(agent, input_text: str, timeout: float, max_turns: int):
    """Runner.run is async; each call here runs on its own worker thread with no
    existing event loop (background jobs.py thread), so asyncio.run is safe."""
    async def _go():
        return await asyncio.wait_for(Runner.run(agent, input_text, max_turns=max_turns), timeout=timeout)
    return asyncio.run(_go())


def _usage_result(run_result) -> ChatResult:
    u = run_result.context_wrapper.usage
    return ChatResult(
        text="", prompt_tokens=u.input_tokens, completion_tokens=u.output_tokens,
        total_tokens=u.total_tokens, latency_ms=0,
    )


def _run_kpi_attempt(spec, api_key, ollama_url, *, task, result, trend_text, cluster, version, timeout):
    model = _sdk_model(spec, api_key, ollama_url, timeout)
    agent = kpi_agents.build_kpi_agent(task, model, result, trend_text)
    # Seed baseline grounding (top knowledge match + dependency impact) directly
    # in the input, on top of giving the agent tools for deeper investigation.
    # tool_choice="required" (kpi_agents.py) asks compliant providers to call a
    # tool first, but weaker/local models via an OpenAI-compatible endpoint (e.g.
    # Ollama) don't reliably honor that — confirmed by tracing a real run where
    # qwen2.5:7b answered on turn 1 without touching any tool. Without this seed,
    # those models would produce an ungrounded answer; capable models still use
    # the tools to go beyond this baseline (a different query, more evidence rows).
    baseline = knowledge.format_for_prompt(knowledge.search(task, result.get("detail", ""), limit=2))
    input_text = (
        f"CLUSTER: {cluster} — Cloudera version {version or 'UNSPECIFIED (assume a recent CDP release)'}\n\n"
        f"CHECK IN FOCUS: {task}\n"
        f"Status: {result.get('status')}\n"
        f"Detail: {result.get('detail')}\n"
        f"Threshold: {result.get('threshold')}\n\n"
        f"BASELINE KNOWLEDGE (a starting point — call search_knowledge for more):\n{baseline}\n\n"
        f"DEPENDENCY IMPACT: {prompts.dependency_block(task)}\n\n"
        "Investigate further with your tools if you need to, then give your final analysis."
    )
    run_result = _run_agent_sync(agent, input_text, timeout, max_turns=6)
    out: ai_models.KpiAgentOutput = run_result.final_output
    data = out.model_dump()
    return data, _usage_result(run_result)


def _run_incident_attempt(spec, api_key, ollama_url, *, breached, trend_text, cluster, version, timeout):
    model = _sdk_model(spec, api_key, ollama_url, timeout)
    agent = kpi_agents.build_incident_agent(model, breached, trend_text)
    tasks = [r["task"] for r in breached]
    baseline_blocks = []
    for r in breached:
        snips = knowledge.format_for_prompt(knowledge.search(r["task"], r.get("detail", ""), limit=1))
        baseline_blocks.append(f"### {r['task']}: {r.get('detail')}\n{snips}")
    input_text = (
        f"CLUSTER: {cluster} — Cloudera version {version or 'UNSPECIFIED (assume a recent CDP release)'}\n\n"
        f"{len(breached)} checks are breaching: {', '.join(tasks)}\n\n"
        f"BASELINE KNOWLEDGE per breach (a starting point — call get_check_detail / search_knowledge for more):\n"
        f"{chr(10).join(baseline_blocks)}\n\n"
        "Look closer at any check with your tools if you need to, connect related problems, then give your final incident report."
    )
    run_result = _run_agent_sync(agent, input_text, timeout, max_turns=10)
    out: ai_models.IncidentAgentOutput = run_result.final_output
    data = out.model_dump()
    return data, _usage_result(run_result)


def _run_kpi_anthropic_fallback(spec, api_key, *, task, result, trend_text, cluster, version, timeout):
    system, prompt, snippets = prompts.build_kpi_prompt(cluster=cluster, version=version, result=result, trend_text=trend_text)
    chat_result = direct_chat(spec, [{"role": "user", "content": prompt}], api_key=api_key, system=system, max_tokens=900, timeout=timeout)
    parsed = ai_models.extract_json(chat_result.text) or {}
    data = {
        "summary": str(parsed.get("summary", "")).strip(),
        "severity": str(parsed.get("severity", "MEDIUM")).upper(),
        "remediation": ai_models.coerce_str_list(parsed.get("remediation")),
        "impact": str(parsed.get("impact", "")).strip(),
        "related_tasks": [str(t) for t in (parsed.get("related_tasks") or [])],
        "sources": [str(s) for s in (parsed.get("sources") or [s.source for s in snippets])],
        "_raw_text": chat_result.text,
    }
    return data, chat_result


def _run_incident_anthropic_fallback(spec, api_key, *, breached, trend_text, cluster, version, timeout):
    system, prompt, snippets = prompts.build_incident_prompt(cluster=cluster, version=version, breached=breached, trend_text=trend_text)
    chat_result = direct_chat(spec, [{"role": "user", "content": prompt}], api_key=api_key, system=system, max_tokens=1600, timeout=timeout)
    parsed = ai_models.extract_json(chat_result.text) or {}
    data = {
        "overall_summary": str(parsed.get("overall_summary", "")).strip(),
        "findings": parsed.get("findings") or [],
        "priority_order": [str(t) for t in (parsed.get("priority_order") or [])],
        "_raw_text": chat_result.text,
    }
    return data, chat_result


def _run_with_fallback(db, user, *, kind, run_agentic, run_anthropic, timeout) -> AgentOutcome:
    chain = _chain_for(user)
    if not chain:
        raise LLMError("No model is available — set your model priority in Settings.")
    usage.check_limit(db, user)

    ollama_url = llm_settings.get_ollama_url(db, user.id) or DEFAULT_OLLAMA_URL
    attempts: list[dict] = []

    for model_id in chain:
        spec = get_model(model_id)
        if spec is None:
            attempts.append({"model_id": model_id, "ok": False, "error": "unknown model"})
            continue

        api_key = llm_settings.get_api_key(db, user.id, spec.provider) if spec.needs_key else None
        if spec.needs_key and not api_key:
            attempts.append({"model_id": model_id, "ok": False, "error": f"no {spec.provider} API key"})
            continue

        try:
            if spec.provider == "anthropic":
                data, chat_result = run_anthropic(spec, api_key)
                agentic = False
            else:
                data, chat_result = run_agentic(spec, api_key, ollama_url)
                agentic = True
        except Exception as exc:  # any agent-run failure (bad key, provider down, tool error, timeout) falls through to the next model, like a bad provider call in the direct-call path
            log.warning("Model '%s' failed for user %s (%s), falling back: %s", model_id, user.id, kind, exc)
            usage.record(db, user, spec.id, spec.provider, kind, None, success=False)
            attempts.append({"model_id": model_id, "ok": False, "error": str(exc)[:200]})
            continue

        usage.record(db, user, spec.id, spec.provider, kind, chat_result, success=True)
        attempts.append({"model_id": model_id, "ok": True})
        return AgentOutcome(data=data, model_id=model_id, attempts=attempts, agentic=agentic)

    tried = "; ".join(f"{a['model_id']}: {a.get('error')}" for a in attempts)
    raise LLMError(f"All models failed. Tried — {tried}")


def run_kpi_with_fallback(db: Session, user: User, *, task: str, result: dict, trend_text: str, cluster: str, version: str, timeout: float = 600.0) -> AgentOutcome:
    return _run_with_fallback(
        db, user, kind="analysis", timeout=timeout,
        run_agentic=lambda spec, api_key, ollama_url: _run_kpi_attempt(
            spec, api_key, ollama_url, task=task, result=result, trend_text=trend_text, cluster=cluster, version=version, timeout=timeout),
        run_anthropic=lambda spec, api_key: _run_kpi_anthropic_fallback(
            spec, api_key, task=task, result=result, trend_text=trend_text, cluster=cluster, version=version, timeout=timeout),
    )


def run_incident_with_fallback(db: Session, user: User, *, breached: list[dict], trend_text: str, cluster: str, version: str, timeout: float = 600.0) -> AgentOutcome:
    return _run_with_fallback(
        db, user, kind="analysis", timeout=timeout,
        run_agentic=lambda spec, api_key, ollama_url: _run_incident_attempt(
            spec, api_key, ollama_url, breached=breached, trend_text=trend_text, cluster=cluster, version=version, timeout=timeout),
        run_anthropic=lambda spec, api_key: _run_incident_anthropic_fallback(
            spec, api_key, breached=breached, trend_text=trend_text, cluster=cluster, version=version, timeout=timeout),
    )
