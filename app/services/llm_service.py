"""
LLM Service — Wraps Claude (Anthropic) and Gemini (Google) for AI matching analysis.

Usage:
    svc = LLMService("claude")  # or "gemini"
    analysis = svc.analyze_one(job, student, scores)
    batch   = svc.analyze_batch(tasks, job)

Env vars required:
    ANTHROPIC_API_KEY  — for provider="claude"
    GEMINI_API_KEY     — for provider="gemini"
"""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are an expert talent acquisition analyst specialising in matching international "
    "students with Japanese internship opportunities. Analyse the candidate-job match and "
    "respond ONLY with valid JSON — no markdown fences, no extra text, no comments."
)

_OUTPUT_SCHEMA = {
    "overall_assessment": "2-3 sentence summary of the candidate-job fit",
    "strengths": ["key strength 1", "key strength 2", "key strength 3"],
    "gaps": ["gap 1 (or 'None identified' if no gaps)"],
    "cultural_fit_score": 75,
    "growth_potential_score": 80,
    "recommendation": "Strong Hire | Consider | Further Review | Pass",
    "detailed_reasoning": "One paragraph explaining the recommendation",
    "interview_questions": [
        "Tailored question 1",
        "Tailored question 2",
        "Tailored question 3",
    ],
}


def _build_prompt(job: dict, student: dict, scores: dict) -> str:
    student_skills = ", ".join(student.get("skills") or []) or "Not specified"
    job_skills = ", ".join(job.get("skills") or []) or "Not specified"
    desc = (job.get("description") or "N/A")[:400]

    return (
        f"Analyse this candidate for a Japanese internship role.\n\n"
        f"JOB:\n"
        f"  Title: {job.get('title', 'N/A')}\n"
        f"  Department: {job.get('department', 'N/A')}\n"
        f"  Description: {desc}\n"
        f"  Required Skills: {job_skills}\n"
        f"  Required Japanese Level: {job.get('required_language') or 'None'}\n\n"
        f"CANDIDATE:\n"
        f"  University: {student.get('university_name', 'N/A')}\n"
        f"  Department: {student.get('department', 'N/A')}\n"
        f"  GPA: {student.get('gpa', 'N/A')}\n"
        f"  Skills: {student_skills}\n"
        f"  Japanese Level: {student.get('jp_level') or 'None'}\n"
        f"  Research: {student.get('research_title') or 'None'}\n"
        f"  Graduation Year: {student.get('graduation_year', 'N/A')}\n\n"
        f"ALGORITHMIC SCORES (0-100):\n"
        f"  Overall: {scores.get('total', 0)}  |  "
        f"Skills: {scores.get('skill_match', 0)}  |  "
        f"Research: {scores.get('research_sim', 0)}  |  "
        f"Language: {scores.get('lang_readiness', 0)}  |  "
        f"Trajectory: {scores.get('learning_traj', 0)}\n\n"
        f"Respond ONLY with JSON:\n{json.dumps(_OUTPUT_SCHEMA, indent=2)}"
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Parse JSON from LLM response, stripping markdown fences if present."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        text = m.group(1).strip()
    return json.loads(text)


def _validate(raw: dict) -> dict:
    """Coerce + cap all fields so callers get a predictable shape."""
    recommendation = str(raw.get("recommendation", "Further Review"))
    valid_recs = {"Strong Hire", "Consider", "Further Review", "Pass"}
    if recommendation not in valid_recs:
        recommendation = "Further Review"

    return {
        "overall_assessment": str(raw.get("overall_assessment", ""))[:600],
        "strengths": [str(s) for s in (raw.get("strengths") or [])][:5],
        "gaps": [str(g) for g in (raw.get("gaps") or [])][:5],
        "cultural_fit_score": max(0, min(100, int(raw.get("cultural_fit_score", 50)))),
        "growth_potential_score": max(0, min(100, int(raw.get("growth_potential_score", 50)))),
        "recommendation": recommendation,
        "detailed_reasoning": str(raw.get("detailed_reasoning", ""))[:1000],
        "interview_questions": [str(q) for q in (raw.get("interview_questions") or [])][:5],
    }


# ---------------------------------------------------------------------------
# Provider-specific callers
# ---------------------------------------------------------------------------

def _call_claude(client, prompt: str) -> dict:
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_json(msg.content[0].text)


def _call_gemini(client, prompt: str) -> dict:
    resp = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"{_SYSTEM_PROMPT}\n\n{prompt}",
        config={"temperature": 0.2, "max_output_tokens": 1024},
    )
    return _extract_json(resp.text)


# ---------------------------------------------------------------------------
# LLMService
# ---------------------------------------------------------------------------

class LLMService:
    """Unified LLM client supporting 'claude' and 'gemini' providers."""

    def __init__(self, provider: str):
        self.provider = provider
        self._claude_client = None
        self._gemini_model = None

        if provider == "claude":
            try:
                import anthropic  # noqa: F401  (checked here, used in _call_claude)
            except ImportError:
                raise RuntimeError("anthropic package missing — run: pip install anthropic")
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY is not set in environment")
            import anthropic as _anthropic
            self._claude_client = _anthropic.Anthropic(api_key=api_key)

        elif provider == "gemini":
            try:
                from google import genai as _genai  # noqa: F401
            except ImportError:
                raise RuntimeError(
                    "google-genai package missing — run: pip install google-genai"
                )
            api_key = os.getenv("GEMINI_API_KEY", "")
            if not api_key:
                raise ValueError("GEMINI_API_KEY is not set in environment")
            from google import genai as _google_genai
            self._gemini_model = _google_genai.Client(api_key=api_key)

        else:
            raise ValueError(f"Unknown LLM provider {provider!r}. Use 'claude' or 'gemini'.")

    # ------------------------------------------------------------------

    def analyze_one(self, job: dict, student: dict, scores: dict) -> Optional[dict]:
        """
        Analyse a single candidate against a job.
        Returns a validated dict or None if the LLM call fails.
        """
        try:
            prompt = _build_prompt(job, student, scores)
            if self.provider == "claude":
                raw = _call_claude(self._claude_client, prompt)
            else:
                raw = _call_gemini(self._gemini_model, prompt)
            result = _validate(raw)
            result["provider"] = self.provider
            return result
        except Exception:
            return None

    def analyze_batch(
        self,
        tasks: list,   # [(student_id, student_dict, scores_dict), ...]
        job: dict,
        max_workers: int = 5,
    ) -> dict:
        """
        Parallel-analyse a batch of candidates for the given job.
        Returns {student_id: analysis_dict}.  Failed analyses are silently skipped.
        """
        results: dict = {}

        def _worker(task):
            sid, student, scores = task
            return sid, self.analyze_one(job, student, scores)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_worker, t): t[0] for t in tasks}
            for future in as_completed(futures):
                try:
                    sid, analysis = future.result(timeout=30)
                    if analysis:
                        results[sid] = analysis
                except Exception:
                    pass

        return results
