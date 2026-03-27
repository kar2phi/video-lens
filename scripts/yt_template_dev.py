#!/usr/bin/env python3
"""
Template dev server for youtube-summarizer.
Edit template.html, run this script, and see the result instantly.

Usage:
    python scripts/yt_template_dev.py
"""
import json
import os
import re

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), '..', 'skills', 'video-lens', 'template.html')
OUTPUT_PATH = os.path.expanduser('~/Downloads/video-lens/reports/video-lens_sample_output.html')

# ── Hardcoded content for https://www.youtube.com/watch?v=3Y1G9najGiI ──────
# AWS re:Invent 2025 — Werner Vogels final keynote

CONTENT = {
    "VIDEO_ID": "3Y1G9najGiI",

    "VIDEO_TITLE": "AWS re:Invent 2025 - Keynote with Dr. Werner Vogels",

    "VIDEO_URL": "https://www.youtube.com/watch?v=3Y1G9najGiI",

    "META_LINE": "AWS Events · 1h 16m · Dec 5 2025 · 13.8M views",

    "SUMMARY": (
        "Werner Vogels uses his final AWS re:Invent keynote &mdash; after 14 consecutive years &mdash; "
        "to argue that today&rsquo;s AI moment is not the end of developers but the start of a new "
        "Renaissance, one that will transform the role rather than eliminate it. He introduces the "
        "&ldquo;Renaissance Developer&rdquo; framework: five qualities &mdash; curiosity, systems "
        "thinking, communication with precision, ownership, and polymathism &mdash; that distinguish "
        "builders who will thrive in an AI-driven world. His most concrete warning is the concept of "
        "&ldquo;verification debt&rdquo;: AI generates code faster than humans can understand it, "
        "creating a gap where quality problems enter production unless deliberate mechanisms like "
        "spec-driven development and code reviews are in place. The keynote closes with an appeal to "
        "professional pride in the invisible craft of keeping reliable systems running."
    ),

    "KEY_POINTS": """
<li><strong>AI will not make developers obsolete &mdash; if they evolve</strong> &mdash; Vogels reframes the keynote&rsquo;s central question from &ldquo;Will AI take my job?&rdquo; to &ldquo;Will AI make me obsolete?&rdquo; and answers: &ldquo;Absolutely not &mdash; if you evolve.&rdquo;
<p>Every generation of developers has faced a wave of change &mdash; compilers, structured programming, object-oriented languages, cloud infrastructure &mdash; and each time the role transformed rather than disappeared. Vogels argues the pattern holds: some tasks will be automated and some skills will become obsolete, but builders who continuously adapt remain essential. His core refrain, repeated throughout the talk, is <em>&ldquo;the work is yours, not that of the tools&rdquo;</em> &mdash; including regulatory and quality responsibility that cannot be offloaded to an AI.</p></li>
<li><strong>The Renaissance Developer framework: five qualities for the AI era</strong> &mdash; Drawing on the 15th-century Renaissance as an analogy for today&rsquo;s convergence of AI, robotics, and space exploration, Vogels proposes five qualities: <strong>curiosity</strong>, <strong>systems thinking</strong>, <strong>precision communication</strong>, <strong>ownership</strong>, and <strong>polymathism</strong>.
<p>The Renaissance analogy is precise: new tools (pencil, microscope, printing press) and cross-disciplinary thinking were inseparable from the era&rsquo;s scientific breakthroughs. Da Vinci worked across painting, engineering, economics, and invention simultaneously. Today&rsquo;s convergence of multiple technological golden ages reinforces each other in the same way. Vogels argues the same mental qualities that made Renaissance scientists effective &mdash; curiosity, bold experimentation, building bridges between fields &mdash; are directly applicable to the challenge of developing software in an AI-assisted world.</p></li>
<li><strong>Curiosity + the Yerkes-Dodson learning curve</strong> &mdash; Real learning happens on the rising slope of the Yerkes-Dodson bell curve, where curiosity meets challenge; too little pressure leads to disengagement, too much to overwhelm.
<p>Vogels uses this psychological law to frame experimentation and failure as essential, not incidental. He draws an analogy to language acquisition: grammar study only takes you so far &mdash; <em>&ldquo;real learning begins where you stumble into a conversation.&rdquo;</em> Software works the same way: the failed build and the broken assumption teach you how a system actually behaves, in ways that documentation cannot. Learning is also social: conferences, user groups, and conversations with other builders are not optional enrichment but a required part of staying sharp.</p></li>
<li><strong>Systems thinking: structure and feedback loops determine behavior</strong> &mdash; Donella Meadows&rsquo; definition: <em>&ldquo;A system is a set of things, interconnected in such a way that they produce their own patterns of behavior over time.&rdquo;</em>
<p>The Yellowstone wolf trophic cascade is Vogels&rsquo; central illustration: removing wolves caused elk to overgraze, rivers to erode, and the entire park ecosystem to degrade &mdash; even though wolves never touched the rivers. Reintroducing them in 2010 reversed the damage. The software lesson: every service, API, queue, and team ownership boundary is part of a larger system with feedback loops. Add a cache and you shift traffic flow; change team ownership and you change delivery pace. <strong>Structure changes, behavior changes; feedback changes, outcome changes.</strong> Meadows&rsquo; paper &ldquo;Leverage Points: Places to Intervene in a System&rdquo; is assigned as homework.</p></li>
<li><strong>Communication with precision: specifications reduce the ambiguity of natural language</strong> &mdash; In AI-assisted coding, developers communicate in natural language (ambiguous) rather than programming languages (precise), making specifications the critical bridge between intent and correct output.
<p>Vogels notes that natural language works for humans because we use tone, context, and shared knowledge to disambiguate. Machines need precision &mdash; which is why programming languages were invented. As AI tools take natural-language prompts, the ambiguity problem re-enters. He references Dijkstra&rsquo;s formal-specification methods and the Apollo Guidance Computer&rsquo;s 145,000-line codebase (guided by meticulous specs) as proof that spec-driven development produces correct, verifiable software. The same principle applies to communicating with a business stakeholder: Werner&rsquo;s &ldquo;Frugal Architect&rdquo; tiering of Amazon&rsquo;s homepage (Tier 1/2/3 by availability requirement) is presented as a communication tool, not just an engineering one.</p></li>
<li><strong>Kiro IDE and spec-driven development: requirements &rarr; design &rarr; tasks before code</strong> &mdash; Clare Liguori&rsquo;s Kiro IDE replaces a single ambiguous vibe-coding prompt with a structured workflow: Kiro generates <strong>requirements, design, and tasks</strong> from the developer&rsquo;s description, which the developer refines before any code is written.
<p>The key insight from building Kiro with Kiro: a prompt like &ldquo;build me a web trivia game&rdquo; has <em>&ldquo;probably a million different possible final outcomes,&rdquo;</em> but only one is what you had in mind. With vibe coding, the AI guesses and you iterate on code; with spec-driven development, you iterate on the spec first. In a production case study (system notifications for the Kiro IDE), the spec workflow surfaced a much larger architectural problem &mdash; building on Electron&rsquo;s native notification API across a 2-million-line codebase &mdash; at the design stage rather than in the code. The feature shipped in roughly half the time of an equivalent vibe-coded approach.</p></li>
<li><strong>Verification debt: AI generates code faster than humans can comprehend it</strong> &mdash; When you write code yourself, comprehension comes with the act of creation; when the machine writes it, you must rebuild that comprehension during review &mdash; a gap Vogels calls <strong>verification debt</strong>.
<p>This gap is one of two main challenges Vogels hears from developers adopting AI tools (the other being hallucination). The practical consequence: code can move toward production before anyone has truly validated what it does. Code reviews therefore become <em>more</em> important in an AI-driven world, not less &mdash; they are the control point where human judgment re-enters the loop. Vogels specifically calls out the knowledge-transfer value of human-to-human reviews: seniors bring pattern recognition and hard-earned judgment, juniors bring fresh eyes, and together they grow the next generation of builders in a way that AI cannot replicate.</p></li>
<li><strong>Mechanisms, not good intentions, ensure quality</strong> &mdash; Everyone at Amazon had good intentions about product quality, but nothing changed until Bezos introduced a <em>mechanism</em>: a button customer-service agents could press to make a product unlisted, triggering automatic alarms.
<p>The Andon Cord story (adapted from Toyota&rsquo;s manufacturing principle: no car leaves the line with a known defect) illustrates that <strong>mechanisms convert good intentions into consistent outcomes</strong>. The S3 team&rsquo;s durability reviews &mdash; pausing any change touching durability to model risks, list threats, and map guardrails &mdash; turn durability from a property of code into an <em>&ldquo;organizational habit.&rdquo;</em> In an AI-driven world, the same logic applies to hallucination and verification debt: good intentions are not enough; you need spec-driven workflows, automated testing pipelines, and mandatory code reviews as structural mechanisms.</p></li>
<li><strong>Become a polymath: T-shaped over I-shaped</strong> &mdash; I-shaped developers are deep in one domain only; T-shaped developers combine that depth with broad cross-disciplinary knowledge that lets them see how their work fits into a larger system.
<p>Jim Gray &mdash; Turing Award winner and inventor of database transactions &mdash; exemplifies the T-shape: he could diagnose a wrong database layout by listening to the rattling of disks for 30 seconds, a <em>&ldquo;sixth sense built from decades of experience.&rdquo;</em> But his curiosity extended far beyond databases to people, business, and other technologies. His work on the Sloan Digital Sky Survey shows how deep database expertise, applied to an entirely different domain (astronomy), was transformative. Vogels&rsquo; advice: develop deep domain expertise, but cultivate the range to connect it to adjacent disciplines &mdash; <em>&ldquo;broaden your T.&rdquo;</em></p></li>
""",

    "OUTLINE": """
<li><a class="ts" data-t="0" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=0" target="_blank">&#9654; 0:00:00</a> &mdash; <span class="outline-title">Opening Cinematic</span><span class="outline-detail">A short film traces recurring &ldquo;end of the developer&rdquo; fears across technology eras &mdash; punch cards, COBOL, cloud &mdash; framing the keynote&rsquo;s central question.</span></li>
<li><a class="ts" data-t="314" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=314" target="_blank">&#9654; 0:05:14</a> &mdash; <span class="outline-title">Werner&rsquo;s Farewell &amp; Central Question</span><span class="outline-detail">Werner announces this is his final re:Invent keynote after 14 years, then addresses the question every customer asks: &ldquo;Will AI make me obsolete?&rdquo;</span></li>
<li><a class="ts" data-t="573" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=573" target="_blank">&#9654; 0:09:33</a> &mdash; <span class="outline-title">History of Developer Evolution</span><span class="outline-detail">From assembly and COBOL to compilers, OOP, microservices, and cloud &mdash; each wave automated tasks and required new skills, and developers adapted every time.</span></li>
<li><a class="ts" data-t="876" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=876" target="_blank">&#9654; 0:14:36</a> &mdash; <span class="outline-title">A New Renaissance</span><span class="outline-detail">Vogels argues that today&rsquo;s convergence of AI, robotics, and space travel mirrors the 15th-century Renaissance, where curiosity, new tools, and cross-disciplinary thinking exploded simultaneously.</span></li>
<li><a class="ts" data-t="1189" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=1189" target="_blank">&#9654; 0:19:49</a> &mdash; <span class="outline-title">Quality 1: Be Curious</span><span class="outline-detail">Curiosity drives learning; the Yerkes-Dodson Law locates peak learning on the rising slope between disengagement and overwhelm, where curiosity meets real challenge.</span></li>
<li><a class="ts" data-t="1510" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=1510" target="_blank">&#9654; 0:25:10</a> &mdash; <span class="outline-title">Learning from the Field: Africa &amp; Latin America</span><span class="outline-detail">Real-world examples from Vogels&rsquo; travels &mdash; Ocean Cleanup&rsquo;s AI river model, Rwanda&rsquo;s health intelligence center, and KOKO Networks&rsquo; ethanol ATMs in Nairobi &mdash; show developers solving humanity&rsquo;s hardest problems.</span></li>
<li><a class="ts" data-t="2000" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=2000" target="_blank">&#9654; 0:33:20</a> &mdash; <span class="outline-title">Quality 2: Think in Systems</span><span class="outline-detail">Donella Meadows&rsquo; systems theory and the Yellowstone wolf trophic cascade illustrate how a single feedback loop can reshape an entire system &mdash; a lesson directly applicable to software architecture.</span></li>
<li><a class="ts" data-t="2284" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=2284" target="_blank">&#9654; 0:38:04</a> &mdash; <span class="outline-title">Quality 3: Communicate with Precision</span><span class="outline-detail">Natural language is ambiguous; specifications reduce that ambiguity, both when communicating with AI tools and when aligning engineering decisions with business stakeholders.</span></li>
<li><a class="ts" data-t="2574" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=2574" target="_blank">&#9654; 0:42:54</a> &mdash; <span class="outline-title">Kiro IDE: Spec-Driven Development Demo</span><span class="outline-detail">Clare Liguori walks through how the Kiro IDE was built using spec-driven development &mdash; requirements, design, and tasks generated and refined before any code is written &mdash; cutting development time by ~50%.</span></li>
<li><a class="ts" data-t="3219" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=3219" target="_blank">&#9654; 0:53:39</a> &mdash; <span class="outline-title">Quality 4: Be an Owner</span><span class="outline-detail">Vogels introduces &ldquo;verification debt&rdquo; and &ldquo;hallucination&rdquo; as the two main challenges of AI coding, arguing that vibe coding without ownership is gambling &mdash; regulatory and quality responsibility remains yours.</span></li>
<li><a class="ts" data-t="3595" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=3595" target="_blank">&#9654; 0:59:55</a> &mdash; <span class="outline-title">Mechanisms vs. Good Intentions</span><span class="outline-detail">The Amazon Andon Cord story and S3&rsquo;s durability reviews demonstrate that mechanisms &mdash; not intentions &mdash; convert quality goals into consistent outcomes; code reviews matter more in an AI-driven world, not less.</span></li>
<li><a class="ts" data-t="3916" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=3916" target="_blank">&#9654; 1:05:16</a> &mdash; <span class="outline-title">Quality 5: Become a Polymath</span><span class="outline-detail">Jim Gray&rsquo;s T-shaped expertise &mdash; deep database mastery plus broad curiosity &mdash; enabled breakthrough work in astronomy; Vogels urges developers to &ldquo;broaden their T&rdquo; beyond single-domain depth.</span></li>
<li><a class="ts" data-t="4279" href="https://www.youtube.com/watch?v=3Y1G9najGiI&t=4279" target="_blank">&#9654; 1:11:19</a> &mdash; <span class="outline-title">Summary &amp; Closing: Professional Pride</span><span class="outline-detail">The five Renaissance Developer qualities are recapped, and Vogels closes with a call to take pride in the invisible craft of building reliable systems &mdash; the clean deployments and overnight uptime that no customer will ever see.</span></li>
""",

    "TAKEAWAY": (
        "The practical consequence of AI-assisted development that most developers underestimate is "
        "&ldquo;verification debt&rdquo;: when the machine writes the code, comprehension must be "
        "rebuilt during review, and that gap &mdash; between generation speed and comprehension speed "
        "&mdash; is where unvalidated software reaches production. Spec-driven development, as "
        "demonstrated with the Kiro IDE (requirements &rarr; design &rarr; tasks, all refined before "
        "any code is written), is the most concrete mechanism to close this gap: it front-loads "
        "disambiguation, catches AI hallucinations at the design stage, and in the Kiro team&rsquo;s "
        "own experience cut development time roughly in half compared to vibe coding. The risk is not "
        "AI replacing you; it is developers who treat AI-generated output as finished product, "
        "abdicating ownership of code they do not understand."
    ),

    "VIDEO_LENS_META": json.dumps({
        "videoId": "3Y1G9najGiI",
        "title": "AWS re:Invent 2025 - Keynote with Dr. Werner Vogels",
        "channel": "AWS Events",
        "duration": "1h 16m",
        "publishDate": "Dec 5 2025",
        "generationDate": "2026-03-06",
        "summary": "Werner Vogels uses his final AWS re:Invent keynote — after 14 consecutive years — to argue that today's AI moment is not the end of developers but the start of a new Renaissance.",
        "tags": ["ai", "cloud", "software architecture", "developer culture"],
        "keywords": ["Renaissance Developer", "verification debt", "systems thinking", "spec-driven development", "polymath"],
        "filename": "reports/video-lens_sample_output.html",
    }),

    "DESCRIPTION_SECTION": (
        '<details class="description-details">'
        "<summary>YouTube Description</summary>"
        '<div class="video-description">'
        "Join Amazon.com CTO Dr. Werner Vogels for the definitive developer keynote of 2025. "
        "Software developers and architects will discover how their tools, patterns, and practices "
        "are evolving in an AI-driven world that demands scalable, reliable, and price-performant "
        "solutions. Drawing from AWS&#x27;s pioneering work, they&#x27;ll share real-world insights "
        "and architectural principles that are shaping modern development. Learn how AI innovations "
        "are transforming software development and operations within AWS, and how you can embrace "
        "these advances to build better solutions.<br><br>"
        "Learn more about AWS events: "
        '<a href="https://go.aws/events" target="_blank" rel="noopener">https://go.aws/events</a><br>'
        " <br>"
        "Subscribe: <br>"
        'More AWS videos: <a href="http://bit.ly/2O3zS75" target="_blank" rel="noopener">http://bit.ly/2O3zS75</a> <br>'
        'More AWS events videos: <a href="http://bit.ly/316g9t4" target="_blank" rel="noopener">http://bit.ly/316g9t4</a><br><br>'
        "ABOUT AWS<br>"
        "Amazon Web Services (AWS) hosts events, both online and in-person, bringing the cloud "
        "computing community together to connect, collaborate, and learn from AWS experts. "
        "AWS is the world&#x27;s most comprehensive and broadly adopted cloud platform, offering "
        "over 200 fully featured services from data centers globally. Millions of "
        "customers\u2014including the fastest-growing startups, largest enterprises, and leading "
        "government agencies\u2014are using AWS to lower costs, become more agile, and innovate "
        "faster.<br><br>"
        "#AWSreInvent #AWSEvents"
        "</div>"
        "</details>"
    ),
}
# ─────────────────────────────────────────────────────────────────────────────


def render():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    for key, value in CONTENT.items():
        html = html.replace("{{" + key + "}}", value)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Rendered → {OUTPUT_PATH}")
    remaining = re.findall(r'\{\{[A-Z_]+\}\}', html)
    if remaining:
        print(f"WARNING: unreplaced template placeholders: {remaining}")
    template_keys = set(re.findall(r'\{\{([A-Z_]+)\}\}', open(TEMPLATE_PATH).read()))
    content_keys = set(CONTENT.keys())
    unused = content_keys - template_keys
    if unused:
        print(f"WARNING: CONTENT keys not in template: {unused}")


if __name__ == "__main__":
    render()
