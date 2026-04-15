import re
from dataclasses import dataclass
from datetime import date


VALID_PROVIDERS = {"ollama", "groq", "chatgpt", "gemini", "claude"}
VALID_MODES = {"prompt", "generate"}

USE_CASE_GUIDANCE = {
    "career": "Highlight measurable outcomes, domain credibility, and clear next actions.",
    "content": "Emphasize audience fit, hook quality, and platform-appropriate tone.",
    "study": "Teach clearly, simplify complex topics, and include memory aids when useful.",
    "travel": "Optimize for practical planning, budgets, and local relevance.",
    "business": "Focus on decision quality, tradeoffs, and concise executive communication.",
    "coding": "Prefer precise technical steps, assumptions, and runnable examples when relevant.",
    "research": "Structure findings, note uncertainty, and keep claims evidence-aware.",
    "personal-brand": "Preserve authentic voice and align outputs with professional goals.",
    "general": "Provide direct, useful answers without unnecessary back-and-forth.",
}

PROVIDER_GUIDANCE = {
    "ollama": "Keep the prompt explicit and compact so smaller local models can follow it reliably.",
    "groq": "Use a crisp, direct structure and keep the output contract explicit.",
    "chatgpt": "Use strong structure, put the goal first, and ask for the final answer directly.",
    "gemini": "Ground the response in context and request a clear, practical output shape.",
    "claude": "Favor careful prose, nuanced reasoning, and concise assumptions when details are missing.",
}

PROFILE_FIELD_LABELS = {
    "occupation": "Occupation",
    "location": "Location",
    "age": "Age",
    "industry": "Industry",
    "primary_use_case": "Primary use case",
    "preferred_tone": "Preferred tone",
    "goals": "Goals",
}

PROFILE_FIELD_PRIORITY = {
    "career": ("occupation", "industry", "location", "goals", "preferred_tone"),
    "content": ("occupation", "industry", "goals", "preferred_tone", "location"),
    "study": ("occupation", "goals", "preferred_tone", "age"),
    "travel": ("location", "age", "goals", "preferred_tone"),
    "business": ("occupation", "industry", "goals", "location", "preferred_tone"),
    "coding": ("occupation", "industry", "goals", "preferred_tone"),
    "research": ("occupation", "industry", "goals", "preferred_tone", "location"),
    "personal-brand": ("occupation", "industry", "goals", "preferred_tone", "location"),
    "general": ("occupation", "location", "goals", "preferred_tone"),
}

HANDOFF_NOTES = {
    "ollama": "Live generation uses your local Ollama server. If it is unavailable, switch to Prompt Mode.",
    "groq": "Generate mode can call Groq directly when GROQ_API_KEY is configured. Prompt mode still gives you a ready-to-paste Groq prompt.",
    "chatgpt": "Generate mode can call OpenAI directly when OPENAI_API_KEY is configured. Prompt mode still gives you a ready-to-paste ChatGPT prompt.",
    "gemini": "Generate mode can call Gemini directly when GEMINI_API_KEY is configured. Prompt mode still gives you a ready-to-paste Gemini prompt.",
    "claude": "Generate mode can call Claude directly when ANTHROPIC_API_KEY is configured. Prompt mode still gives you a ready-to-paste Claude prompt.",
}

PROMPT_MODE_NOTES = {
    "ollama": "Prompt generated successfully. No model call was made.",
    "groq": "Prompt generated successfully. No model call was made.",
    "chatgpt": "Prompt generated successfully. No model call was made.",
    "gemini": "Prompt generated successfully. No model call was made.",
    "claude": "Prompt generated successfully. No model call was made.",
}

THINKING_STYLE_HINTS = {
    "career": "strategic, outcome-oriented, and practical",
    "content": "creative, audience-aware, and crisp",
    "study": "clear, patient, and memory-friendly",
    "travel": "practical, cost-aware, and location-sensitive",
    "business": "decision-oriented, tradeoff-aware, and concise",
    "coding": "precise, debug-friendly, and implementation-oriented",
    "research": "evidence-aware, structured, and careful with uncertainty",
    "personal-brand": "authentic, polished, and voice-consistent",
    "general": "structured, direct, and useful",
}

