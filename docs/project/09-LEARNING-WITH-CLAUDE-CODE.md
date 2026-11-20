# Learning While Building with Claude Code and Obsidian

## 1. Purpose

Claude Code will handle much of the implementation work. Obsidian will become the project's **learning and engineering knowledge base**. The goal is to build quickly without becoming dependent on AI or turning every coding task into a long tutorial.

Use a lightweight loop:

**Build → inspect → understand → verify → capture only what is worth remembering.**

This is not a plan to study every technology before coding. Learn concepts just before they become useful, deepen understanding for important algorithms, and keep concise notes that make future sessions easier.

## 2. What Obsidian is—and what it is not

Obsidian is a local knowledge workspace. A vault is simply a folder containing Markdown files. Notes remain plain text files on your computer, can be edited by other tools such as Claude Code, and can be version-controlled with Git. Obsidian adds useful navigation and knowledge-management features on top: internal links, backlinks, graph view, templates, properties and Bases.

For this project:

- **The source code is the implementation truth.** The repository, tests and Git history show what the software actually does.
- **The project specifications are the product truth.** The PRD, requirements, architecture and roadmap record what we intend to build.
- **The Obsidian knowledge notes are the learning layer.** They explain concepts, decisions, data flow, algorithms, examples and things you personally understand or need to revisit.

Do not copy every source file into notes. Do not dump every Claude conversation into the vault and assume that this creates understanding. The value comes from concise, linked explanations that you can revisit and use.

Obsidian is not itself an AI tutor and opening a vault does not automatically teach you or consume Claude tokens. Claude Code only spends context on vault files when it reads them or when you include them in a task.

## 3. Recommended setup: one project repository, opened as an Obsidian vault

**Recommendation:** when the code repository is created, open the repository's root folder as the Obsidian vault. This keeps code, project specifications and learning notes in one Git-controlled workspace. Claude Code is already operating in the same folder, so no special plugin or API bridge is needed.

Obsidian supports this because a vault is an ordinary local folder of Markdown files. It automatically notices changes made by external editors.

Suggested layout (adapt it to the actual repository when created):

```text
architectural-reconstruction/
├── CLAUDE.md
├── README.md
├── frontend/
├── backend/
├── tests/
├── docs/
│   ├── project/                 # The eight project/specification documents
│   ├── learning/
│   │   ├── Learning Dashboard.md
│   │   ├── Learning Log.md
│   │   ├── Project Map.md
│   │   ├── Glossary.md
│   │   ├── concepts/
│   │   ├── walkthroughs/
│   │   └── templates/
│   ├── architecture/
│   │   └── decisions/
│   └── references/
└── .gitignore
```

Keep the existing nine planning documents as the project's formal documentation. Place or copy them into `docs/project/` when the repository is initialized; do not maintain two independently edited copies. The ninth document (this one) governs the learning workflow.

If the repository becomes too cluttered in Obsidian, use Obsidian's file-exclusion and search settings to reduce noise. Do not create a vault inside another vault. A separate sibling vault is possible, but it introduces duplicated files or cross-folder access and is not the simplest starting point.

## 4. Initial Obsidian setup

