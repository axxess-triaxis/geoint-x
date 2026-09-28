"""Question answering over detected changes, grounded in deterministic tools.

Flow: route (LLM or rules) -> one allowlisted tool call -> answer (LLM or
template) from the tool result only. LLM answers are checked: every case id and
every quoted figure must appear in the tool result, otherwise the template
answer is used.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

from geointx.ai.client import LlmClient, LlmUnavailable
from geointx.ai.interpret import BANNED
from geointx.ai.tools import TOOL_SPECS, Tools, call_tool

CASE_ID = re.compile(r"\bCASE[-\s#]?0*(\d{1,4})\b", re.IGNORECASE)
NUMBER = re.compile(r"(?<![\w-])(\d+(?:\.\d+)?)(?![\w-])")
WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "six": 6, "twelve": 12}

ROUTER_SYSTEM = """You route questions about satellite-detected land-cover change cases in Assam to exactly one tool.
Return {{"tool": <name>, "args": {{...}}}} using only the tools and argument names listed. Case ids look like CASE-0001.
Known monitored area ids: {aoi_ids}. Known districts: {districts}."""

ANSWER_SYSTEM = """You answer an official's question using ONLY the TOOL RESULT JSON provided.
- Quote figures exactly as they appear in the result. Never estimate or invent numbers, places, or dates.
- Cases are suspected changes for verification; never say encroachment or illegality is established.
- If the result is empty or the time window has no observations, say so plainly and mention the latest observation date.
- Mention case ids you rely on in cited_case_ids. Answer in 2-6 short sentences or a short list."""


class ToolPlan(BaseModel):
    tool: str
    args: dict[str, Any]


class LlmAnswer(BaseModel):
    answer: str
    cited_case_ids: list[str]


def _months(q: str) -> int | None:
    m = re.search(r"(?:last|past)\s+(\d+|one|two|three|four|six|twelve)\s+months?", q, re.I)
    if m:
        v = m.group(1).lower()
        return int(v) if v.isdigit() else WORD_NUM[v]
    if re.search(r"(?:last|past)\s+year", q, re.I):
        return 12
    return None


def rule_route(question: str, aoi_ids: dict[str, str], districts: list[str]) -> ToolPlan:
    q = question.lower()
    if m := CASE_ID.search(question):
        return ToolPlan(tool="get_case", args={"case_id": f"CASE-{int(m.group(1)):04d}"})
    if "wetland" in q and any(w in q for w in ("largest", "most", "biggest", "which", "rank")):
        return ToolPlan(tool="wetland_ranking", args={})
    district = next((d for d in districts if d.lower() in q), None)
    aoi = next(
        (
            aid
            for aid, name in aoi_ids.items()
            if aid.replace("_", " ") in q or name.lower().split(",")[0] in q
        ),
        None,
    )
    months = _months(question)
    if any(
        w in q for w in ("by district", "per district", "each district", "by category", "by type")
    ):
        return ToolPlan(
            tool="aggregate",
            args={
                "group_by": "district" if "district" in q else "transition",
                "since_months": months,
            },
        )
    if aoi and any(w in q for w in ("summar", "overview", "around", "what happened")):
        return ToolPlan(tool="area_summary", args={"aoi_id": aoi})
    args: dict[str, Any] = {"since_months": months}
    if district:
        args["district"] = district
    if aoi:
        args["aoi_id"] = aoi
    if "confirmed" in q:
        args["status"] = "CONFIRMED"
    elif "rejected" in q:
        args["status"] = "REJECTED"
    if any(w in q for w in ("largest", "biggest", "significant")):
        args["sort_by"] = "area"
    return ToolPlan(tool="list_cases", args=args)


def _fmt_case(c: dict[str, Any]) -> str:
    return (
        f"{c['case_id']} ({c['priority_band']}, {c['status']}): {c['transition'].replace('_', ' ')}, "
        f"{c['area_ha']:.2f} ha, {c['district'] or 'district n/a'}, "
        f"observed {c['observed_between'][0]} to {c['observed_between'][1]}"
    )


def template_answer(tool: str, result: dict[str, Any]) -> str:
    if "error" in result:
        return str(result["error"])
    if tool == "list_cases":
        n = result["total_matching"]
        head = f"{n} matching case(s), {result['total_area_ha']:.2f} ha in total"
        if result.get("time_window"):
            head += f" ({result['time_window']})"
        if n == 0:
            return (
                head
                + f". Latest observation in the system: {result.get('latest_observation_in_system') or 'none'}."
            )
        return head + ":\n" + "\n".join(f"- {_fmt_case(c)}" for c in result["cases"])
    if tool == "get_case":
        lines = [_fmt_case(result)]
        for f in sorted(result["priority_breakdown"], key=lambda f: -f["contribution"]):
            lines.append(
                f"- {f['name'].replace('_', ' ')}: +{f['contribution']:.1f} ({f['explanation']})"
            )
        return "Priority breakdown for " + lines[0] + "\n" + "\n".join(lines[1:])
    if tool == "aggregate":
        rows = [
            f"- {k}: {v['cases']:.0f} case(s), {v['area_ha']:.2f} ha"
            for k, v in result["groups"].items()
        ]
        return f"Detected change by {result['group_by']}:\n" + ("\n".join(rows) or "- no cases")
    if tool == "wetland_ranking":
        rows = [
            f"- {r['polygon']}: {r['changed_area_inside_ha']:.2f} ha changed inside, "
            f"{r['changed_area_in_buffer_ha']:.2f} ha in the watch buffer"
            + (f" ({', '.join(r['case_ids'])})" if r["case_ids"] else "")
            for r in result["monitored_boundaries"]
        ]
        return "Monitored wetlands and protected areas by detected change:\n" + "\n".join(rows)
    if tool == "area_summary":
        parts = [
            f"{result['name']} ({result['district'] or 'district n/a'}): {result['analyses_run']} analysis run(s), "
            f"{result['cases']} case(s)."
        ]
        for k, v in result["changed_area_by_transition_ha"].items():
            parts.append(f"- {k.replace('_', ' ')}: {v:.2f} ha")
        for c in result["top_cases"]:
            parts.append(f"- {_fmt_case(c)}")
        return "\n".join(parts)
    return json.dumps(result)[:2000]


def _numbers_in(obj: Any) -> list[float]:
    raw = json.dumps(obj, default=str)
    return [float(x) for x in NUMBER.findall(raw)]


def _answer_problems(ans: LlmAnswer, result: dict[str, Any]) -> list[str]:
    problems = []
    raw = json.dumps(result, default=str)
    for cid in ans.cited_case_ids + [f"CASE-{int(m):04d}" for m in CASE_ID.findall(ans.answer)]:
        if cid.upper() not in raw:
            problems.append(f"case id not in result: {cid}")
    allowed = _numbers_in(result)
    for n in NUMBER.findall(ans.answer):
        x = float(n)
        if x <= 12 and x == int(x):  # small counts / months are phrasing, not measurements
            continue
        if not any(abs(x - a) <= max(0.051, abs(a) * 0.01) for a in allowed):
            problems.append(f"unsupported figure {n}")
    if m := BANNED.search(ans.answer):
        problems.append(f"accusatory language: {m.group(0)}")
    return problems


def ask(
    question: str,
    tools: Tools,
    aoi_ids: dict[str, str],
    districts: list[str],
    llm: LlmClient | None,
) -> dict[str, Any]:
    route_source = "rules"
    plan = rule_route(question, aoi_ids, districts)
    if llm is not None:
        tool_desc = {
            n: {"description": d, "args": m.model_json_schema()} for n, (m, d) in TOOL_SPECS.items()
        }
        try:
            cand = llm.generate_json(
                ROUTER_SYSTEM.format(aoi_ids=list(aoi_ids), districts=districts),
                f"TOOLS: {json.dumps(tool_desc)}\nQUESTION: {question}",
                ToolPlan,
            )
            if cand.tool in TOOL_SPECS:
                TOOL_SPECS[cand.tool][0].model_validate(cand.args)
                plan, route_source = cand, "gemini"
        except (LlmUnavailable, ValueError):
            pass
    try:
        result = call_tool(tools, plan.tool, plan.args)
    except ValueError as e:
        plan = rule_route(question, aoi_ids, districts)
        route_source = f"rules (LLM route invalid: {str(e)[:60]})"
        result = call_tool(tools, plan.tool, plan.args)

    answer = template_answer(plan.tool, result)
    answer_source = "template"
    problems: list[str] = []
    if llm is not None:
        try:
            cand_ans = llm.generate_json(
                ANSWER_SYSTEM,
                f"QUESTION: {question}\nTOOL: {plan.tool}\nTOOL RESULT: {json.dumps(result, default=str)}",
                LlmAnswer,
            )
            problems = _answer_problems(cand_ans, result)
            if not problems:
                answer, answer_source = cand_ans.answer, "gemini"
        except LlmUnavailable as e:
            problems = [str(e)[:120]]
    raw = json.dumps(result, default=str)
    focus = sorted(set(re.findall(r"CASE-\d{4}", raw)))[:20]
    return {
        "question": question,
        "answer": answer,
        "answer_source": answer_source,
        "route_source": route_source,
        "tool": plan.tool,
        "args": plan.args,
        "result": result,
        "guard_problems": problems,
        "focus_case_ids": focus,
    }
