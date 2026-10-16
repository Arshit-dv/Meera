"""
Meera - Code Synthesis & Software Architecture Skill
Specializes the agent in algorithmic reasoning, clean architecture, and debugging.
"""
from skills.manifest import SkillManifest


def get_coding_skill() -> SkillManifest:
    return SkillManifest(
        id="code_synthesis",
        name="Core Reasoning & Code Synthesis",
        description="Specialized in software architecture, clean patterns, algorithms, and bug diagnosis",
        system_prompt_extension=(
            "[Active Skill: Code Synthesis]\n"
            "- Prioritize pure standard library, minimal allocations, and modular architecture.\n"
            "- Analyze edge cases, time/space complexity (Big-O), and async/thread safety.\n"
            "- Use python_eval for testing computations and run_command for verified execution."
        ),
        keywords=["code", "python", "bug", "algorithm", "refactor", "function", "class", "architecture", "debug"],
        recommended_tools=["python_eval", "list_directory", "read_file", "run_command"],
        example_prompts=[
            "Design a lightweight, thread-safe memory cache using standard library.",
            "Analyze time and space complexity of this search algorithm.",
            "Diagnose potential deadlock conditions in multi-threaded socket handling.",
        ],
    )
