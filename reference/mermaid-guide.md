# Mermaid rules and patterns for codebase guides

GitHub, GitLab, VS Code and Obsidian render ```` ```mermaid ```` blocks as diagrams. One syntax slip shows the reader an error box instead, so follow these rules exactly.

## Syntax rules (these prevent almost every rendering failure)

1. **Quote every label:** `authSvc["auth.service.ts"]`. Inside quotes, slashes, dots, colons, parentheses and `&` are all safe. Without quotes, `(`, `)`, `[`, `]`, `{`, `}`, `;` and a leading `/` break the diagram.
2. **Node ids are plain words:** letters, digits and `_` only (`authSvc`, `db`, `routes_v1`). Never use `end`, `graph` or `subgraph` as an id. Do not start an id with `o` or `x` right after `--` (`A---oB` draws a circle edge).
3. **Quote edge labels:** `a -->|"calls (HTTP)"| b`.
4. **Subgraphs** get an id and a quoted title: `subgraph api ["Backend API (FastAPI)"]` … `end`. Every `subgraph` needs its own `end`.
5. **Sequence diagrams:** no `;` inside a message, because it ends the statement early. Close every `alt`, `opt`, `loop`, `par` and `rect` with `end`.
6. **ER diagrams:** entity names have no spaces (`USER`, `ORDER_ITEM`); relationships always have a label: `USER ||--o{ ORDER : places`.
7. **Line breaks** inside a quoted label: `<br/>`. No other HTML.
8. **No `%%{init}%%` theme blocks.** The host picks light or dark.
9. Keep each diagram **at or under ~15 nodes**. Two small diagrams beat one unreadable one. Use subgraphs for layers.
10. A literal double quote inside a label is written `#quot;`.

## Colour by role (optional, works in light and dark mode)

```mermaid
flowchart LR
  ui["UI"]:::ui --> api["API"]:::api --> logic["Services"]:::logic --> data[("Database")]:::data
  logic --> ext["Stripe API"]:::ext
  classDef ui fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
  classDef api fill:#ede9fe,stroke:#7c3aed,color:#4c1d95
  classDef logic fill:#dcfce7,stroke:#16a34a,color:#14532d
  classDef data fill:#fef3c7,stroke:#d97706,color:#78350f
  classDef ext fill:#f3f4f6,stroke:#6b7280,color:#111827
```

## 1. Architecture (section 4)

Build it from the scan: **architecture groups** become nodes and **folder-to-folder dependencies** become arrows. Merge small groups, then add what the scan cannot see: the user or browser, databases, queues and third-party APIs.

```mermaid
flowchart LR
  user(["User / browser"])
  subgraph fe ["Frontend: frontend/src"]
    routes["routes/<br/>pages"]
    comps["components/"]
    client["client/<br/>generated API client"]
  end
  subgraph be ["Backend: backend/app"]
    api["api/routes/<br/>HTTP endpoints"]
    core["core/<br/>config, security, db"]
    models["models.py<br/>tables + schemas"]
  end
  db[("PostgreSQL")]
  mail["SMTP server"]
  user --> routes
  routes --> comps
  routes --> client
  client -->|"HTTP JSON"| api
  api --> core
  api --> models
  core -->|"SQL"| db
  api -.->|"emails"| mail
```

Shapes: `(["..."])` people, `[("...")]` databases and storage, `["..."]` code, dotted `-.->` for optional or async links.

## 2. Folder map (section 5)

```mermaid
flowchart TD
  root["repo/"] --> src["src/<br/>application code"]
  root --> tests["tests/<br/>unit + e2e tests"]
  root --> infra["docker/ + .github/<br/>build and CI"]
  src --> routes["routes/<br/>one folder per feature"]
  src --> lib["lib/<br/>shared helpers"]
  src --> db["db/<br/>schema + migrations"]
```

A `mindmap` also works on GitHub, but the flowchart above is the most reliable everywhere.

## 3. Main flow (section 6)

Participants are files or layers, named so the reader can find them. Messages name the real function.

```mermaid
sequenceDiagram
  autonumber
  actor U as User
  participant R as auth.controller.ts
  participant S as auth.service.ts
  participant D as PostgreSQL via Prisma
  U->>R: POST /api/users/login with email and password
  R->>S: login(input)
  S->>D: findUnique user by email
  D-->>S: user row
  alt password matches
    S-->>R: user + JWT
    R-->>U: 200 with user JSON
  else wrong password
    S-->>R: throws HttpException 403
    R-->>U: 403 error JSON
  end
```

## 4. Data model (section 7)

```mermaid
erDiagram
  USER ||--o{ ARTICLE : writes
  USER ||--o{ COMMENT : posts
  ARTICLE ||--o{ COMMENT : has
  ARTICLE }o--o{ TAG : "tagged with"
  USER {
    int id PK
    string email "unique"
    string username "unique"
    string password "bcrypt hash"
  }
  ARTICLE {
    int id PK
    string slug "unique, used in URLs"
    int authorId FK
  }
```

Show only the important columns: ids, foreign keys, and fields the logic depends on.

## 5. Lifecycle or status (optional)

Use this when a status field drives behaviour (orders, jobs, payments).

```mermaid
stateDiagram-v2
  [*] --> pending
  pending --> paid: payment webhook
  pending --> cancelled: user cancels
  paid --> shipped: warehouse marks shipped
  shipped --> [*]
  cancelled --> [*]
```

## 6. Hub-file dependency view (optional)

Use this when a few files carry most of the app (highest "In" in the scan).

```mermaid
flowchart LR
  prisma["src/prisma/prisma-client.ts"]
  a["article.service.ts"] --> prisma
  b["auth.service.ts"] --> prisma
  c["profile.service.ts"] --> prisma
  d["tag.service.ts"] --> prisma
```

## 7. Class diagram (optional, for OOP-heavy code)

```mermaid
classDiagram
  class Repository {
    +find(id)
    +save(entity)
  }
  class UserRepository
  Repository <|-- UserRepository
  UserService --> UserRepository : uses
```