1. Install Obsidian from [obsidian.md](https://obsidian.md/).
2. Create the code repository first, or wait until its root folder exists.
3. In Obsidian, choose **Open folder as vault** and select the repository root.
4. Enable only the useful built-in features at first:
   - **Backlinks** and **Outgoing links** to follow relationships between concepts and decisions.
   - **Templates** to create consistent concept and walkthrough notes.
   - **Graph view** when you want to inspect how concepts connect; it is optional, not a measure of learning.
   - **Properties view** for note metadata.
   - **Bases** later, if you want a filtered table of concepts by status or confidence.
5. Create the `docs/learning/` folders shown above.
6. Create the initial notes: `Learning Dashboard.md`, `Learning Log.md`, `Project Map.md` and `Glossary.md`.
7. Commit the documentation and vault structure to Git. Add machine-specific workspace state and sensitive local files to `.gitignore` as appropriate.

Start with core features only. Community plugins are optional and should not be installed just because a tutorial recommends them. They add maintenance and security considerations without being necessary for this workflow.

## 5. How Claude Code and Obsidian work together

### Simplest and recommended integration

Run Claude Code from the project repository root, the same folder opened as the Obsidian vault:

```bash
cd path/to/architectural-reconstruction
claude
```

Claude Code can read and edit the Markdown files in the repository directly. Obsidian will reflect those edits. No Obsidian plugin, MCP server, paid API or special synchronisation layer is required.

Keep a short root `CLAUDE.md` with stable project instructions. It should tell Claude where the project documents and learning notes live, how to update them, and when not to create notes. It should not contain the full contents of every document.

### Optional integrations—not part of the MVP learning setup

There are community plugins that expose Claude Code sessions or tools inside Obsidian. They can be explored later, but they are not required. Some plugins run local processes, access files or send selected note content to an AI service. Review permissions, code, maintainer activity and data handling before installing any community plugin. Do not install an AI plugin just to avoid opening a terminal.

For now, the terminal-based Claude Code workflow is simpler, easier to audit and has fewer moving parts.

## 6. The knowledge system: what goes into the vault

Keep the system small. Create a note only when it will be useful again.

| Note | Purpose | When to update |
|---|---|---|
| `Learning Dashboard.md` | Current milestone, what you are learning now, next checkpoint | At milestone changes |
| `Learning Log.md` | Short record of durable learning and unresolved questions | After a meaningful learning checkpoint |
| `Project Map.md` | Main modules and how data travels through the system | When architecture or major data flow changes |
| `Glossary.md` | Short definitions of recurring technical and architectural terms | When a new term becomes important |
| Concept notes | Explain one concept, with a project-specific example | When a concept is foundational or confusing |
| Walkthrough notes | Trace one real input through code, step by step | For important algorithms and end-to-end flows |
| Architecture decisions | Record a decision, alternatives and reason | When a consequential decision is made |
| Reference notes | Link to useful official docs and record what part matters | When an external reference is actually used |

### Suggested note metadata

Use a small amount of YAML frontmatter so notes can be searched and filtered. Example:

```yaml
---
type: concept
status: learning
confidence: needs-revisit
created: 2026-11-19
tags:
  - geometry
  - dxf
---
```

Use Obsidian wikilinks such as `[[Coordinate Systems]]` and `[[Project Map]]` to connect notes. Link only where the relationship is meaningful. Avoid building an elaborate taxonomy before there is enough content to justify it.

### What a good concept note contains

- **In one sentence:** the idea in plain language.
- **Why this matters here:** where it appears in this project.
- **Mental model:** a small diagram, analogy or explanation.
- **Concrete example:** one actual project input or code example.
- **Common mistake:** what can go wrong or be misunderstood.
- **Related notes:** links to relevant concepts, code walkthroughs or decisions.
- **Confidence:** understood, partial, or revisit.

A good note should help you explain or use the concept later. It should not be a textbook chapter.

## 7. The efficient learning loop

### Before a coding task

Give Claude one specific outcome and acceptance criteria. Ask it to inspect only the relevant files and one relevant specification. For unfamiliar or multi-file work, ask for a short plan before editing.

### During implementation

Let Claude implement a small, testable vertical slice. Do not ask it to narrate every keystroke or explain obvious syntax. Ask it to flag important assumptions, new dependencies and design choices before they become difficult to reverse.

### After implementation

Ask for a concise teaching summary:

1. What changed and why?
2. What is the input → processing → output flow?
3. Which one or two functions are most important to inspect?
4. What assumptions or edge cases matter?
5. Which tests were actually run and what did they establish?
6. Is there one concept worth adding to Obsidian?

Inspect the Git diff and run the tests yourself. For geometry, inspect numerical measurements as well as the rendered result.

### The teach-back checkpoint

Explain the component in your own words, or trace one example through it. If you cannot, ask Claude about the exact step that is unclear. Then either:

- add a short concept or walkthrough note if the learning will be useful later; or
- leave it unrecorded if it was routine and unlikely to matter again.

Do not create a note after every code edit. A useful note is a distilled explanation, not a transcript.

## 8. Three levels of explanation

| Level | Use it for | Ask Claude for |
|---|---|---|
| **1 — Quick** | UI wiring, routine configuration, small fixes | Responsibility, changed files, behaviour and tests in a few bullets |
| **2 — Logic walkthrough** | API flow, data models, parser stages, state management | Input → steps → output, key functions, assumptions and one example |
| **3 — Deep dive** | Geometry algorithms, coordinate systems, topology, provenance, validation, security | Step-by-step explanation, worked example, edge cases, alternatives and tests |

Use Level 3 for the core engineering ideas—not for every library call. Understand how the project uses ezdxf, Shapely or Three.js; do not try to master each library's entire internals before making progress.

## 9. Token and time efficiency rules

1. **Do not load the whole vault by default.** Ask Claude to read only the relevant specification, source files and learning note.
2. Keep `CLAUDE.md` short. Put detailed knowledge in linked notes and read it only when needed.
3. Do not ask for a full project recap at the start of every session. Use `Project Map.md` and the current milestone note.
4. Do not request line-by-line explanations unless you are debugging or studying a specific function.
5. Do not create a learning note for every session. Update the log only when there is durable learning, a changed mental model or an unresolved question worth revisiting.
6. Ask Claude to update existing notes rather than create duplicate notes about the same concept.
7. Prefer one concrete example and a test over several paragraphs of abstract explanation.
8. Avoid unnecessary subagents for routine coding. Use them only when work is genuinely independent or an isolated review is valuable.
9. Avoid installing Obsidian AI plugins, MCP bridges or transcript-sync tools during the initial setup. They are not needed and may add extra context, permissions or maintenance.
10. Keep Git commits small and meaningful. Git history is the change record; the learning log is the understanding record.
11. Check Claude Code's `/usage` command when available and consult the current account usage/billing view. A vault does not consume tokens merely by existing; context is consumed when Claude reads or processes its contents.

## 10. Suggested root `CLAUDE.md` instructions

Use a concise version of this policy in the repository's root `CLAUDE.md`:

```text
## Learn-as-you-build
- The developer wants to understand the system while Claude Code handles implementation.
- Work in small, testable vertical slices. Avoid unrelated refactors and dependencies.
- For multi-file or unfamiliar algorithmic work, give a short plan before editing.
- After implementation, summarise: what changed, key input-to-output flow, important assumptions, tests run, and at most two concepts worth understanding.
- Do not explain every line or obvious syntax unless asked.
- Use deeper walkthroughs for geometry, coordinate systems, data modelling, validation, provenance, security and core algorithms.
- Read only the relevant project document and learning note. Do not load the entire vault by default.
- Update docs/learning only when a durable concept, project-map change, decision or unresolved question merits it. Do not create a note after every task.
- Prefer updating an existing note over creating a duplicate.
- When writing a learning note, use plain language, one project-specific example and links to related notes.
- Never claim tests passed unless they were actually run. Never weaken tests to hide a bug.
- Preserve verified dimensions and provenance. Never silently invent measurements.
```

## 11. Reusable prompts

### A. Plan a task

```text
I want to complete this task: [specific outcome].

Inspect only the files and documentation needed. Do not edit anything yet.
Return a concise plan, likely files, assumptions or decisions needed from me, and tests that will demonstrate success. Explain unfamiliar concepts only where they affect the design.
```

### B. Implement and teach efficiently

```text
Implement the agreed task only. Keep the change small, avoid unrelated refactors and add or update relevant tests.

After implementation, give me:
- what changed;
- the key input → processing → output flow;
- the 1–2 functions or concepts I should inspect;
- important assumptions or edge cases;
- tests actually run and results.

Do not explain every line. Check whether this task produced durable learning worth adding to an existing Obsidian note. If yes, suggest the exact note to update and make a concise update; do not create a new note without a clear reason.
```

### C. Deep-dive one concept

```text
Teach me [specific concept] using this project's actual code and data.
Start with a plain-language mental model, then trace one concrete example through the relevant functions. Explain important syntax only where needed. Cover assumptions, edge cases and how the tests verify the behaviour.
Do not modify code. At the end, give me a short note-sized summary suitable for the relevant Obsidian concept note.
```

### D. Debug and learn

```text
Here is the failure and how to reproduce it: [details].
Trace the failure to its source. Explain the underlying concept briefly, propose the smallest correct fix, implement it only after the cause is clear, and run relevant tests. Do not change tests merely to hide the failure. Tell me what this bug teaches us and whether an existing learning note should be updated.
```

### E. End a session

```text
Summarise only the durable state needed for the next session: current milestone, completed work, changed modules, test status, unresolved issues and the single best next task.
Update Project Map or Learning Log only if a durable change or learning occurred. Do not create a transcript or repeat the whole conversation.
```

## 12. Learning sequence for this project

| Project milestone | Concepts to learn alongside implementation |
|---|---|
| Repository setup | Git, package managers, virtual environments, frontend/backend separation, HTTP basics |
| DXF inspection | CAD drawing concepts, DXF entities, layers, blocks, units and coordinate systems |
| Canonical model | Data modelling, schemas, identifiers, provenance and serialisation |
| 2D geometry | Vectors, line segments, polylines, polygons, intersections, offsets, tolerances and numerical precision |
| 3D generation | Extrusion, vertices, faces, normals, meshes, transforms and GLB |
| API integration | REST, request/response schemas, validation, error handling and file uploads |
| Three.js viewer | Scene graph, camera, controls, transforms, raycasting and object selection |
| Persistence/deployment | PostgreSQL, authentication, object storage, environment variables, CORS and deployment limits |
| Benchmarking | Test design, profiling, reproducibility, performance metrics and error analysis |

Do not front-load a full course on CAD, computer graphics or backend engineering. Learn what the current milestone requires, then deepen the concept when the implementation gives you a reason.

## 13. Pacing: keep building moving

Use these as rough review budgets, not mandatory study sessions:

- Routine task: 2–5 minutes to read the summary, inspect the diff and run the check.
- Medium task: 5–15 minutes to trace the important path and understand the changed behaviour.
- Core algorithm or architecture: 15–30 minutes for a focused explanation, worked example and small experiment.

If understanding a core topic requires longer, split it into a separate focused learning task—but do not stop all implementation to study unrelated theory. Build speed and learning speed should support each other.

## 14. Comprehension checkpoints

At the end of each major module, you should be able to do these without asking Claude to answer for you:

- **Parser:** explain how one DXF entity becomes one canonical element.
- **Canonical model:** explain how units, IDs and provenance are represented.
- **Geometry:** reason through one simple wall's dimensions and extrusion.
- **Validation:** explain why an issue is a warning or a blocking error.
- **API:** trace one upload request from browser to backend response.
- **Viewer:** explain how model geometry, camera and selected-object metadata relate.
- **Deployment:** identify where the database, files, secrets and processing service live.

If a checkpoint fails, revisit that component and update the relevant note. Do not reread the entire vault.

## 15. Security, accuracy and maintenance

- Treat Claude-generated explanations as drafts. Verify them against code, tests and authoritative documentation before marking a concept as understood.
- Do not let Claude silently overwrite your own notes or delete/rename large note groups. Review diffs like code changes.
- Keep secrets, API keys, private drawings and personal data out of learning notes and Git.
- Review community plugins before installing them. Start without community plugins.
- Back up the repository. Git is the baseline version history; it is not a substitute for a separate backup of important work.
- For geometry, inspect both numeric measurements and visual output. Do not accept a visually plausible model as proof of geometric correctness.
- Record unresolved assumptions rather than converting them into facts.

## 16. Cost

Obsidian's core application is free. A vault is stored locally and does not require an Obsidian account. Obsidian Sync and Publish are optional paid add-ons; they are not required for this project. Use Git and an independent backup for the initial workflow. If you later want cross-device syncing, compare Sync with a carefully configured Git or cloud-storage workflow before paying for anything.

Claude Code usage is separate. Obsidian itself does not grant Claude additional usage, and the existence of Markdown notes does not consume Claude tokens. Tokens are used when Claude reads, reasons over or edits content. The selective-reading rules above are therefore important.

## 17. Official references

- [Obsidian: How data is stored](https://obsidian.md/help/data-storage) — vaults are local folders containing Markdown files and can be edited externally.
- [Obsidian: Internal links](https://obsidian.md/help/links) — link notes and maintain relationships.
- [Obsidian: Properties](https://obsidian.md/help/properties) — metadata stored as YAML frontmatter.
- [Obsidian: Bases](https://obsidian.md/help/bases) — optional database-like views over notes and properties.
- [Obsidian: Core plugins](https://obsidian.md/help/Plugins/Core%20plugins) — built-in features such as Backlinks, Graph view and Templates.
- [Obsidian: Pricing](https://obsidian.md/pricing) — free core application and optional Sync/Publish services.
- [Claude Code: Memory](https://code.claude.com/docs/en/memory) — project instructions and memory.
- [Claude Code: Common workflows](https://code.claude.com/docs/en/common-workflows) — exploring code, planning, editing and testing.
- [Claude Code: Costs](https://code.claude.com/docs/en/costs) — usage and cost management.

Community plugin examples are deliberately not part of the recommended setup. If reconsidered later, evaluate them individually rather than treating a plugin as a required part of Obsidian.

---

**Working principle:** Claude Code should accelerate implementation; Obsidian should preserve the understanding you earn. You remain responsible for verifying the code and being able to explain the system.