PROMPT_WIZARD_VARIANTS = (
    {
        "name": "goal-first",
        "compact": False,
        "thinking_position": "task",
        "profile_density": "full",
        "assumption_level": "brief",
    },
    {
        "name": "style-led",
        "compact": False,
        "thinking_position": "top",
        "profile_density": "full",
        "assumption_level": "strong",
    },
    {
        "name": "compact-executor",
        "compact": True,
        "thinking_position": "task",
        "profile_density": "trimmed",
        "assumption_level": "brief",
    },
    {
        "name": "analyst",
        "compact": False,
        "thinking_position": "instructions",
        "profile_density": "full",
        "assumption_level": "strong",
    },
)


def coerce_text(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        parts = [coerce_text(item) for item in value]
        return ", ".join(part for part in parts if part)
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def lookup_value(mapping, key, default=""):
    if mapping is None:
        return default
    if hasattr(mapping, "get"):
        return mapping.get(key, default)
    try:
        return mapping[key]
    except (KeyError, IndexError, TypeError):
        return default


def dedupe_preserve_order(items):
    seen = set()
    result = []
    for item in items:
        text = coerce_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def split_thinking_styles(raw_styles):
    if isinstance(raw_styles, (list, tuple, set)):
        items = [coerce_text(style) for style in raw_styles]
    else:
        text = coerce_text(raw_styles)
        if not text:
            return []
        items = [part.strip() for part in re.split(r"[,\n;/]+", text)]
    return dedupe_preserve_order(items)


def human_join(items):
    items = dedupe_preserve_order(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def resolve_thinking_styles(prompt_request, user_profile):
    fallback_styles = [
        coerce_text(lookup_value(user_profile, "preferred_tone")) or "Direct and polished",
        THINKING_STYLE_HINTS.get(prompt_request.use_case, THINKING_STYLE_HINTS["general"]),
    ]
    styles = split_thinking_styles(getattr(prompt_request, "thinking_styles", ""))
    if not styles:
        styles = fallback_styles
    return dedupe_preserve_order(styles)


def build_profile_lines(user_profile, prompt_request, profile_density):
    profile_values = {
        "occupation": user_profile["occupation"],
        "location": user_profile["location"],
        "age": calculate_age(user_profile["date_of_birth"]),
        "industry": user_profile["industry"] or "Not specified",
        "primary_use_case": user_profile["primary_use_case"],
        "preferred_tone": user_profile["preferred_tone"],
        "goals": user_profile["goals"],
    }
    prioritized_fields = list(PROFILE_FIELD_PRIORITY[prompt_request.use_case])
    if profile_density == "trimmed":
        prioritized_fields = prioritized_fields[:3]
    profile_lines = [
        f"{PROFILE_FIELD_LABELS[field]}: {profile_values[field]}"
        for field in prioritized_fields
        if profile_values.get(field)
    ]
    profile_lines.append(f"Stored profile focus: {user_profile['primary_use_case']}")
    return profile_lines


def build_task_lines(prompt_request):
    task_lines = [
        f"Current task: {prompt_request.task}",
        f"Use case: {prompt_request.use_case}",
        f"Audience: {prompt_request.audience}",
        f"Desired format: {prompt_request.desired_format}",
        f"Preferred length: {prompt_request.output_length}",
    ]
    return task_lines


def build_instruction_lines(prompt_request, thinking_styles, assumption_level, compact, thinking_position):
    if compact:
        instructions = [
            "Deliver the answer directly and use only profile details that materially improve the answer.",
            "If information is missing but not critical, make a brief assumption and continue.",
        ]
    else:
        instructions = [
            "Deliver the answer directly instead of asking the user to restate details already given.",
            "Use only profile details that materially improve the answer.",
            "If information is missing but not critical, state a brief assumption and continue.",
        ]

    if assumption_level == "strong":
        instructions.append("If a critical detail is missing, ask one clarifying question before proceeding.")

    if thinking_position == "instructions":
        instructions.append(f"Use a {human_join(thinking_styles)} thinking style while solving the task.")

    if compact:
        instructions.append(
            f"{USE_CASE_GUIDANCE[prompt_request.use_case]} {PROVIDER_GUIDANCE[prompt_request.target_provider]}"
        )
    else:
        instructions.append(USE_CASE_GUIDANCE[prompt_request.use_case])
        instructions.append(PROVIDER_GUIDANCE[prompt_request.target_provider])

    return instructions


def build_output_contract(compact):
    if compact:
        return [
            "Start with the final answer.",
            "Use bullets or headers only when they improve scanability.",
        ]

    return [
        "Start with the final answer.",
        "Use headers or bullets only if they make the result easier to scan.",
        "Avoid repeating the user's profile back unless it directly matters.",
    ]


def build_prompt_document(user_profile, prompt_request, thinking_styles, variant):
    profile_lines = build_profile_lines(user_profile, prompt_request, variant["profile_density"])
    task_lines = build_task_lines(prompt_request)
    instructions = build_instruction_lines(
        prompt_request,
        thinking_styles,
        variant["assumption_level"],
        variant["compact"],
        variant["thinking_position"],
    )
    output_contract = build_output_contract(variant["compact"])

    prompt_sections = [
        "You are an AI assistant working through a profile-aware orchestration layer.",
        "",
    ]

    prompt_sections.extend(
        [
            "User profile:",
            *[f"- {line}" for line in profile_lines],
            "",
            "Task brief:",
            *[f"- {line}" for line in task_lines],
            "",
            "Response instructions:",
            *[f"- {line}" for line in instructions],
            "",
            "Output contract:",
            *[f"- {line}" for line in output_contract],
        ]
    )

    return "\n".join(prompt_sections).strip()


def mutate_prompt_variants(user_profile, prompt_request):
    thinking_styles = resolve_thinking_styles(prompt_request, user_profile)
    variants = []

    for variant in PROMPT_WIZARD_VARIANTS:
        variant_config = dict(variant)
        prompt = build_prompt_document(user_profile, prompt_request, thinking_styles, variant_config)
        variants.append(
            {
                "variant": variant_config["name"],
                "config": variant_config,
                "thinking_styles": thinking_styles,
                "prompt": prompt,
            }
        )

    return variants


def score_prompt_variant(candidate, prompt_request):
    config = candidate["config"]
    prompt = candidate["prompt"]
    thinking_styles = candidate["thinking_styles"]
    score = 0
    strengths = []
    gaps = []

    if config["profile_density"] == "full":
        score += 16
        strengths.append("Includes a fuller profile snapshot.")
    else:
        score += 11
        strengths.append("Trims the profile to stay lean.")

    if config["thinking_position"] == "task":
        score += 15
        strengths.append("Keeps the thinking styles close to the task.")
    elif config["thinking_position"] == "top":
        score += 13
        strengths.append("Makes the thinking styles visible early.")
    else:
        score += 12
        strengths.append("Binds the thinking styles to the instructions.")

    if config["assumption_level"] == "strong":
        score += 12
        strengths.append("Explicitly handles missing critical details.")
    else:
        score += 8
        strengths.append("Keeps the instructions lightweight.")

    if config["compact"]:
        score += 10 if prompt_request.target_provider == "ollama" else 6
        strengths.append("Keeps the prompt compact.")
    else:
        score += 9
        strengths.append("Leaves enough room for a full response.")

    if thinking_styles:
        score += 8
    else:
        gaps.append("Thinking styles were not explicit.")

    if "Output contract:" in prompt:
        score += 8

    if "If information is missing but not critical" in prompt:
        score += 6
    if "If a critical detail is missing" in prompt:
        score += 6

    length = len(prompt)
    target_length = 900 if prompt_request.target_provider == "ollama" else 1200
    if length < target_length * 0.75:
        score -= 4
        gaps.append("The prompt may be too brief to guide the model consistently.")
    elif length > target_length * 1.5:
        score -= 6
        gaps.append("The prompt may be longer than necessary.")
    else:
        score += 6

    if prompt_request.use_case in {"coding", "research", "business"} and not config["compact"]:
        score += 4
    if prompt_request.use_case in {"travel", "content", "general"} and config["compact"]:
        score += 3

    if prompt_request.target_provider == "ollama" and config["compact"]:
        score += 4
    if prompt_request.target_provider in {"groq", "chatgpt", "claude"} and not config["compact"]:
        score += 3
    if prompt_request.target_provider == "gemini" and config["thinking_position"] != "instructions":
        score += 2

    return {
        "candidate": candidate,
        "score": score,
        "strengths": strengths,
        "gaps": gaps,
        "length": length,
    }


def score_prompt_variants(candidates, prompt_request):
    scored_candidates = [score_prompt_variant(candidate, prompt_request) for candidate in candidates]
    return sorted(scored_candidates, key=lambda item: item["score"], reverse=True)


def critique_prompt(scored_candidates, prompt_request):
    best = scored_candidates[0]
    runner_up = scored_candidates[1] if len(scored_candidates) > 1 else None
    config = best["candidate"]["config"]
    strengths = []
    weaknesses = []

    if config["profile_density"] == "full":
        strengths.append("It uses enough profile context to avoid repeating the background.")
    else:
        strengths.append("It stays compact enough for fast iteration.")

    if config["thinking_position"] == "task":
        strengths.append("It keeps the thinking styles close to the task block.")
    elif config["thinking_position"] == "top":
        strengths.append("It surfaces the reasoning style early.")
    else:
        strengths.append("It ties the reasoning style directly to the instructions.")

    if config["assumption_level"] == "strong":
        strengths.append("It protects against missing critical details.")
    else:
        weaknesses.append("It could be clearer about what to do when a critical detail is missing.")

    if prompt_request.target_provider == "ollama" and not config["compact"]:
        weaknesses.append("A smaller local model may benefit from a tighter prompt.")
    if prompt_request.target_provider in {"groq", "chatgpt", "claude"} and config["compact"]:
        weaknesses.append("A hosted model can usually handle a little more context and structure.")
    if prompt_request.use_case in {"coding", "research"} and config["compact"]:
        weaknesses.append("This use case usually benefits from a fuller context block.")

    if runner_up and runner_up["score"] >= best["score"] - 2:
        weaknesses.append(
            f"The {runner_up['candidate']['variant']} variant is close enough to suggest the balance of brevity and context could still move."
        )

    if prompt_request.thinking_styles and config["thinking_position"] != "task":
        weaknesses.append("The thinking styles are present, but they should sit closer to the task.")

    return {
        "strengths": strengths,
        "weaknesses": weaknesses,
    }


def synthesize_prompt(best_candidate, critique, user_profile, prompt_request):
    refined_config = dict(best_candidate["candidate"]["config"])
    needs_stronger_gap_rule = any("critical detail" in item.lower() for item in critique["weaknesses"])
    needs_task_style_anchor = any("thinking styles" in item.lower() for item in critique["weaknesses"])
    needs_more_context = any("more context" in item.lower() for item in critique["weaknesses"])
    needs_tighter_prompt = any("tighter prompt" in item.lower() for item in critique["weaknesses"])
    needs_full_context = any("fuller context" in item.lower() for item in critique["weaknesses"])

    if needs_stronger_gap_rule:
        refined_config["assumption_level"] = "strong"

    if needs_task_style_anchor:
        refined_config["thinking_position"] = "task"

    if needs_tighter_prompt or prompt_request.target_provider == "ollama":
        refined_config["compact"] = True
        refined_config["profile_density"] = "trimmed"

    if needs_more_context or needs_full_context or prompt_request.use_case in {"coding", "research", "business"}:
        refined_config["compact"] = False if prompt_request.target_provider != "ollama" else refined_config["compact"]
        refined_config["profile_density"] = "full" if prompt_request.target_provider != "ollama" else refined_config["profile_density"]

    refined_candidate = {
        "variant": f"{best_candidate['candidate']['variant']} + critique",
        "config": refined_config,
        "thinking_styles": best_candidate["candidate"]["thinking_styles"],
    }
    refined_candidate["prompt"] = build_prompt_document(
        user_profile,
        prompt_request,
        refined_candidate["thinking_styles"],
        refined_candidate["config"],
    )
    return refined_candidate


def format_scoreboard(scored_candidates):
    return ", ".join(f"{item['candidate']['variant']}={item['score']}" for item in scored_candidates)


def format_trace(result):
    strengths = "; ".join(result["critique"]["strengths"]) if result["critique"]["strengths"] else "none"
    weaknesses = "; ".join(result["critique"]["weaknesses"]) if result["critique"]["weaknesses"] else "none"
    return "\n".join(
        [
            "Prompt wizard",
            f"- Mutate: generated {len(result['candidates'])} prompt variants from the task and thinking styles.",
            f"- Scoring: {format_scoreboard(result['scored_candidates'])}. Selected {result['selected_variant']} at {result['selected_score']}.",
            f"- Critique strengths: {strengths}.",
            f"- Critique gaps: {weaknesses}.",
            f"- Synthesize: {result['selection_note']} It was rescored at {result['refined_score']}.",
        ]
    ).strip()


def run_prompt_wizard(user_profile, prompt_request):
    candidates = mutate_prompt_variants(user_profile, prompt_request)
    scored_candidates = score_prompt_variants(candidates, prompt_request)
    best_candidate = scored_candidates[0]
    critique = critique_prompt(scored_candidates, prompt_request)
    refined_candidate = synthesize_prompt(best_candidate, critique, user_profile, prompt_request)
    refined_scored_candidate = score_prompt_variant(refined_candidate, prompt_request)

    if refined_scored_candidate["score"] >= best_candidate["score"]:
        selected = refined_scored_candidate
        selection_note = "The refined prompt won the iteration and replaced the original best draft."
    else:
        selected = best_candidate
        selection_note = "The original best draft remained stronger, so it was retained."

    result = {
        "final_prompt": selected["candidate"]["prompt"],
        "selected_variant": selected["candidate"]["variant"],
        "selected_score": selected["score"],
        "initial_best_variant": best_candidate["candidate"]["variant"],
        "initial_best_score": best_candidate["score"],
        "refined_variant": refined_scored_candidate["candidate"]["variant"],
        "refined_score": refined_scored_candidate["score"],
        "selection_note": selection_note,
        "candidates": [
            {
                "variant": item["candidate"]["variant"],
                "score": item["score"],
                "length": item["length"],
            }
            for item in scored_candidates
        ],
        "scored_candidates": scored_candidates,
        "critique": critique,
    }
    result["trace"] = format_trace(result)
    return result


@dataclass
class PromptRequest:
    task: str
    use_case: str
    target_provider: str
    mode: str
    audience: str
    desired_format: str
    output_length: str
    model: str
    thinking_styles: str

    @classmethod
    def from_payload(cls, payload):
        task = coerce_text(payload.get("task"))
        use_case = coerce_text(payload.get("use_case", "general")).lower()
        target_provider = coerce_text(payload.get("target_provider", "groq")).lower()
        mode = coerce_text(payload.get("mode", "prompt")).lower()

        if not task:
            raise ValueError("Describe the task you want the AI to handle.")
        if target_provider not in VALID_PROVIDERS:
            raise ValueError("Choose a supported provider target.")
        if mode not in VALID_MODES:
            raise ValueError("Choose prompt mode or generate mode.")
        if use_case not in USE_CASE_GUIDANCE:
            use_case = "general"

        return cls(
            task=task,
            use_case=use_case,
            target_provider=target_provider,
            mode=mode,
            audience=coerce_text(payload.get("audience")) or "General audience",
            desired_format=coerce_text(payload.get("desired_format")) or "Concise answer",
            output_length=coerce_text(payload.get("output_length")) or "Medium",
            model=coerce_text(payload.get("model")),
            thinking_styles=coerce_text(payload.get("thinking_styles")),
        )


def build_handoff_note(provider, mode):
    if mode == "prompt":
        return PROMPT_MODE_NOTES[provider]

    if mode == "generate" and provider != "ollama":
        return (
            f"{HANDOFF_NOTES[provider]} If the required provider key is missing, PromptPilot will still "
            "return the optimized prompt for manual use."
        )
    return HANDOFF_NOTES[provider]


def calculate_age(date_of_birth):
    try:
        born = date.fromisoformat(date_of_birth)
    except ValueError:
        return "Unknown age"

    today = date.today()
    years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return f"{years} years old"


def build_prompt(user_profile, prompt_request):
    return run_prompt_wizard(user_profile, prompt_request)["final_prompt"]
