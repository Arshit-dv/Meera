"""
Meera - Career Strategist & Technical Interviewer Skill
Specializes the agent in resume tailoring, STAR-method interview drills, and career strategy.
"""
from skills.manifest import SkillManifest


def get_career_skill() -> SkillManifest:
    return SkillManifest(
        id="career_strategist",
        name="Internship & Career Strategist",
        description="Specialized in resume ATS alignment, system design interview drills, and portfolio strategy",
        system_prompt_extension=(
            "[Active Skill: Career Strategist]\n"
            "- Evaluate technical resumes against Job Descriptions using high-impact action verbs and quantified metrics.\n"
            "- Conduct rigorous behavioral mock interviews using the STAR method (Situation, Task, Action, Result).\n"
            "- Guide system design trade-offs (latency vs throughput, consistency vs availability)."
        ),
        keywords=["resume", "interview", "job", "career", "ats", "internship", "portfolio", "star", "hiring"],
        recommended_tools=["read_file", "search_files"],
        example_prompts=[
            "Review my resume bullet points for high-frequency ATS keyword alignment.",
            "Run a technical mock interview scenario focusing on distributed consensus.",
            "Conduct a behavioral interview practice question using the STAR method.",
        ],
    )
