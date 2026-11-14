#!/usr/bin/env python3
"""
Template dev server for video-lens.
Edit viewer/*, run this script (or `task dev`), and see the result through the production
renderer. It rebuilds skills/video-lens/template.html from viewer/ first.

Usage:
    python scripts/yt_template_dev.py
"""
import os
import subprocess
import sys
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "skills" / "video-lens" / "template.html"
OUTPUT_PATH = os.path.expanduser('~/Downloads/video-lens/reports/video-lens_sample_output.html')

sys.path.insert(0, str(REPO_ROOT / "skills" / "video-lens" / "scripts"))
from render_report import render_from_payload  # noqa: E402

# ── Hardcoded content for https://www.youtube.com/watch?v=3Y1G9najGiI ──────
# AWS re:Invent 2025 — Werner Vogels final keynote
#
# The agent's payload shape (v1 arrays, as SKILL.md asks for): KEY_POINTS with point, why,
# detail and t (the start of an outline entry), OUTLINE with t, title, detail. Text uses raw
# Unicode and the inline markers **bold**, *em* and `code`; the renderer escapes the rest.
# DESCRIPTION_SECTION is HTML; the sanitiser keeps its allowed tags.

CONTENT = {
    "VIDEO_ID": "3Y1G9najGiI",

    "VIDEO_TITLE": "AWS re:Invent 2025 - Keynote with Dr. Werner Vogels",

    "VIDEO_URL": "https://www.youtube.com/watch?v=3Y1G9najGiI",

    "META_LINE": "AWS Events · 1h 16m · Dec 5 2025 · 13.8M views",

    "SUMMARY": (
        "Werner Vogels uses his final AWS re:Invent keynote — after 14 consecutive years — "
        "to argue that today's AI moment is not the end of developers but the start of a new "
        "Renaissance, one that will transform the role rather than eliminate it. He introduces the "
        "“Renaissance Developer” framework: five qualities — curiosity, systems "
        "thinking, communication with precision, ownership, and polymathism — that distinguish "
        "builders who will thrive in an AI-driven world. His most concrete warning is the concept of "
        "“verification debt”: AI generates code faster than humans can understand it, "
        "creating a gap where quality problems enter production unless deliberate mechanisms like "
        "spec-driven development and code reviews are in place. The keynote closes with an appeal to "
        "professional pride in the invisible craft of keeping reliable systems running."
    ),

    "KEY_POINTS": [{'t': 314,
      'point': 'AI will not make developers obsolete — if they evolve',
      'why': 'Vogels reframes the keynote’s central question from “Will AI take my job?” to “Will AI '
             'make me obsolete?” and answers: “Absolutely not — if you evolve.”',
      'detail': 'Every generation of developers has faced a wave of change — compilers, structured '
                'programming, object-oriented languages, cloud infrastructure — and each time the role '
                'transformed rather than disappeared. Vogels argues the pattern holds: some tasks will '
                'be automated and some skills will become obsolete, but builders who continuously '
                'adapt remain essential. His core refrain, repeated throughout the talk, is *“the work '
                'is yours, not that of the tools”* — including regulatory and quality responsibility '
                'that cannot be offloaded to an AI.'},
     {'t': 876,
      'point': 'The Renaissance Developer framework: five qualities for the AI era',
      'why': 'Drawing on the 15th-century Renaissance as an analogy for today’s convergence of AI, '
             'robotics, and space exploration, Vogels proposes five qualities: **curiosity**, '
             '**systems thinking**, **precision communication**, **ownership**, and **polymathism**.',
      'detail': 'The Renaissance analogy is precise: new tools (pencil, microscope, printing press) '
                'and cross-disciplinary thinking were inseparable from the era’s scientific '
                'breakthroughs. Da Vinci worked across painting, engineering, economics, and invention '
                'simultaneously. Today’s convergence of multiple technological golden ages reinforces '
                'each other in the same way. Vogels argues the same mental qualities that made '
                'Renaissance scientists effective — curiosity, bold experimentation, building bridges '
                'between fields — are directly applicable to the challenge of developing software in '
                'an AI-assisted world.'},
     {'t': 1189,
      'point': 'Curiosity + the Yerkes-Dodson learning curve',
      'why': 'Real learning happens on the rising slope of the Yerkes-Dodson bell curve, where '
             'curiosity meets challenge; too little pressure leads to disengagement, too much to '
             'overwhelm.',
      'detail': 'Vogels uses this psychological law to frame experimentation and failure as essential, '
                'not incidental. He draws an analogy to language acquisition: grammar study only takes '
                'you so far — *“real learning begins where you stumble into a conversation.”* Software '
                'works the same way: the failed build and the broken assumption teach you how a system '
                'actually behaves, in ways that documentation cannot. Learning is also social: '
                'conferences, user groups, and conversations with other builders are not optional '
                'enrichment but a required part of staying sharp.'},
     {'t': 2000,
      'point': 'Systems thinking: structure and feedback loops determine behavior',
      'why': 'Donella Meadows’ definition: *“A system is a set of things, interconnected in such a way '
             'that they produce their own patterns of behavior over time.”*',
      'detail': 'The Yellowstone wolf trophic cascade is Vogels’ central illustration: removing wolves '
                'caused elk to overgraze, rivers to erode, and the entire park ecosystem to degrade — '
                'even though wolves never touched the rivers. Reintroducing them in 2010 reversed the '
                'damage. The software lesson: every service, API, queue, and team ownership boundary '
                'is part of a larger system with feedback loops. Add a cache and you shift traffic '
                'flow; change team ownership and you change delivery pace. **Structure changes, '
                'behavior changes; feedback changes, outcome changes.** Meadows’ paper “Leverage '
                'Points: Places to Intervene in a System” is assigned as homework.'},
     {'t': 2284,
      'point': 'Communication with precision: specifications reduce the ambiguity of natural language',
      'why': 'In AI-assisted coding, developers communicate in natural language (ambiguous) rather '
             'than programming languages (precise), making specifications the critical bridge between '
             'intent and correct output.',
      'detail': 'Vogels notes that natural language works for humans because we use tone, context, and '
                'shared knowledge to disambiguate. Machines need precision — which is why programming '
                'languages were invented. As AI tools take natural-language prompts, the ambiguity '
                'problem re-enters. He references Dijkstra’s formal-specification methods and the '
                'Apollo Guidance Computer’s 145,000-line codebase (guided by meticulous specs) as '
                'proof that spec-driven development produces correct, verifiable software. The same '
                'principle applies to communicating with a business stakeholder: Werner’s “Frugal '
                'Architect” tiering of Amazon’s homepage (Tier 1/2/3 by availability requirement) is '
                'presented as a communication tool, not just an engineering one.'},
     {'t': 2574,
      'point': 'Kiro IDE and spec-driven development: requirements → design → tasks before code',
      'why': 'Clare Liguori’s Kiro IDE replaces a single ambiguous vibe-coding prompt with a '
             'structured workflow: Kiro generates **requirements, design, and tasks** from the '
             'developer’s description, which the developer refines before any code is written.',
      'detail': 'The key insight from building Kiro with Kiro: a prompt like “build me a web trivia '
                'game” has *“probably a million different possible final outcomes,”* but only one is '
                'what you had in mind. With vibe coding, the AI guesses and you iterate on code; with '
                'spec-driven development, you iterate on the spec first. In a production case study '
                '(system notifications for the Kiro IDE), the spec workflow surfaced a much larger '
                'architectural problem — building on Electron’s native notification API across a '
                '2-million-line codebase — at the design stage rather than in the code. The feature '
                'shipped in roughly half the time of an equivalent vibe-coded approach.'},
     {'t': 3219,
      'point': 'Verification debt: AI generates code faster than humans can comprehend it',
      'why': 'When you write code yourself, comprehension comes with the act of creation; when the '
             'machine writes it, you must rebuild that comprehension during review — a gap Vogels '
             'calls **verification debt**.',
      'detail': 'This gap is one of two main challenges Vogels hears from developers adopting AI tools '
                '(the other being hallucination). The practical consequence: code can move toward '
                'production before anyone has truly validated what it does. Code reviews therefore '
                'become *more* important in an AI-driven world, not less — they are the control point '
                'where human judgment re-enters the loop. Vogels specifically calls out the '
                'knowledge-transfer value of human-to-human reviews: seniors bring pattern recognition '
                'and hard-earned judgment, juniors bring fresh eyes, and together they grow the next '
                'generation of builders in a way that AI cannot replicate.'},
     {'t': 3595,
      'point': 'Mechanisms, not good intentions, ensure quality',
      'why': 'Everyone at Amazon had good intentions about product quality, but nothing changed until '
             'Bezos introduced a *mechanism*: a button customer-service agents could press to make a '
             'product unlisted, triggering automatic alarms.',
      'detail': 'The Andon Cord story (adapted from Toyota’s manufacturing principle: no car leaves '
                'the line with a known defect) illustrates that **mechanisms convert good intentions '
                'into consistent outcomes**. The S3 team’s durability reviews — pausing any change '
                'touching durability to model risks, list threats, and map guardrails — turn '
                'durability from a property of code into an *“organizational habit.”* In an AI-driven '
                'world, the same logic applies to hallucination and verification debt: good intentions '
                'are not enough; you need spec-driven workflows, automated testing pipelines, and '
                'mandatory code reviews as structural mechanisms.'},
     {'t': 3916,
      'point': 'Become a polymath: T-shaped over I-shaped',
      'why': 'I-shaped developers are deep in one domain only; T-shaped developers combine that depth '
             'with broad cross-disciplinary knowledge that lets them see how their work fits into a '
             'larger system.',
      'detail': 'Jim Gray — Turing Award winner and inventor of database transactions — exemplifies '
                'the T-shape: he could diagnose a wrong database layout by listening to the rattling '
                'of disks for 30 seconds, a *“sixth sense built from decades of experience.”* But his '
                'curiosity extended far beyond databases to people, business, and other technologies. '
                'His work on the Sloan Digital Sky Survey shows how deep database expertise, applied '
                'to an entirely different domain (astronomy), was transformative. Vogels’ advice: '
                'develop deep domain expertise, but cultivate the range to connect it to adjacent '
                'disciplines — *“broaden your T.”*'}],

    "OUTLINE": [{'t': 0,
      'title': 'Opening Cinematic',
      'detail': 'A short film traces recurring “end of the developer” fears across technology eras — '
                'punch cards, COBOL, cloud — framing the keynote’s central question.'},
     {'t': 314,
      'title': 'Werner’s Farewell & Central Question',
      'detail': 'Werner announces this is his final re:Invent keynote after 14 years, then addresses '
                'the question every customer asks: “Will AI make me obsolete?”'},
     {'t': 573,
      'title': 'History of Developer Evolution',
      'detail': 'From assembly and COBOL to compilers, OOP, microservices, and cloud — each wave '
                'automated tasks and required new skills, and developers adapted every time.'},
     {'t': 876,
      'title': 'A New Renaissance',
      'detail': 'Vogels argues that today’s convergence of AI, robotics, and space travel mirrors the '
                '15th-century Renaissance, where curiosity, new tools, and cross-disciplinary thinking '
                'exploded simultaneously.'},
     {'t': 1189,
      'title': 'Quality 1: Be Curious',
      'detail': 'Curiosity drives learning; the Yerkes-Dodson Law locates peak learning on the rising '
                'slope between disengagement and overwhelm, where curiosity meets real challenge.'},
     {'t': 1510,
      'title': 'Learning from the Field: Africa & Latin America',
      'detail': 'Real-world examples from Vogels’ travels — Ocean Cleanup’s AI river model, Rwanda’s '
                'health intelligence center, and KOKO Networks’ ethanol ATMs in Nairobi — show '
                'developers solving humanity’s hardest problems.'},
     {'t': 2000,
      'title': 'Quality 2: Think in Systems',
      'detail': 'Donella Meadows’ systems theory and the Yellowstone wolf trophic cascade illustrate '
                'how a single feedback loop can reshape an entire system — a lesson directly '
                'applicable to software architecture.'},
     {'t': 2284,
      'title': 'Quality 3: Communicate with Precision',
      'detail': 'Natural language is ambiguous; specifications reduce that ambiguity, both when '
                'communicating with AI tools and when aligning engineering decisions with business '
                'stakeholders.'},
     {'t': 2574,
      'title': 'Kiro IDE: Spec-Driven Development Demo',
      'detail': 'Clare Liguori walks through how the Kiro IDE was built using spec-driven development '
                '— requirements, design, and tasks generated and refined before any code is written — '
                'cutting development time by ~50%.'},
     {'t': 3219,
      'title': 'Quality 4: Be an Owner',
      'detail': 'Vogels introduces “verification debt” and “hallucination” as the two main challenges '
                'of AI coding, arguing that vibe coding without ownership is gambling — regulatory and '
                'quality responsibility remains yours.'},
     {'t': 3595,
      'title': 'Mechanisms vs. Good Intentions',
      'detail': 'The Amazon Andon Cord story and S3’s durability reviews demonstrate that mechanisms — '
                'not intentions — convert quality goals into consistent outcomes; code reviews matter '
                'more in an AI-driven world, not less.'},
     {'t': 3916,
      'title': 'Quality 5: Become a Polymath',
      'detail': 'Jim Gray’s T-shaped expertise — deep database mastery plus broad curiosity — enabled '
                'breakthrough work in astronomy; Vogels urges developers to “broaden their T” beyond '
                'single-domain depth.'},
     {'t': 4279,
      'title': 'Summary & Closing: Professional Pride',
      'detail': 'The five Renaissance Developer qualities are recapped, and Vogels closes with a call '
                'to take pride in the invisible craft of building reliable systems — the clean '
                'deployments and overnight uptime that no customer will ever see.'}],

    "TAKEAWAY": (
        "The practical consequence of AI-assisted development that most developers underestimate is "
        "“verification debt”: when the machine writes the code, comprehension must be "
        "rebuilt during review, and that gap — between generation speed and comprehension speed "
        "— is where unvalidated software reaches production. Spec-driven development, as "
        "demonstrated with the Kiro IDE (requirements → design → tasks, all refined before "
        "any code is written), is the most concrete mechanism to close this gap: it front-loads "
        "disambiguation, catches AI hallucinations at the design stage, and in the Kiro team's "
        "own experience cut development time roughly in half compared to vibe coding. The risk is not "
        "AI replacing you; it is developers who treat AI-generated output as finished product, "
        "abdicating ownership of code they do not understand."
    ),

    "DESCRIPTION_SECTION": (
        '<details class="description-details">'
        "<summary>YouTube Description</summary>"
        '<div class="video-description">'
        "Join Amazon.com CTO Dr. Werner Vogels for the definitive developer keynote of 2025. "
        "Software developers and architects will discover how their tools, patterns, and practices "
        "are evolving in an AI-driven world that demands scalable, reliable, and price-performant "
        "solutions. Drawing from AWS's pioneering work, they'll share real-world insights "
        "and architectural principles that are shaping modern development. Learn how AI innovations "
        "are transforming software development and operations within AWS, and how you can embrace "
        "these advances to build better solutions.<br><br>"
        "Learn more about AWS events: "
        '<a href="https://go.aws/events" target="_blank" rel="noopener noreferrer">https://go.aws/events</a><br>'
        " <br>"
        "Subscribe: <br>"
        'More AWS videos: <a href="http://bit.ly/2O3zS75" target="_blank" rel="noopener noreferrer">http://bit.ly/2O3zS75</a> <br>'
        'More AWS events videos: <a href="http://bit.ly/316g9t4" target="_blank" rel="noopener noreferrer">http://bit.ly/316g9t4</a><br><br>'
        "ABOUT AWS<br>"
        "Amazon Web Services (AWS) hosts events, both online and in-person, bringing the cloud "
        "computing community together to connect, collaborate, and learn from AWS experts. "
        "AWS is the world's most comprehensive and broadly adopted cloud platform, offering "
        "over 200 fully featured services from data centers globally. Millions of "
        "customers—including the fastest-growing startups, largest enterprises, and leading "
        "government agencies—are using AWS to lower costs, become more agile, and innovate "
        "faster.<br><br>"
        "#AWSreInvent #AWSEvents"
        "</div>"
        "</details>"
    ),

    "TAGS": ["ai", "cloud", "software architecture", "developer culture"],
    "CHANNEL": "AWS Events",
    "DURATION": "1h 16m",
    "PUBLISH_DATE": "Dec 5 2025",
    "GENERATION_DATE": "2026-03-06",
    "AGENT_MODEL": "claude-opus-4-7",
}
# ─────────────────────────────────────────────────────────────────────────────


def main():
    subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "build_viewer.py"), "--mode", "local"], check=True)
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    template_path = pathlib.Path(TEMPLATE_PATH)
    result = render_from_payload(CONTENT, OUTPUT_PATH, template_path=template_path)
    print(f"OUTPUT_PATH: {result}")


if __name__ == "__main__":
    main()
