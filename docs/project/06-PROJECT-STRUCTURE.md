# Project Structure

## 1. Recommended repository shape

Use a small monorepo so frontend and backend live together while retaining clear runtime boundaries.

```text
architectural-reconstruction/
├── CLAUDE.md
├── README.md
├── .gitignore
├── .env.example
├── docs/
│   ├── product/
│   │   ├── PRD.md
│   │   ├── MVP_SCOPE.md
│   │   └── FUNCTIONAL_REQUIREMENTS.md
│   ├── architecture/
│   │   ├── TECHNICAL_ARCHITECTURE.md
│   │   ├── PROJECT_STRUCTURE.md
│   │   └── adr/
│   ├── planning/
│   │   ├── DEVELOPMENT_ROADMAP.md
│   │   └── INPUT_CONSTRAINTS_AND_BENCHMARK_PLAN.md
│   └── learning/
│       ├── LEARNING_WITH_CLAUDE_CODE.md
│       ├── LEARNING_LOG.md
│       ├── PROJECT_MAP.md
│       └── GLOSSARY.md
├── apps/
│   └── web/
│       ├── package.json
│       ├── next.config.*
│       ├── src/
│       │   ├── app/
│       │   ├── components/
│       │   ├── features/
│       │   │   ├── upload/
│       │   │   ├── interpretation/
│       │   │   ├── verification/
│       │   │   └── viewer/
│       │   ├── lib/
│       │   └── types/
│       └── tests/
├── services/
│   └── api/
│       ├── pyproject.toml
│       ├── app/
│       │   ├── main.py
│       │   ├── api/
│       │   ├── core/
│       │   ├── schemas/
│       │   ├── services/
│       │   └── workers/          # add only when async processing is needed
│       └── tests/
├── packages/
│   └── building-schema/
│       ├── README.md
│       ├── schema/
│       └── examples/
├── fixtures/
│   ├── input/
│   ├── expected/
│   └── LICENCES.md
├── scripts/
│   ├── dev.*
│   └── benchmark.*
└── .github/
    └── workflows/
```

This is a target structure, not a demand to create every directory on day one. Start with the smallest set of files needed for the first parser test and add folders when responsibilities become real.

## 2. Frontend responsibilities

`apps/web` owns:

- upload and project user interface;
- interpretation / correction forms;
- API client and request state;
- Three.js viewer and camera controls;
- selected-element inspection panel;
- display of validation reports and provenance.

It must not duplicate architectural parsing or geometry-generation rules. The backend's canonical model is the source of truth.

## 3. Backend responsibilities

`services/api/app/api/` contains HTTP route handlers only. Keep request parsing and response mapping here; do not put all geometry logic into route files.

`services/api/app/schemas/` contains API request / response schemas.

`services/api/app/services/` contains application workflows such as upload processing, project management and generation orchestration.

`services/api/app/core/` contains configuration, logging, error types and shared infrastructure.

As the backend grows, separate the domain engine into focused modules such as:

```text
services/api/app/engine/
├── adapters/
│   └── dxf/
├── canonical/
├── validation/
├── geometry2d/
├── geometry3d/
└── exporters/
```

Do not create all of these empty directories before they are needed. The key separation is conceptual: adapters translate formats; canonical models describe architecture; validators check; geometry modules generate; exporters serialise.

## 4. Shared canonical schema

The canonical schema is the contract between backend processing, API responses and the viewer. Keep it versioned and documented.

It should define:

- coordinate system and units;
- project / building / floor identity;
- element types and geometry variants;
- element identifiers;
- measurement values and their source / provenance;
- source drawing references;
- issue severity and uncertainty;
- model-to-metadata identity mapping.

The first implementation can use Python models and JSON examples. Add a formal cross-language schema only when the frontend needs to validate the same payload independently.

## 5. Test and fixture structure

- `fixtures/input/`: legally usable sample DXF files.
- `fixtures/expected/`: expected entity inventories and canonical outputs.
- `fixtures/LICENCES.md`: source, licence / permission and any attribution for every fixture.
- backend unit tests: DXF parsing, geometry and validation.
- backend integration tests: parser → canonical model → geometry → export.
- frontend tests: upload states, interpretation displays and viewer interactions.
- end-to-end tests: one complete happy path and representative failure paths.

Never assume that a file found online is free to redistribute. Use public-domain, explicitly open-licensed or permissioned samples and record provenance.

## 6. Environment files

- `.env.example` contains variable names and placeholder values only.
- Local `.env` files are ignored by Git.
- Vercel / Render / Supabase credentials are stored in deployment secret settings.
- Keep frontend-public variables separate from backend secrets. Never expose service-role keys in browser code.

## 7. Project instructions for Claude Code

Keep root `CLAUDE.md` concise because it is loaded as persistent context. It should include:

- project objective and current milestone;
- core architectural boundaries;
- coding / testing commands;
- the learning workflow (short explanation after implementation; deeper walkthrough only for core logic);
- rules against unrelated refactors and unnecessary dependencies;
- instruction to consult only the relevant document when a task needs more detail.

Do not paste the full PRD, architecture and learning guide into `CLAUDE.md`. Keep detailed material in `docs/` and ask Claude Code to read the one relevant file for a task.
