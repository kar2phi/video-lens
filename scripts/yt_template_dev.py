#!/usr/bin/env python3
"""
Template dev server for youtube-summarizer.
Edit template.html, run this script, and see the result instantly.

Usage:
    python scripts/yt_template_dev.py
"""
import os

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), '..', 'skill', 'template.html')
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), 'sample_output.html')

# ── Hardcoded content for https://www.youtube.com/watch?v=3Y1G9najGiI ──────
# AWS re:Invent 2025 — Werner Vogels final keynote

CONTENT = {
    "VIDEO_ID": "3Y1G9najGiI",

    "VIDEO_TITLE": "AWS re:Invent 2025 - Keynote with Dr. Werner Vogels",

    "VIDEO_URL": "https://www.youtube.com/watch?v=3Y1G9najGiI",

    "META_LINE": "AWS Events · 1h 16m · Dec 4 2025 · 13.8M views",

    "SUMMARY": (
        "In his final re:Invent keynote, Dr. Werner Vogels introduces the &ldquo;Renaissance "
        "Developer&rdquo; framework &mdash; arguing that AI will not make developers obsolete, "
        "but will demand they evolve by cultivating curiosity, systems thinking, precise "
        "communication, ownership, and polymathic breadth. He draws parallels between today&rsquo;s "
        "converging golden ages in AI, robotics, and space travel and the original Renaissance, "
        "where curiosity, new tools, and cross-disciplinary thinking fueled breakthroughs. The "
        "keynote features a live demonstration of spec-driven development in the Kiro IDE by Clare "
        "Liguori, and closes with a call for developers to take pride in the unseen craft of "
        "their work."
    ),

    "ANALYSIS": """
<p><strong>Werner Vogels frames AI not as a threat to developers but as the latest in a long line of transformative tools</strong>, from assembly language and compilers through structured programming, object-oriented design, cloud computing, and modern IDEs. He opens by announcing this will be his final re:Invent keynote &mdash; not because he is leaving Amazon, but because <em>&ldquo;you are owed young, fresh, new voices.&rdquo;</em> He then addresses the question on every developer&rsquo;s mind &mdash; &ldquo;Will AI take my job?&rdquo; &mdash; and reframes it: <strong>AI will not make you obsolete, if you evolve</strong>. The work, he insists, remains yours, not the tool&rsquo;s.</p>
<p><strong>The centrepiece of the talk is the &ldquo;Renaissance Developer&rdquo; framework, built around five qualities.</strong> First, <strong>be curious</strong>: protect the instinct to take things apart, embrace failure as a learning mechanism, and keep learning socially through communities and travel. Second, <strong>think in systems</strong>: drawing on ecologist Donella Meadows and the Yellowstone wolves example, Vogels argues that changing one part of a system cascades unpredictably, so developers must understand feedback loops and leverage points. Third, <strong>communicate with precision</strong>: in an era of natural-language prompts, ambiguity is the enemy, and specifications are the antidote.</p>
<p><strong>Clare Liguori demonstrates the practical expression of precise communication through the Kiro IDE&rsquo;s spec-driven development workflow.</strong> She explains how vibe coding often produces code that doesn&rsquo;t match the developer&rsquo;s intent, because <em>&ldquo;out of a very short prompt, there&rsquo;s probably a million possible different final outcomes.&rdquo;</em> Kiro addresses this by generating requirements, designs, and tasks from a prompt &mdash; giving developers an opportunity to refine what they mean before any code is written. She walks through a real production feature (system notifications) where spec-driven development <strong>shipped the feature in roughly half the time</strong> compared to pure vibe coding.</p>
<p><strong>The final two qualities &mdash; ownership and polymathy &mdash; round out Vogels&rsquo; vision for the modern developer.</strong> On ownership, he warns of <strong>&ldquo;verification debt&rdquo;</strong>: AI generates code faster than humans can comprehend it, creating a dangerous gap before production. He stresses <strong>mechanisms over good intentions</strong>, illustrating with Bezos&rsquo;s Andon Cord story at Amazon and the S3 team&rsquo;s durability reviews. On polymathy, he urges developers to become <em>&ldquo;T-shaped&rdquo;</em> &mdash; deep in one domain but broad enough to see how their work fits the larger system, following the example of Turing Award winner Jim Gray. He closes with a heartfelt tribute to the unseen craft of software engineering: <em>&ldquo;The best builders do things properly, even when nobody&rsquo;s watching.&rdquo;</em></p>
""",

    "KEY_POINTS": """
<li><strong>The &ldquo;Renaissance Developer&rdquo; framework</strong> &mdash; Vogels distils five qualities developers need to thrive alongside AI: curiosity, systems thinking, precise communication, ownership, and polymathic breadth. These mirror the traits that drove breakthroughs during the original Renaissance.</li>
<li><strong>AI will not make developers obsolete &mdash; if they evolve</strong> &mdash; Every generation of developers has faced a wave of change (compilers, OOP, cloud, IDEs). AI is the latest, and the pattern holds: <em>&ldquo;the work is yours, not that of the tools.&rdquo;</em></li>
<li><strong>Spec-driven development reduces ambiguity</strong> &mdash; The Kiro IDE generates requirements, designs, and tasks from natural-language prompts before writing code, giving developers a checkpoint to refine intent. Clare Liguori reports this <strong>halved delivery time</strong> on a real production feature compared to vibe coding alone.</li>
<li><strong>Verification debt is the new technical debt</strong> &mdash; AI produces code faster than humans can understand it, allowing unvalidated software to reach production. Vogels urges more human-to-human code reviews as the critical control point in an AI-driven workflow.</li>
<li><strong>Mechanisms beat good intentions</strong> &mdash; Illustrated by Bezos&rsquo;s Andon Cord story and S3&rsquo;s durability reviews, the principle is that systemic problems persist until a concrete mechanism &mdash; not just awareness &mdash; forces corrective action.</li>
<li><strong>Systems thinking reveals hidden cascades</strong> &mdash; Using Donella Meadows&rsquo; work and the Yellowstone wolves reintroduction, Vogels shows that altering one component (a retry policy, a cache, team ownership) reshapes the behaviour of the entire system. He assigns Meadows&rsquo; <em>&ldquo;Leverage Points&rdquo;</em> paper as homework.</li>
<li><strong>T-shaped developers outperform specialists</strong> &mdash; Deep domain expertise matters, but breadth &mdash; understanding cost, performance, business context &mdash; enables better architectural decisions. Jim Gray exemplified this by diagnosing a database layout flaw simply by <em>listening to the disc drives</em>.</li>
""",

    "OUTLINE": """
<li><a class="ts" data-t="0" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=0" target="_blank">▶ 0:00</a> — <span class="outline-title">Opening Cinematic: Eras of Developers</span><span class="outline-detail">A time-travel skit shows developers from the 1960s punch-card era through cloud computing, each facing the same fear that new tools will make them obsolete.</span></li>
<li><a class="ts" data-t="308" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=308" target="_blank">▶ 5:08</a> — <span class="outline-title">Werner&rsquo;s Final re:Invent Keynote</span><span class="outline-detail">Vogels announces this is his last re:Invent keynote after 14 years, saying he wants younger AWS voices to take the stage.</span></li>
<li><a class="ts" data-t="463" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=463" target="_blank">▶ 7:43</a> — <span class="outline-title">&ldquo;Will AI Take My Job?&rdquo;</span><span class="outline-detail">He reframes the question from job replacement to personal evolution, asserting developers will not become obsolete if they adapt.</span></li>
<li><a class="ts" data-t="562" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=562" target="_blank">▶ 9:22</a> — <span class="outline-title">History of Developer Tool Evolution</span><span class="outline-detail">A walk through compilers, structured programming, C++, microservices, cloud, and IDEs shows that tools have always transformed &mdash; and developers have always adapted.</span></li>
<li><a class="ts" data-t="932" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=932" target="_blank">▶ 15:32</a> — <span class="outline-title">The Renaissance Parallel</span><span class="outline-detail">Vogels compares today&rsquo;s converging golden ages in AI, robotics, and space to the Renaissance, where curiosity and new tools like the printing press drove breakthroughs.</span></li>
<li><a class="ts" data-t="1198" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=1198" target="_blank">▶ 19:58</a> — <span class="outline-title">Quality 1: Be Curious</span><span class="outline-detail">Curiosity, willingness to fail, and social learning are presented as the foundation &mdash; with the Yerkes-Dodson stress curve illustrating the optimal learning zone.</span></li>
<li><a class="ts" data-t="1470" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=1470" target="_blank">▶ 24:30</a> — <span class="outline-title">Learning from Global Customers</span><span class="outline-detail">Stories from Africa and Latin America showcase developers solving real-world problems &mdash; from Ocean Cleanup&rsquo;s AI river models to Rwanda&rsquo;s data-driven healthcare and KOKO Networks&rsquo; micro-fuel dispensers.</span></li>
<li><a class="ts" data-t="2025" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=2025" target="_blank">▶ 33:45</a> — <span class="outline-title">Quality 2: Think in Systems</span><span class="outline-detail">Drawing on Donella Meadows and the Yellowstone wolves reintroduction, Vogels explains how feedback loops and trophic cascades apply directly to distributed software architecture.</span></li>
<li><a class="ts" data-t="2284" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=2284" target="_blank">▶ 38:04</a> — <span class="outline-title">Quality 3: Communicate with Precision</span><span class="outline-detail">Using Amazon&rsquo;s tier-based availability model and the ambiguity of natural language, Vogels argues specifications are essential for reducing miscommunication with both humans and AI.</span></li>
<li><a class="ts" data-t="2558" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=2558" target="_blank">▶ 42:38</a> — <span class="outline-title">Clare Liguori: Kiro IDE &amp; Spec-Driven Dev</span><span class="outline-detail">Clare demonstrates how Kiro&rsquo;s spec-driven workflow &mdash; requirements, designs, tasks &mdash; halved feature delivery time compared to vibe coding by letting developers refine intent before code generation.</span></li>
<li><a class="ts" data-t="3308" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=3308" target="_blank">▶ 55:08</a> — <span class="outline-title">Quality 4: Own Your Software Quality</span><span class="outline-detail">Vogels introduces &ldquo;verification debt,&rdquo; warns against treating vibe coding as gambling, and stresses that regulatory responsibility remains with the developer, not the AI.</span></li>
<li><a class="ts" data-t="3560" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=3560" target="_blank">▶ 59:20</a> — <span class="outline-title">Mechanisms Over Good Intentions</span><span class="outline-detail">The Bezos Andon Cord story and S3 durability reviews illustrate that systemic quality requires concrete mechanisms, not just awareness &mdash; especially as AI accelerates code production.</span></li>
<li><a class="ts" data-t="3929" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=3929" target="_blank">▶ 1:05:29</a> — <span class="outline-title">Quality 5: Become a Polymath</span><span class="outline-detail">Using Jim Gray&rsquo;s career as the exemplar, Vogels urges developers to become T-shaped &mdash; deep in one domain but broad enough to see cross-cutting trade-offs.</span></li>
<li><a class="ts" data-t="4312" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=4312" target="_blank">▶ 1:11:52</a> — <span class="outline-title">Closing: Pride in Unseen Craft</span><span class="outline-detail">Vogels ends with an emotional tribute to the invisible work of software engineering &mdash; clean deployments, silent rollbacks &mdash; and signs off with &ldquo;Werner out.&rdquo;</span></li>
""",

    "TAKEAWAY": (
        "AI is transforming the developer&rsquo;s toolkit, not replacing the developer &mdash; "
        "but only those who actively evolve will thrive. Cultivate curiosity, think in systems, "
        "communicate with precision through specifications, own the quality of what you ship, "
        "and broaden your expertise beyond a single domain."
    ),
}
# ─────────────────────────────────────────────────────────────────────────────


def render():
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    for key, value in CONTENT.items():
        html = html.replace("{{" + key + "}}", value)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Rendered → {OUTPUT_PATH}")


if __name__ == "__main__":
    render()
