# FloodOps

> **Urban Flood Nowcasting & Safe-Route System**

FloodOps is an urban flood intelligence platform designed around a complete decision-support pipeline:

**Rainfall / Nowcast → Terrain → Surface Water Movement → Drainage Network → Hydraulic Simulation → Street-Level Flood Depth → Flood-Aware Routing → GIS Dashboard**

The project is being developed around **SIH 2026 Problem Statement 26085** and focuses on turning short-horizon rainfall information into actionable urban flood intelligence, with particular emphasis on drainage overflow, street-level flood depth, and safer route selection.

> **Repository status:** Private during the development/submission phase. The repository is intended to be made public after the relevant submission stage so judges, evaluators, and other reviewers can inspect the implementation and documentation.

---

## Table of Contents

- [1. Project Overview](#1-project-overview)
- [2. Problem](#2-problem)
- [3. Proposed Solution](#3-proposed-solution)
- [4. Core Objective](#4-core-objective)
- [5. Key Capabilities](#5-key-capabilities)
- [6. End-to-End System Flow](#6-end-to-end-system-flow)
- [7. System Architecture](#7-system-architecture)
- [8. Core Modules](#8-core-modules)
- [9. Rainfall Nowcasting](#9-rainfall-nowcasting)
- [10. Terrain and DEM Processing](#10-terrain-and-dem-processing)
- [11. Surface Water Modelling](#11-surface-water-modelling)
- [12. Drainage Network](#12-drainage-network)
- [13. Hydraulic Simulation](#13-hydraulic-simulation)
- [14. Flood Depth Generation](#14-flood-depth-generation)
- [15. Flood-Safe Routing](#15-flood-safe-routing)
- [16. GIS Dashboard](#16-gis-dashboard)
- [17. Prototype Scope](#17-prototype-scope)
- [18. Demo Strategy](#18-demo-strategy)
- [19. Technology Stack](#19-technology-stack)
- [20. Repository Structure](#20-repository-structure)
- [21. Data Flow](#21-data-flow)
- [22. Inputs](#22-inputs)
- [23. Outputs](#23-outputs)
- [24. Backend Architecture](#24-backend-architecture)
- [25. Frontend Architecture](#25-frontend-architecture)
- [26. API Responsibilities](#26-api-responsibilities)
- [27. Installation](#27-installation)
- [28. Environment Configuration](#28-environment-configuration)
- [29. Running the Project](#29-running-the-project)
- [30. Running the Simulation Pipeline](#30-running-the-simulation-pipeline)
- [31. Development Workflow](#31-development-workflow)
- [32. Git and Team Workflow](#32-git-and-team-workflow)
- [33. Testing and Validation](#33-testing-and-validation)
- [34. Validation Strategy](#34-validation-strategy)
- [35. Known Limitations](#35-known-limitations)
- [36. Fallback Strategy](#36-fallback-strategy)
- [37. Security and Reliability Considerations](#37-security-and-reliability-considerations)
- [38. Reproducibility](#38-reproducibility)
- [39. Project Roadmap](#39-project-roadmap)
- [40. Current Status](#40-current-status)
- [41. Demo / Screenshots](#41-demo--screenshots)
- [42. Research and References](#42-research-and-references)
- [43. Team](#43-team)
- [44. License](#44-license)
- [45. Disclaimer](#45-disclaimer)

---

# 1. Project Overview

FloodOps is conceived as a **short-horizon urban flood nowcasting and safe-route decision-support system**.

The system connects several traditionally separate layers of urban flood analysis into one workflow:

1. Observe or obtain rainfall information.
2. Produce a short-horizon rainfall nowcast.
3. Project rainfall onto the urban terrain.
4. Model surface water movement/runoff.
5. Represent the stormwater drainage network.
6. Simulate drainage behaviour and potential overflow.
7. Convert model results into street-level flood depth.
8. Identify roads affected by flooding.
9. Generate a safer route that avoids hazardous road segments.
10. Present the evolving situation through a GIS-oriented dashboard.

The project's central idea is not simply to display rainfall or historical flood maps.

The objective is to build a connected chain from:

> **incoming rainfall information → physical urban response → actionable route intelligence**

---

# 2. Problem

Urban flooding can become dangerous within a short period of time because rainfall interacts with:

- terrain,
- surface flow paths,
- impervious urban areas,
- stormwater infrastructure,
- drainage capacity,
- road networks,
- and local accumulation points.

A rainfall value alone does not tell a commuter which road will become unsafe.

Likewise, a static flood map may not communicate how conditions are expected to evolve during the next few hours.

A useful urban flood system therefore needs to connect:

**rainfall prediction + terrain + drainage + flood depth + road-level decision making**

within a single workflow.

---

# 3. Proposed Solution

FloodOps combines geospatial processing, short-horizon rainfall nowcasting, surface-flow reasoning, drainage-network simulation, and flood-aware routing.

The system is intended to provide:

- a **0–3 hour rainfall outlook**,
- terrain-aware flood propagation,
- drainage-network overflow information,
- street-level water depth,
- time-aware flood visualization,
- and flood-safe route recommendations.

The architecture is intentionally modular so that individual data sources and modelling components can be improved independently.

---

# 4. Core Objective

The primary objective is to answer a practical question:

> **Given current/forecast rainfall and an urban area, which roads are likely to become hazardous over the next few hours, and what safer route can be used instead?**

FloodOps therefore prioritizes an end-to-end chain rather than isolated prediction outputs.

---

# 5. Key Capabilities

## 5.1 Rainfall Nowcasting

Generate a short-horizon rainfall forecast covering approximately **0–3 hours**.

## 5.2 Terrain-Aware Flood Modelling

Use digital elevation information to reason about how rainfall-driven surface water can move and accumulate.

## 5.3 Drainage Network Modelling

Represent urban drainage as a network of nodes and links and account for potential capacity constraints and overflow.

## 5.4 Hydraulic Simulation

Use **SWMM / PySWMM** for drainage-system simulation and time-dependent hydraulic behaviour.

## 5.5 Street-Level Flood Depth

Transform model output into road-level or street-level flood depth information, represented in centimetres where the available modelling supports it.

## 5.6 Time-Aware GIS Visualization

Provide a map experience in which the user can inspect flooding across the **0–3 hour horizon** using a time slider or equivalent temporal control.

## 5.7 Flood-Safe Routing

Use flood information as a routing constraint so that roads with unacceptable flood conditions can be avoided.

## 5.8 Decision-Oriented Dashboard

Bring the system into a single interface rather than requiring a user to interpret multiple disconnected modelling tools.

---

# 6. End-to-End System Flow

```text
Rainfall Observation / Input
            │
            ▼
     Rainfall Nowcasting
        (0–3 hours)
            │
            ▼
     Terrain / DEM Layer
            │
            ▼
 Surface Water / Runoff Model
            │
            ├───────────────┐
            │               │
            ▼               ▼
      Road Network     Drainage Graph
                            │
                            ▼
                       SWMM / PySWMM
                            │
                            ▼
                     Overflow / Depth
                            │
            ┌───────────────┘
            ▼
      Flood Depth Layer
            │
            ▼
     Flooded Road Segments
            │
            ▼
     Flood-Aware Routing
            │
            ▼
      GIS Dashboard / API
```

---

# 7. System Architecture

The system can be viewed as six logical layers.

## Layer 1 — Data

Responsible for:

- rainfall inputs,
- terrain/DEM,
- road network,
- drainage representation,
- supporting geographic datasets,
- storm/event metadata.

## Layer 2 — Prediction

Responsible for:

- rainfall nowcasting,
- forecast time steps,
- storm progression.

## Layer 3 — Physical / Hydraulic Modelling

Responsible for:

- terrain-aware surface response,
- runoff reasoning,
- drainage-network simulation,
- overflow behaviour,
- water-depth generation.

## Layer 4 — Spatial Intelligence

Responsible for:

- mapping,
- spatial joins,
- road/flood intersection,
- converting simulation results into usable geographic layers.

## Layer 5 — Routing

Responsible for:

- road graph construction,
- flooded-road avoidance,
- route scoring,
- safe/safer path selection.

## Layer 6 — Presentation

Responsible for:

- GIS dashboard,
- time slider,
- flood-depth visualization,
- drainage overlays,
- route visualization,
- user-facing status information.

---

# 8. Core Modules

A mature implementation of FloodOps is expected to contain the following logical modules:

```text
modules/
├── rainfall-nowcast/
├── terrain-processing/
├── surface-flow/
├── drainage/
├── hydraulic-simulation/
├── flood-mapping/
├── routing/
├── dashboard/
└── validation/
```

The actual repository layout may differ because implementation folders should follow the project’s adopted architecture. The module boundaries above describe **responsibilities**, not mandatory physical directory names.

---

# 9. Rainfall Nowcasting

FloodOps includes a short-range rainfall nowcasting layer intended to estimate rainfall evolution over the next **0–3 hours**.

A candidate implementation uses **pySTEPS** where suitable input data are available.

The nowcasting stage should produce time-indexed rainfall fields or equivalent spatial rainfall information that downstream stages can consume.

Conceptually:

```text
Rainfall observations
        │
        ▼
Pre-processing
        │
        ▼
Nowcasting model
        │
        ▼
t+0, t+Δt, t+2Δt, ...
        │
        ▼
0–3 hour rainfall sequence
```

The output of this stage is not the final flood prediction.

It is an upstream forcing input for the urban flood pipeline.

---

# 10. Terrain and DEM Processing

The terrain layer describes the physical surface on which rainfall-driven water movement occurs.

A **Digital Elevation Model (DEM)** may be processed using geospatial tooling such as:

- GDAL
- Rasterio
- GeoPandas
- related raster/vector utilities

Typical processing can include:

- coordinate-system handling,
- clipping to the study area,
- raster cleaning,
- resolution alignment,
- derived terrain information,
- spatial transformation,
- preparation for downstream modelling.

The DEM is particularly important because urban water tends to follow topographic gradients and accumulate in lower areas.

---

# 11. Surface Water Modelling

The surface component is responsible for translating rainfall over terrain into a representation of runoff and/or water movement.

The exact modelling method may evolve during implementation based on available data, computational constraints, and validation quality.

The intended chain is:

```text
Rainfall
   +
Terrain
   +
Surface characteristics
        │
        ▼
Surface response
        │
        ▼
Water accumulation / movement
```

A key architectural principle is that terrain-based surface reasoning should remain distinct from drainage-system simulation.

The final system may combine multiple simplified or detailed representations depending on the available information and prototype constraints.

---

# 12. Drainage Network

The drainage network is one of the most important and technically challenging parts of the system.

It represents urban stormwater infrastructure as a connected network of:

- nodes,
- links,
- inlets/outfalls where applicable,
- capacity constraints,
- and time-varying flows.

A simplified prototype may use a deliberately limited network for one study area rather than attempting to reproduce an entire city-wide drainage system.

Conceptually:

```text
Node A ─── Node B ─── Node C
   │          │          │
   │          │          │
  inlet     inlet      outlet
```

During intense rainfall, drainage demand may exceed available capacity.

This is where the system attempts to identify:

- rising hydraulic load,
- overflow,
- backing-up,
- and the resulting flood impact on nearby streets.

---

# 13. Hydraulic Simulation

FloodOps uses **EPA SWMM / PySWMM** as the primary hydraulic-simulation concept discussed for drainage behaviour.

SWMM is used to represent:

- rainfall/runoff relationships,
- drainage-network flow,
- storage,
- links and nodes,
- hydraulic behaviour,
- and overflow-related conditions.

A Python layer such as **PySWMM** can be used to orchestrate simulations and consume outputs programmatically.

The intended flow is:

```text
Rainfall forcing
      │
      ▼
Runoff generation
      │
      ▼
Drainage network
      │
      ▼
Hydraulic simulation
      │
      ▼
Node/link results
      │
      ├── flow
      ├── depth
      ├── surcharge
      └── overflow-related signals
```

The project should clearly distinguish between:

- model assumptions,
- real network data,
- synthetic/prototype network data,
- and validated observations.

---

# 14. Flood Depth Generation

The system should convert model outputs into a spatial representation that users can understand.

A target representation is:

> **street-level flood depth in centimetres**

The resulting flood map can be organized as a time series:

```text
T0      → Flood depth map
T+30m   → Flood depth map
T+60m   → Flood depth map
T+90m   → Flood depth map
...
T+3h    → Flood depth map
```

This enables a temporal slider or equivalent control in the dashboard.

The exact spatial interpolation/mapping method should be documented alongside the implemented model so reviewers can distinguish hydraulic results from visualization assumptions.

---

# 15. Flood-Safe Routing

FloodOps extends flood mapping into an actionable route recommendation layer.

Instead of treating every road equally, each road segment can be assigned a flood-risk or passability condition derived from the flood model.

Conceptually:

```text
Road Graph
    │
    ├── Road A → Safe
    ├── Road B → Flooded
    ├── Road C → Caution
    ├── Road D → Safe
    └── Road E → Flooded
             │
             ▼
      Routing constraints
             │
             ▼
       Safer route
```

A route should prioritize avoiding unacceptable flood exposure rather than merely minimizing geometric distance.

Possible route inputs include:

- road geometry,
- flood depth,
- flood status,
- temporal forecast,
- origin,
- destination.

The frontend can request route information through a backend API.

---

# 16. GIS Dashboard

The dashboard is intended to provide one place where a user can understand the evolving flood situation.

A typical dashboard can include:

- interactive map,
- current rainfall/nowcast information,
- flood-depth layer,
- drainage network overlay,
- overflow indicators,
- time slider,
- road status,
- origin/destination selection,
- flood-safe route,
- supporting event metadata.

The visual hierarchy should allow a user to move from:

**What is happening?**
→ **Where is it happening?**
→ **How bad is it?**
→ **How will it evolve?**
→ **Which route is safer?**

---

# 17. Prototype Scope

To keep the system demonstrable and technically tractable, the prototype strategy is intentionally constrained.

## Primary prototype scope

- One manageable urban study area / ward
- One representative storm/event
- A realistic or carefully constructed road network
- A manageable drainage graph
- Short-horizon rainfall forcing
- Flood-depth generation
- GIS visualization
- Flood-aware routing

The objective is to demonstrate a **complete vertical slice** rather than claim that a prototype already reproduces a city's full drainage infrastructure.

This approach allows the architecture to be demonstrated end-to-end while keeping the most difficult components, particularly drainage and hydraulic simulation, within a workable scope.

---

# 18. Demo Strategy

The demonstration strategy is based on **precomputed/replayable data** where appropriate.

The demo should not depend on:

- unreliable live internet,
- third-party services being available at presentation time,
- long-running live simulations,
- or unpredictable external data sources.

A typical 60–90 second demonstration flow is:

1. Show rainfall / rainfall nowcast.
2. Show rainfall interaction with terrain.
3. Show drainage-network behaviour.
4. Show overflow / accumulation.
5. Show flood-depth visualization.
6. Move the time slider.
7. Select an origin and destination.
8. Show the flood-aware safer route.

The demonstration should prioritize clear evidence of the complete pipeline.

---

# 19. Technology Stack

| Layer | Technologies / Tools |
|---|---|
| Frontend | React, TypeScript |
| Mapping | Leaflet / Folium / Mapbox where appropriate |
| Backend API | FastAPI |
| Rainfall Nowcasting | pySTEPS |
| Terrain / Raster | GDAL, Rasterio |
| Vector / GIS | GeoPandas |
| Road Network | OpenStreetMap, OSMnx |
| Drainage Simulation | EPA SWMM, PySWMM |
| Routing | Graph-based routing logic integrated with flood constraints |
| Data Formats | GeoJSON, raster formats, SWMM `.inp`, structured JSON/CSV where appropriate |
| Version Control | Git, GitHub |

The exact dependencies installed in the repository should be treated as authoritative over this conceptual stack.

---

# 20. Repository Structure

The repository should maintain a clean separation between the application layers and modelling/data assets.

A recommended high-level structure is:

```text
FloodOps/
├── frontend/
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── ...
│
├── backend/
│   ├── app/
│   ├── tests/
│   ├── requirements.txt
│   └── ...
│
├── data/
│   ├── dem/
│   ├── roads/
│   ├── rainfall/
│   ├── drainage/
│   ├── storms/
│   └── processed/
│
├── simulations/
│   ├── swmm/
│   ├── scripts/
│   └── outputs/
│
├── notebooks/
│   └── ...
│
├── docs/
│   ├── architecture/
│   ├── methodology/
│   ├── validation/
│   └── demo/
│
├── README.md
├── .gitignore
└── ...
```

This is a logical reference architecture. The repository's actual final structure should reflect the implementation that exists rather than introducing unused folders.

---

# 21. Data Flow

The complete logical data flow is:

```text
                 ┌────────────────────┐
                 │ Rainfall Input     │
                 └─────────┬──────────┘
                           │
                           ▼
                 ┌────────────────────┐
                 │ Rainfall Nowcast   │
                 └─────────┬──────────┘
                           │
                           ▼
 ┌─────────────┐   ┌────────────────────┐
 │ DEM / Terrain│──►│ Surface Response   │
 └─────────────┘   └─────────┬──────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │ Drainage Graph │
                    └───────┬────────┘
                            │
                            ▼
                    ┌────────────────┐
                    │ SWMM / PySWMM  │
                    └───────┬────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │ Flood Depth Output │
                  └─────────┬──────────┘
                            │
                  ┌─────────┴──────────┐
                  ▼                    ▼
          ┌──────────────┐     ┌──────────────┐
          │ GIS Map      │     │ Road Graph   │
          └──────────────┘     └──────┬───────┘
                                      │
                                      ▼
                             ┌─────────────────┐
                             │ Safe Routing    │
                             └────────┬────────┘
                                      │
                                      ▼
                             ┌─────────────────┐
                             │ FloodOps UI/API │
                             └─────────────────┘
```

---

# 22. Inputs

Depending on the implementation stage and available datasets, inputs may include:

## Rainfall

- rainfall observations,
- rainfall grids,
- event-specific rainfall data,
- nowcast input sequences.

## Terrain

- Digital Elevation Model,
- derived terrain layers,
- study-area boundary.

## Roads

- OpenStreetMap road network,
- road geometry,
- graph connectivity.

## Drainage

- drainage nodes,
- drainage links,
- capacities,
- inlets/outfalls,
- or a carefully constructed prototype network where official network data are unavailable.

## Storm Event

- storm duration,
- rainfall intensity,
- timestamps,
- event metadata.

---

# 23. Outputs

Potential system outputs include:

- rainfall nowcast sequence,
- terrain-derived layers,
- surface-flow representation,
- drainage-network states,
- overflow indicators,
- time-dependent flood depth,
- flooded road segments,
- route recommendations,
- GIS layers,
- API responses,
- dashboard visualizations.

---

# 24. Backend Architecture

The backend is responsible for exposing modelling results and application services through APIs.

A conceptual backend structure is:

```text
backend/
└── app/
    ├── api/
    ├── core/
    ├── services/
    ├── models/
    ├── schemas/
    ├── simulation/
    ├── routing/
    ├── geospatial/
    └── main.py
```

Responsibilities may include:

- API routing,
- request validation,
- flood-data retrieval,
- simulation orchestration,
- route generation,
- geospatial processing,
- response serialization,
- configuration management.

The exact implementation should follow the actual source code in the repository.

---

# 25. Frontend Architecture

The frontend is the user-facing visualization layer.

A clean React + TypeScript architecture may separate:

- pages,
- reusable components,
- feature-specific components,
- layouts,
- services,
- hooks,
- utilities,
- types,
- routes,
- styles,
- assets.

The frontend should not contain the authoritative hydraulic calculations.

Instead, it should consume model/API outputs and provide:

- visualization,
- interaction,
- route selection,
- temporal exploration,
- status interpretation.

---

# 26. API Responsibilities

A future/implemented API surface may include responsibilities such as:

```text
GET  /health
GET  /rainfall
GET  /forecast
GET  /flood-map
GET  /flood-depth
GET  /drainage
GET  /drainage/overflow
POST /route
GET  /events/{event_id}
```

The exact endpoint paths should be documented from the actual implementation once the API is finalized.

The API layer should return structured data that can be rendered by the frontend without embedding model-specific logic into UI components.

---

# 27. Installation

> **Note:** The commands below are intended as a documentation template until the repository's final scripts and dependency files are fixed. Always prefer the actual package manager and commands defined by the repository.

## Prerequisites

Recommended environment:

- Git
- Node.js
- npm
- Python 3.x
- A compatible SWMM installation/runtime
- A virtual environment for Python dependencies

Optional tooling depending on the implementation:

- Docker
- GDAL
- QGIS
- database tooling

---

# 28. Environment Configuration

Environment-specific settings should be placed in local environment files rather than committed secrets.

Example:

```text
frontend/.env
backend/.env
```

Typical configuration categories may include:

```text
API_BASE_URL=
MAP_PROVIDER_KEY=
DATABASE_URL=
DATA_DIR=
SIMULATION_DIR=
```

Do not commit:

- private API keys,
- passwords,
- tokens,
- credentials,
- internal service URLs,
- production secrets.

A `.env.example` file should be maintained with placeholder values wherever configuration is required.

---

# 29. Running the Project

## Frontend

Typical development flow:

```bash
cd frontend
npm install
npm run dev
```

## Backend

Typical development flow:

```bash
cd backend
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Then install the repository's backend dependencies using its actual dependency file.

For FastAPI applications, a typical development command is:

```bash
uvicorn app.main:app --reload
```

Use the project's actual entry point if it differs.

---

# 30. Running the Simulation Pipeline

A complete simulation run conceptually follows:

```text
Prepare rainfall
      ↓
Generate/obtain nowcast
      ↓
Prepare DEM
      ↓
Prepare road network
      ↓
Prepare drainage graph
      ↓
Generate SWMM model/input
      ↓
Run hydraulic simulation
      ↓
Process model outputs
      ↓
Generate flood-depth layers
      ↓
Associate flood information with roads
      ↓
Generate routing weights/constraints
      ↓
Expose results through API
      ↓
Render in dashboard
```

The actual scripts and commands should remain documented close to the implementation once they are finalized.

---

# 31. Development Workflow

The implementation should follow a foundation-first approach.

## Phase 1 — Foundation

- environment setup,
- study-area selection,
- DEM acquisition/processing,
- basic geospatial pipeline.

## Phase 2 — Spatial Inputs

- road network,
- storm event,
- rainfall inputs,
- supporting geographic data.

## Phase 3 — Drainage

- drainage graph,
- node/link representation,
- SWMM model,
- simulation outputs.

## Phase 4 — Flood Mapping

- flood-depth processing,
- spatial visualization,
- temporal outputs.

## Phase 5 — Routing

- road graph,
- flood constraints,
- route generation.

## Phase 6 — Dashboard

- GIS interface,
- time slider,
- flood overlays,
- safe-route interaction.

## Phase 7 — Validation and Demo

- validation,
- screenshots,
- video,
- performance checks,
- documentation.

The key principle is to complete the **end-to-end backbone** before spending disproportionate time on visual polish.

---

# 32. Git and Team Workflow

This repository is intended to remain a **shared team repository** rather than requiring each teammate to fork it.

## Recommended setup

The repository owner should add teammates as GitHub collaborators.

Each teammate can then clone the same private repository:

```bash
git clone <PRIVATE_REPOSITORY_URL>
```

Then work through feature branches:

```bash
git checkout -b feature/<short-description>
```

Example:

```bash
git checkout -b feature/flood-map
git checkout -b feature/drainage-simulation
git checkout -b feature/dashboard
git checkout -b feature/routing
```

Push the branch:

```bash
git push -u origin feature/<short-description>
```

Then open a Pull Request into the agreed integration branch.

## Why this workflow?

It keeps:

- one source of truth,
- one issue/PR history,
- clear ownership,
- isolated feature work,
- simpler merges,
- and a clean project history.

The repository can remain private during development and submission preparation.

After submission, the repository can be made public so judges/evaluators can inspect:

- source code,
- architecture,
- documentation,
- commit history,
- implementation details,
- and reproducibility instructions.

---

# 33. Testing and Validation

The project should validate every major layer independently before integrating the complete pipeline.

## Frontend

Check:

- route rendering,
- responsive layouts,
- map interactions,
- controls,
- time slider,
- route display,
- loading/error states.

## Backend

Check:

- endpoint correctness,
- input validation,
- response schema,
- error handling,
- service integration.

## Geospatial

Check:

- coordinate reference systems,
- raster/vector alignment,
- valid geometries,
- road-network connectivity,
- spatial joins.

## Hydraulic

Check:

- SWMM model validity,
- input correctness,
- simulation completion,
- node/link results,
- expected overflow behaviour.

## Routing

Check:

- valid origin/destination,
- route graph connectivity,
- flooded-road avoidance,
- fallback route behaviour.

---

# 34. Validation Strategy

The system should distinguish between **prototype validation** and **real-world deployment validation**.

Possible validation layers include:

### Internal consistency

Does the pipeline produce physically/logically coherent results?

### Spatial consistency

Do flood areas align with terrain and network assumptions?

### Temporal consistency

Do simulated conditions evolve sensibly across the 0–3 hour horizon?

### Drainage behaviour

Do overloaded or constrained drainage nodes produce expected responses?

### Route safety

Does the routing layer avoid road segments designated unsafe by the flood model?

### Event-level validation

Where suitable observed data are available, compare predicted flood conditions against real observations.

Any quantitative validation claim should be accompanied by:

- dataset,
- time period,
- spatial extent,
- metric,
- assumptions,
- and known uncertainty.

---

# 35. Known Limitations

FloodOps is a decision-support prototype and should not be presented as a perfect representation of real-world urban hydrology.

Potential limitations include:

## Drainage Data Availability

Detailed city-wide drainage infrastructure may not be publicly available. A prototype may therefore use a simplified or carefully constructed network.

## Terrain Resolution

DEM resolution and preprocessing directly affect surface-water representation.

## Rainfall Uncertainty

Short-horizon rainfall nowcasts are inherently uncertain, especially as lead time increases.

## Simplified Urban Hydrology

A prototype may simplify:

- infiltration,
- land-cover effects,
- sewer hydraulics,
- blockage,
- boundary conditions,
- and micro-scale drainage features.

## Flood-Depth Mapping Assumptions

Spatially translating model results to road-level depth can require assumptions when complete measurement networks are unavailable.

## Routing Uncertainty

A route can only be considered safer with respect to the modelled hazards. Real-time conditions may differ.

These limitations should be stated clearly in technical documentation and presentations.

---

# 36. Fallback Strategy

The project prioritizes hydraulic simulation, but a prototype needs a controlled fallback when detailed drainage modelling becomes the schedule bottleneck.

A simplified fallback may use:

```text
Estimated inflow > Effective drainage capacity
                 ↓
        Overflow condition
                 ↓
     Localized flood contribution
```

This should be treated as a **fallback abstraction**, not as a substitute for full hydraulic modelling where validated SWMM outputs are available.

The implementation should clearly label the difference between:

- hydraulically simulated behaviour,
- simplified prototype logic,
- and visual/mock outputs.

---

# 37. Security and Reliability Considerations

Although FloodOps is primarily a geospatial/modeling application, standard application-security practices still apply.

## Secrets

Never commit credentials or API keys.

## Input Validation

Validate:

- route coordinates,
- query parameters,
- file references,
- event identifiers,
- numeric simulation inputs.

## Error Handling

Do not expose internal stack traces to end users.

## External Dependencies

Do not make the demo critically dependent on a single external service.

## Data Integrity

Validate geospatial data before feeding it into simulation or routing pipelines.

## Reproducibility

Keep transformation scripts, configuration, and documented assumptions version-controlled where possible.

---

# 38. Reproducibility

A strong research/engineering repository should allow another developer to understand:

1. Which data were used.
2. How the data were prepared.
3. Which assumptions were made.
4. Which scripts produced intermediate outputs.
5. Which simulation configuration was used.
6. How flood layers were generated.
7. How routing consumed those layers.
8. How the dashboard consumed the API.

Where large datasets cannot be stored directly in Git, document:

- source,
- acquisition procedure,
- expected filename,
- expected format,
- coordinate reference system,
- preprocessing steps,
- and where the resulting artifact should be placed.

---

# 39. Project Roadmap

## Stage A — Selection / Submission Preparation

- finalize problem framing,
- finalize architecture,
- prepare the 6-slide presentation,
- establish repository,
- prepare initial proof-of-concept evidence,
- document assumptions.

## Stage B — Full Prototype

- obtain/process DEM,
- integrate road network,
- prepare rainfall/storm data,
- construct drainage graph,
- create SWMM model,
- execute simulation,
- generate flood maps,
- implement routing,
- integrate dashboard,
- validate outputs.

## Stage C — Finale / Advanced Prototype

Potential improvements:

- larger study area,
- better rainfall sources,
- improved drainage representation,
- stronger validation,
- improved route scoring,
- live/near-real-time ingestion,
- richer dashboard,
- automated data pipelines,
- deployment infrastructure.

---

# 40. Current Status

This README intentionally separates **project intent** from **implementation status**.

The repository should be updated with explicit status markers such as:

| Component | Status |
|---|---|
| Frontend foundation | In progress / implemented |
| Dashboard | In progress / implemented |
| Rainfall nowcast | Planned / prototype / implemented |
| DEM processing | Planned / prototype / implemented |
| Surface-flow model | Planned / prototype / implemented |
| Drainage graph | Planned / prototype / implemented |
| SWMM integration | Planned / prototype / implemented |
| Flood-depth mapping | Planned / prototype / implemented |
| Safe-route API | Planned / prototype / implemented |
| Validation | Planned / ongoing |
| Demo pipeline | Planned / prototype / completed |

**Update this table as the implementation evolves.**

Do not mark a subsystem as complete until it is actually implemented and verified.

---

# 41. Demo / Screenshots

Recommended documentation assets:

```text
docs/
└── demo/
    ├── dashboard.png
    ├── rainfall-nowcast.png
    ├── drainage-overflow.png
    ├── flood-depth.png
    ├── time-slider.png
    └── safe-route.png
```

A final project README can later embed images here, for example:

```markdown
![FloodOps Dashboard](docs/demo/dashboard.png)
```

Recommended visual sequence:

1. Main dashboard
2. Rainfall nowcast
3. Drainage overlay / overflow
4. Flood depth with time slider
5. Safer route
6. Optional architecture diagram

---

# 42. Research and References

The final repository should maintain a curated references section covering the technologies and methodology actually used.

Potential foundational references include:

- EPA SWMM documentation
- PySWMM documentation
- pySTEPS documentation
- GDAL documentation
- Rasterio documentation
- GeoPandas documentation
- OpenStreetMap
- OSMnx documentation
- Leaflet documentation
- FastAPI documentation

For any scientific methodology introduced later, add the original paper or authoritative technical source rather than relying only on secondary summaries.

Where a model or algorithm has known assumptions, document the relevant reference alongside the implementation.

---

# 43. Team

## FloodOps Team

**Project:** FloodOps  
**Problem Statement:** SIH 2026 PS 26085  
**Domain:** Urban Flood Intelligence / GIS / Hydraulic Modelling / Routing

Add the final team roster here once the submission team details are finalized.

Suggested format:

| Member | Role | Primary Contribution |
|---|---|---|
| Member 1 | Team Lead / System Architecture | Architecture, integration |
| Member 2 | Backend / Simulation | APIs, simulation pipeline |
| Member 3 | Frontend / GIS | Dashboard, visualization |
| Member 4 | Data / Geospatial | DEM, roads, drainage, validation |

Roles should describe actual contributions rather than titles added only for presentation.

---

# 44. License

The license should be selected before public release.

Until then, the repository can remain private and the license section can be finalized alongside the public release decision.

Recommended options to evaluate include:

- MIT License
- Apache License 2.0
- another license appropriate to the team's intended usage.

Do not add a license that imposes obligations the team has not reviewed.

---

# 45. Disclaimer

FloodOps is a prototype/research-oriented decision-support system.

Its outputs depend on the quality and resolution of:

- rainfall data,
- terrain data,
- drainage representation,
- hydraulic assumptions,
- road-network data,
- and routing logic.

Flood depth and route recommendations should therefore be interpreted as **model-based guidance**, not guaranteed real-world measurements or official emergency instructions.

Any public deployment should undergo substantially stronger validation, calibration, monitoring, and operational review before being used for real emergency decision making.

---

## Project Philosophy

FloodOps is built around a simple engineering principle:

> **Do not stop at prediction. Turn prediction into an actionable decision.**

Rainfall alone is not enough.

A flood map alone is not enough.

A route planner alone is not enough.

FloodOps connects all three through an interpretable pipeline:

```text
Rainfall
   ↓
Nowcast
   ↓
Terrain
   ↓
Surface Water
   ↓
Drainage
   ↓
Hydraulic Behaviour
   ↓
Flood Depth
   ↓
Road Risk
   ↓
Safer Route
```

The goal is a system that is technically explainable, spatially grounded, demonstrable, and extensible.

---

## Repository Maintenance Note

As implementation progresses, keep this README synchronized with the repository.

In particular, update:

- installation commands,
- environment variables,
- actual API endpoints,
- final folder structure,
- current component status,
- datasets,
- model assumptions,
- validation results,
- screenshots,
- demo links,
- and deployment instructions.

A README is most valuable when it describes the system that actually exists.
