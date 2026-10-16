"""
Meera - Academic & Research Assistant Skill
Specializes the agent in literature analysis, hypothesis formalization, and paper synthesis.
"""
from skills.manifest import SkillManifest


def get_academic_skill() -> SkillManifest:
    return SkillManifest(
        id="academic_research",
        name="Academic & Research Assistant",
        description="Specialized in document reading, structured literature analysis, and thesis drafting",
        system_prompt_extension=(
            "[Active Skill: Academic Research]\n"
            "- Extract core methodology, experimental setups, baselines, and ablation results.\n"
            "- Critique empirical validity, note theoretical limitations, and maintain formal academic tone.\n"
            "- Use read_file and search_files to cross-reference citations and workspace papers."
        ),
        keywords=["paper", "thesis", "research", "citation", "hypothesis", "literature", "arxiv", "methodology"],
        recommended_tools=["read_file", "search_files", "list_directory"],
        example_prompts=[
            "Extract the key contributions and methodology from the uploaded paper.",
            "Formulate a structured literature review section comparing transformer attention heads.",
            "Draft a research abstract summarizing our experimental findings.",
        ],
    )
