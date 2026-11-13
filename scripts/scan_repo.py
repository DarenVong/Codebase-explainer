#!/usr/bin/env python3
"""
scan_repo.py - dependency-free inventory of a codebase (codebase-explainer skill).

Usage:
    python3 scan_repo.py [ROOT] [--focus SUBDIR] [--json OUT.json] [--max-list N]

Prints a Markdown report to stdout with:
  * size and language breakdown
  * detected stack (frameworks, databases, tooling) with evidence
  * manifests, run scripts, Makefile targets, docker-compose services
  * likely entry points
  * top-level folder map and folder-to-folder dependency edges
  * hub files (most imported) and possibly-unused source files
  * routes / endpoints
  * environment variables and where they are read (names only, never values)
  * full file inventory: path, kind, language, lines, fan-in, fan-out

Only the Python standard library is used. Python 3.8+.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "bower_components", "jspm_packages",
    ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".tox", ".nox", ".eggs", "dist", "build", "out", ".next", ".nuxt", ".output",
    ".svelte-kit", ".turbo", ".cache", ".parcel-cache", ".vercel", ".netlify",
    "coverage", ".nyc_output", "htmlcov", "target", "vendor", "Pods", ".gradle",
    ".idea", ".vscode", ".terraform", "DerivedData", ".expo", ".dart_tool",
    "site-packages", ".angular", "storybook-static", ".docusaurus", "tmp", ".tmp",
    ".serverless", ".aws-sam", "bin-debug", "obj",
}

BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".icns", ".webp", ".avif",
    ".tif", ".tiff", ".psd", ".ai", ".sketch", ".fig", ".woff", ".woff2", ".ttf",
    ".otf", ".eot", ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".mp4", ".mov",
    ".avi", ".webm", ".mkv", ".pdf", ".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z",
    ".rar", ".jar", ".war", ".class", ".dll", ".so", ".dylib", ".exe", ".bin",
    ".o", ".a", ".lib", ".pyc", ".pyo", ".wasm", ".db", ".sqlite", ".sqlite3",
    ".pkl", ".pickle", ".npy", ".npz", ".h5", ".onnx", ".pt", ".pth", ".ckpt",
    ".safetensors", ".parquet", ".avro", ".keystore", ".jks", ".p12", ".pfx",
    ".der", ".DS_Store",
}

LANG_BY_EXT = {
    ".py": "Python", ".pyi": "Python", ".ipynb": "Jupyter Notebook",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript (JSX)",
    ".ts": "TypeScript", ".mts": "TypeScript", ".cts": "TypeScript", ".tsx": "TypeScript (TSX)",
    ".vue": "Vue", ".svelte": "Svelte", ".astro": "Astro",
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin",
    ".scala": "Scala", ".groovy": "Groovy", ".gradle": "Gradle", ".swift": "Swift",
    ".m": "Objective-C", ".mm": "Objective-C++", ".rb": "Ruby", ".erb": "Ruby (ERB)",
    ".php": "PHP", ".blade.php": "PHP (Blade)", ".cs": "C#", ".fs": "F#", ".vb": "Visual Basic",
    ".c": "C", ".h": "C/C++ header", ".cpp": "C++", ".cc": "C++", ".cxx": "C++",
    ".hpp": "C++ header", ".hh": "C++ header", ".dart": "Dart", ".ex": "Elixir",
    ".exs": "Elixir", ".erl": "Erlang", ".hs": "Haskell", ".lua": "Lua", ".r": "R",
    ".jl": "Julia", ".clj": "Clojure", ".cljs": "ClojureScript", ".ml": "OCaml",
    ".zig": "Zig", ".nim": "Nim", ".sol": "Solidity", ".pl": "Perl", ".pm": "Perl",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".fish": "Shell",
    ".ps1": "PowerShell", ".bat": "Batch", ".cmd": "Batch",
    ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "SCSS", ".sass": "Sass",
    ".less": "Less", ".styl": "Stylus", ".sql": "SQL", ".prisma": "Prisma",
    ".graphql": "GraphQL", ".gql": "GraphQL", ".proto": "Protocol Buffers",
    ".tf": "Terraform", ".hcl": "HCL", ".yaml": "YAML", ".yml": "YAML",
    ".json": "JSON", ".jsonc": "JSON", ".json5": "JSON", ".toml": "TOML",
    ".ini": "INI", ".cfg": "INI", ".xml": "XML", ".md": "Markdown", ".mdx": "MDX",
    ".rst": "reStructuredText", ".txt": "Text", ".svg": "SVG", ".csv": "CSV",
}

CODE_LANGS = {
    "Python", "JavaScript", "JavaScript (JSX)", "TypeScript", "TypeScript (TSX)", "Vue",
    "Svelte", "Astro", "Go", "Rust", "Java", "Kotlin", "Scala", "Groovy", "Swift",
    "Objective-C", "Objective-C++", "Ruby", "Ruby (ERB)", "PHP", "PHP (Blade)", "C#", "F#",
    "Visual Basic", "C", "C/C++ header", "C++", "C++ header", "Dart", "Elixir", "Erlang",
    "Haskell", "Lua", "R", "Julia", "Clojure", "ClojureScript", "OCaml", "Zig", "Nim",
    "Solidity", "Perl", "Shell", "PowerShell", "Batch", "HTML", "Jupyter Notebook",
}

LOCK_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock",
    "poetry.lock", "Pipfile.lock", "pdm.lock", "uv.lock", "Cargo.lock", "go.sum",
    "composer.lock", "Gemfile.lock", "pubspec.lock", "packages.lock.json",
    "Podfile.lock", "mix.lock", "flake.lock", "gradle.lockfile",
}

CONFIG_NAMES = {
    "package.json", "tsconfig.json", "jsconfig.json", "pyproject.toml", "setup.py",
    "setup.cfg", "requirements.txt", "Pipfile", "tox.ini", "pytest.ini", "mypy.ini",
    "go.mod", "Cargo.toml", "Gemfile", "Rakefile", "composer.json", "pom.xml",
    "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts",
    "pubspec.yaml", "Makefile", "makefile", "GNUmakefile", "Dockerfile",
    "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
    "Procfile", "Justfile", "justfile", "Taskfile.yml", ".editorconfig", ".gitignore",
    ".gitattributes", ".dockerignore", ".npmrc", ".nvmrc", ".node-version",
    ".python-version", ".tool-versions", ".prettierrc", ".eslintrc", ".babelrc",
    "babel.config.js", "vercel.json", "netlify.toml", "fly.toml", "render.yaml",
    "app.json", "eas.json", "angular.json", "nx.json", "turbo.json", "lerna.json",
    "pnpm-workspace.yaml", "firebase.json", "serverless.yml", "manage.py",
    "config.ru", "artisan", "deno.json", "deno.jsonc", "bunfig.toml", "biome.json",
    "CMakeLists.txt", "meson.build", "Podfile", "Info.plist", "AndroidManifest.xml",
    "tauri.conf.json", "wrangler.toml", "Chart.yaml", "skaffold.yaml", "Brewfile",
}

CONFIG_PATTERNS = [
    "*.config.js", "*.config.ts", "*.config.mjs", "*.config.cjs", "*.config.json",
    ".eslintrc*", ".prettierrc*", ".stylelintrc*", "tsconfig*.json", "requirements*.txt",
    "Dockerfile*", "*.dockerfile", ".env*", "*.csproj", "*.sln", "*.xcconfig",
    "*.gemspec", "*.cabal", "*.nimble", "vite.config.*", "next.config.*",
    "nuxt.config.*", "svelte.config.*", "astro.config.*", "tailwind.config.*",
    "postcss.config.*", "webpack.config.*", "rollup.config.*", "jest.config.*",
    "vitest.config.*", "playwright.config.*", "cypress.config.*", "karma.conf.*",
    "metro.config.*", "drizzle.config.*", "knexfile.*", "ormconfig.*",
    "alembic.ini", "*.properties", "application*.yml", "application*.yaml",
]

DOC_NAMES = {"readme", "changelog", "contributing", "license", "licence", "code_of_conduct",
             "security", "authors", "notice", "history", "copying", "todo"}

TEST_DIR_NAMES = {"test", "tests", "__tests__", "spec", "specs", "e2e", "cypress",
                  "playwright", "integration_tests", "unit_tests", "testing", "__mocks__"}

MAX_READ_BYTES = 1_000_000

# dependency name (lower-case) -> (layer, label). Prefix entries end with '*'.
KNOWN_DEPS = {
    # JS frontend
    "react": ("Frontend", "React"), "react-dom": ("Frontend", "React DOM"),
    "next": ("Frontend / full-stack", "Next.js"), "vue": ("Frontend", "Vue"),
    "nuxt": ("Frontend / full-stack", "Nuxt"), "svelte": ("Frontend", "Svelte"),
    "@sveltejs/kit": ("Frontend / full-stack", "SvelteKit"),
    "@angular/core": ("Frontend", "Angular"), "solid-js": ("Frontend", "SolidJS"),
    "preact": ("Frontend", "Preact"), "astro": ("Frontend", "Astro"),
    "@remix-run/*": ("Frontend / full-stack", "Remix"),
    "react-router": ("Routing", "React Router"), "react-router-dom": ("Routing", "React Router"),
    "@tanstack/react-router": ("Routing", "TanStack Router"),
    "vue-router": ("Routing", "Vue Router"), "gatsby": ("Frontend", "Gatsby"),
    "jquery": ("Frontend", "jQuery"), "htmx.org": ("Frontend", "htmx"),
    "three": ("Graphics", "Three.js"), "d3": ("Charts", "D3"),
    "chart.js": ("Charts", "Chart.js"), "recharts": ("Charts", "Recharts"),
    # state / data fetching
    "redux": ("State", "Redux"), "@reduxjs/toolkit": ("State", "Redux Toolkit"),
    "zustand": ("State", "Zustand"), "mobx": ("State", "MobX"), "pinia": ("State", "Pinia"),
    "jotai": ("State", "Jotai"), "recoil": ("State", "Recoil"), "xstate": ("State", "XState"),
    "@tanstack/react-query": ("Data fetching", "TanStack Query"),
    "react-query": ("Data fetching", "React Query"), "swr": ("Data fetching", "SWR"),
    "axios": ("HTTP client", "Axios"), "@apollo/client": ("Data fetching", "Apollo Client"),
    "@trpc/*": ("API", "tRPC"), "graphql": ("API", "GraphQL"),
    # styling / UI
    "tailwindcss": ("Styling", "Tailwind CSS"), "styled-components": ("Styling", "styled-components"),
    "@emotion/react": ("Styling", "Emotion"), "sass": ("Styling", "Sass"),
    "@mui/material": ("UI kit", "Material UI"), "@chakra-ui/react": ("UI kit", "Chakra UI"),
    "antd": ("UI kit", "Ant Design"), "bootstrap": ("UI kit", "Bootstrap"),
    "@radix-ui/*": ("UI kit", "Radix UI"), "@headlessui/react": ("UI kit", "Headless UI"),
    "framer-motion": ("Animation", "Framer Motion"),
    # JS backend
    "express": ("Backend / API", "Express"), "fastify": ("Backend / API", "Fastify"),
    "koa": ("Backend / API", "Koa"), "hono": ("Backend / API", "Hono"),
    "@nestjs/*": ("Backend / API", "NestJS"), "@hapi/hapi": ("Backend / API", "hapi"),
    "socket.io": ("Realtime", "Socket.IO"), "ws": ("Realtime", "WebSockets (ws)"),
    "@apollo/server": ("API", "Apollo Server"), "apollo-server": ("API", "Apollo Server"),
    "passport": ("Auth", "Passport"), "jsonwebtoken": ("Auth", "JWT"),
    "next-auth": ("Auth", "NextAuth"), "@auth/*": ("Auth", "Auth.js"),
    "@clerk/*": ("Auth", "Clerk"), "bcrypt": ("Auth", "bcrypt"), "bcryptjs": ("Auth", "bcrypt"),
    "zod": ("Validation", "Zod"), "joi": ("Validation", "Joi"), "yup": ("Validation", "Yup"),
    # DB / ORM
    "prisma": ("Database / ORM", "Prisma"), "@prisma/client": ("Database / ORM", "Prisma"),
    "drizzle-orm": ("Database / ORM", "Drizzle"), "typeorm": ("Database / ORM", "TypeORM"),
    "sequelize": ("Database / ORM", "Sequelize"), "mongoose": ("Database / ORM", "Mongoose"),
    "knex": ("Database / ORM", "Knex"), "pg": ("Database", "PostgreSQL (pg)"),
    "mysql2": ("Database", "MySQL"), "mysql": ("Database", "MySQL"), "sqlite3": ("Database", "SQLite"),
    "better-sqlite3": ("Database", "SQLite"), "mongodb": ("Database", "MongoDB"),
    "redis": ("Cache / queue", "Redis"), "ioredis": ("Cache / queue", "Redis"),
    "bullmq": ("Cache / queue", "BullMQ"), "@supabase/supabase-js": ("Backend-as-a-service", "Supabase"),
    "firebase": ("Backend-as-a-service", "Firebase"), "firebase-admin": ("Backend-as-a-service", "Firebase Admin"),
    "@aws-sdk/*": ("Cloud", "AWS SDK"), "aws-sdk": ("Cloud", "AWS SDK"),
    "stripe": ("Payments", "Stripe"),
    # AI
    "openai": ("AI", "OpenAI SDK"), "@anthropic-ai/sdk": ("AI", "Anthropic SDK"),
    "anthropic": ("AI", "Anthropic SDK"), "langchain": ("AI", "LangChain"),
    "@langchain/*": ("AI", "LangChain"), "ai": ("AI", "Vercel AI SDK"),
    # mobile / desktop
    "react-native": ("Mobile", "React Native"), "expo": ("Mobile", "Expo"),
    "electron": ("Desktop", "Electron"), "@tauri-apps/api": ("Desktop", "Tauri"),
    "@capacitor/core": ("Mobile", "Capacitor"), "@ionic/*": ("Mobile", "Ionic"),
    # tooling / testing
    "typescript": ("Language", "TypeScript"), "vite": ("Build tool", "Vite"),
    "webpack": ("Build tool", "webpack"), "esbuild": ("Build tool", "esbuild"),
    "rollup": ("Build tool", "Rollup"), "turbo": ("Monorepo", "Turborepo"), "nx": ("Monorepo", "Nx"),
    "jest": ("Testing", "Jest"), "vitest": ("Testing", "Vitest"), "mocha": ("Testing", "Mocha"),
    "@playwright/test": ("Testing", "Playwright"), "cypress": ("Testing", "Cypress"),
    "@testing-library/*": ("Testing", "Testing Library"), "storybook": ("Tooling", "Storybook"),
    "@storybook/*": ("Tooling", "Storybook"), "eslint": ("Linting", "ESLint"),
    "prettier": ("Formatting", "Prettier"), "@biomejs/biome": ("Linting", "Biome"),
    "nodemon": ("Tooling", "nodemon"), "ts-node": ("Tooling", "ts-node"), "tsx": ("Tooling", "tsx"),
    # Python
    "django": ("Backend / API", "Django"), "djangorestframework": ("Backend / API", "Django REST Framework"),
    "flask": ("Backend / API", "Flask"), "fastapi": ("Backend / API", "FastAPI"),
    "starlette": ("Backend / API", "Starlette"), "tornado": ("Backend / API", "Tornado"),
    "aiohttp": ("Backend / API", "aiohttp"), "sanic": ("Backend / API", "Sanic"),
    "litestar": ("Backend / API", "Litestar"), "uvicorn": ("Server", "Uvicorn"),
    "gunicorn": ("Server", "Gunicorn"), "sqlalchemy": ("Database / ORM", "SQLAlchemy"),
    "sqlmodel": ("Database / ORM", "SQLModel"), "alembic": ("Database / ORM", "Alembic migrations"),
    "peewee": ("Database / ORM", "Peewee"), "tortoise-orm": ("Database / ORM", "Tortoise ORM"),
    "psycopg2": ("Database", "PostgreSQL"), "psycopg2-binary": ("Database", "PostgreSQL"),
    "psycopg": ("Database", "PostgreSQL"), "asyncpg": ("Database", "PostgreSQL"),
    "pymongo": ("Database", "MongoDB"), "motor": ("Database", "MongoDB"),
    "pydantic": ("Validation", "Pydantic"), "marshmallow": ("Validation", "Marshmallow"),
    "celery": ("Cache / queue", "Celery"), "rq": ("Cache / queue", "RQ"),
    "pytest": ("Testing", "pytest"), "requests": ("HTTP client", "requests"),
    "httpx": ("HTTP client", "HTTPX"), "click": ("CLI", "Click"), "typer": ("CLI", "Typer"),
    "numpy": ("Data / ML", "NumPy"), "pandas": ("Data / ML", "pandas"),
    "scikit-learn": ("Data / ML", "scikit-learn"), "torch": ("Data / ML", "PyTorch"),
    "tensorflow": ("Data / ML", "TensorFlow"), "transformers": ("Data / ML", "Hugging Face Transformers"),
    "streamlit": ("Frontend", "Streamlit"), "gradio": ("Frontend", "Gradio"),
    "jinja2": ("Templating", "Jinja2"), "boto3": ("Cloud", "AWS (boto3)"),
    "pyqt5": ("Desktop", "PyQt"), "pyside6": ("Desktop", "PySide"), "kivy": ("Desktop", "Kivy"),
    "discord.py": ("Bot", "discord.py"), "python-telegram-bot": ("Bot", "python-telegram-bot"),
    # Go
    "github.com/gin-gonic/gin": ("Backend / API", "Gin"), "github.com/labstack/echo*": ("Backend / API", "Echo"),
    "github.com/gofiber/fiber*": ("Backend / API", "Fiber"), "github.com/go-chi/chi*": ("Backend / API", "chi"),
    "github.com/gorilla/mux": ("Backend / API", "gorilla/mux"), "gorm.io/gorm": ("Database / ORM", "GORM"),
    "github.com/jackc/pgx*": ("Database", "PostgreSQL (pgx)"), "github.com/spf13/cobra": ("CLI", "Cobra"),
    "google.golang.org/grpc": ("API", "gRPC"), "github.com/redis/go-redis*": ("Cache / queue", "Redis"),
    # Rust
    "actix-web": ("Backend / API", "Actix Web"), "axum": ("Backend / API", "Axum"),
    "rocket": ("Backend / API", "Rocket"), "tokio": ("Async runtime", "Tokio"),
    "serde": ("Serialization", "Serde"), "diesel": ("Database / ORM", "Diesel"),
    "sqlx": ("Database / ORM", "SQLx"), "clap": ("CLI", "clap"), "tauri": ("Desktop", "Tauri"),
    "bevy": ("Game engine", "Bevy"),
    # Ruby / PHP / JVM / .NET / Dart
    "rails": ("Backend / full-stack", "Ruby on Rails"), "sinatra": ("Backend / API", "Sinatra"),
    "rspec": ("Testing", "RSpec"), "rspec-rails": ("Testing", "RSpec"), "sidekiq": ("Cache / queue", "Sidekiq"),
    "devise": ("Auth", "Devise"), "pg ": ("Database", "PostgreSQL"),
    "laravel/framework": ("Backend / full-stack", "Laravel"), "symfony/*": ("Backend / API", "Symfony"),
    "phpunit/phpunit": ("Testing", "PHPUnit"),
    "spring-boot*": ("Backend / API", "Spring Boot"), "hibernate*": ("Database / ORM", "Hibernate"),
    "junit*": ("Testing", "JUnit"), "ktor*": ("Backend / API", "Ktor"),
    "microsoft.aspnetcore*": ("Backend / API", "ASP.NET Core"),
    "microsoft.entityframeworkcore*": ("Database / ORM", "Entity Framework Core"),
    "flutter": ("Mobile", "Flutter"), "provider": ("State", "Provider (Flutter)"),
    "flutter_bloc": ("State", "BLoC (Flutter)"), "riverpod": ("State", "Riverpod"),
}

FILE_SIGNALS = [  # (glob on path, layer, label)
    ("next.config.*", "Frontend / full-stack", "Next.js"),
    ("nuxt.config.*", "Frontend / full-stack", "Nuxt"),
    ("svelte.config.*", "Frontend", "Svelte/SvelteKit"),
    ("astro.config.*", "Frontend", "Astro"),
    ("angular.json", "Frontend", "Angular"),
    ("vite.config.*", "Build tool", "Vite"),
    ("tailwind.config.*", "Styling", "Tailwind CSS"),
    ("manage.py", "Backend / API", "Django"),
    ("config/routes.rb", "Backend / full-stack", "Ruby on Rails"),
    ("artisan", "Backend / full-stack", "Laravel"),
    ("*schema.prisma", "Database / ORM", "Prisma"),
    ("Dockerfile*", "Infra", "Docker"),
    ("docker-compose.y*ml", "Infra", "Docker Compose"),
    ("compose.y*ml", "Infra", "Docker Compose"),
    ("*.tf", "Infra", "Terraform"),
    ("serverless.yml", "Infra", "Serverless Framework"),
    ("vercel.json", "Hosting", "Vercel"),
    ("netlify.toml", "Hosting", "Netlify"),
    ("fly.toml", "Hosting", "Fly.io"),
    ("wrangler.toml", "Hosting", "Cloudflare Workers"),
    ("firebase.json", "Backend-as-a-service", "Firebase"),
    ("supabase/config.toml", "Backend-as-a-service", "Supabase"),
    (".github/workflows/*", "CI/CD", "GitHub Actions"),
    (".gitlab-ci.yml", "CI/CD", "GitLab CI"),
    (".circleci/config.yml", "CI/CD", "CircleCI"),
    ("Jenkinsfile", "CI/CD", "Jenkins"),
    ("*.csproj", "Backend / app", ".NET"),
    ("pubspec.yaml", "Mobile", "Flutter/Dart"),
    ("Chart.yaml", "Infra", "Helm"),
    ("*/k8s/*.y*ml", "Infra", "Kubernetes manifests"),
]

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def posix(p: str) -> str:
    return p.replace(os.sep, "/")


def read_text(abs_path: str, limit: int = MAX_READ_BYTES) -> str | None:
    try:
        with open(abs_path, "rb") as fh:
            data = fh.read(limit + 1)
    except OSError:
        return None
    if len(data) > limit:
        return None
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def count_lines(abs_path: str) -> int:
    try:
        size = os.path.getsize(abs_path)
        if size > 20_000_000:
            return 0
        with open(abs_path, "rb") as fh:
            data = fh.read()
        if b"\x00" in data[:8192]:
            return 0
        n = data.count(b"\n")
        return n + (1 if data and not data.endswith(b"\n") else 0)
    except OSError:
        return 0


def ext_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if name.endswith(".blade.php"):
        return ".blade.php"
    if name.startswith(".") and name.count(".") == 1:
        return ""
    return os.path.splitext(name)[1].lower()


def strip_json_comments(text: str) -> str:
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
        else:
            out.append(c)
            i += 1
    cleaned = "".join(out)
    return re.sub(r",(\s*[}\]])", r"\1", cleaned)


def load_json(abs_path: str):
    txt = read_text(abs_path)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except ValueError:
        try:
            return json.loads(strip_json_comments(txt))
        except ValueError:
            return None


def load_toml(abs_path: str):
    txt = read_text(abs_path)
    if txt is None:
        return None
    try:
        import tomllib  # type: ignore[import-not-found]
        return tomllib.loads(txt)
    except Exception:
        pass
    try:
        import tomli  # type: ignore[import-not-found]
        return tomli.loads(txt)
    except Exception:
        return None


def md_escape(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


# --------------------------------------------------------------------------
# File discovery & classification
# --------------------------------------------------------------------------


def git_info(root: str):
    def run(*args):
        try:
            r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=30)
            return r.stdout.strip() if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    if run("rev-parse", "--is-inside-work-tree") != "true":
        return None
    return {
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": run("rev-parse", "--short", "HEAD"),
        "toplevel": run("rev-parse", "--show-toplevel"),
        "remote": run("config", "--get", "remote.origin.url"),
        "last_commit_date": run("log", "-1", "--format=%cs"),
    }


def is_skipped_dir(rel_parts) -> bool:
    for part in rel_parts:
        if part in SKIP_DIRS or part.endswith(".egg-info"):
            return True
    return False


SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def self_prefix(root: str):
    """Repo-relative path of this skill's folder when it lives inside the repo, else None."""
    rel = os.path.relpath(SKILL_DIR, os.path.abspath(root))
    if rel == "." or rel.startswith(".."):
        return None
    return posix(rel).rstrip("/") + "/"


def list_files(root: str, use_git: bool):
    files = []
    own = self_prefix(root)
    if use_git:
        try:
            r = subprocess.run(
                ["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                capture_output=True, timeout=120,
            )
            if r.returncode == 0:
                for raw in r.stdout.split(b"\x00"):
                    if not raw:
                        continue
                    rel = raw.decode("utf-8", errors="replace")
                    parts = rel.split("/")
                    if is_skipped_dir(parts[:-1]) or (own and rel.startswith(own)):
                        continue
                    if os.path.isfile(os.path.join(root, rel)):
                        files.append(rel)
                return sorted(set(files))
        except (OSError, subprocess.SubprocessError):
            pass
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = posix(os.path.relpath(dirpath, root))
        keep = []
        for d in dirnames:
            if d in SKIP_DIRS or d.endswith(".egg-info"):
                continue
            if d == "env" and os.path.exists(os.path.join(dirpath, d, "pyvenv.cfg")):
                continue
            if os.path.islink(os.path.join(dirpath, d)):
                continue
            keep.append(d)
        dirnames[:] = keep
        if own:
            dirnames[:] = [d for d in dirnames
                           if not (own == (d if rel_dir == "." else f"{rel_dir}/{d}") + "/")]
        for f in filenames:
            rel = f if rel_dir == "." else f"{rel_dir}/{f}"
            files.append(rel)
    return sorted(files)


def classify(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    lower = name.lower()
    parts = [p.lower() for p in path.split("/")[:-1]]
    ext = ext_of(path)
    stem = lower.split(".")[0]

    if name in LOCK_FILES or lower.endswith((".min.js", ".min.css", ".map", ".pb.go", "_pb2.py",
                                              "_pb2_grpc.py", ".g.dart", ".freezed.dart")) \
            or ".generated." in lower or lower.endswith(".d.ts") and "generated" in path.lower():
        return "lock/generated"
    if ext in BINARY_EXT or ext in {".svg"}:
        return "asset"
    if any(p in {".github", ".gitlab", ".circleci", ".buildkite"} for p in parts) or \
            name in {".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml", ".travis.yml", "bitbucket-pipelines.yml"}:
        return "ci"
    if "migrations" in parts or "migration" in parts or (parts and parts[-1] == "versions" and "alembic" in parts):
        return "migration"
    if any(p in TEST_DIR_NAMES for p in parts) or re.search(
            r"(^test_.*\.py$|_test\.(py|go|rb|exs)$|\.(test|spec|e2e|cy)\.[cm]?[jt]sx?$|_spec\.rb$|Tests?\.(java|kt|cs|swift)$|conftest\.py$)",
            name):
        return "test"
    if stem in DOC_NAMES or ext in {".md", ".mdx", ".rst", ".adoc"} or (parts and parts[0] in {"docs", "doc", "documentation"}):
        return "docs"
    if ext in {".prisma", ".graphql", ".gql", ".proto"} or lower in {"schema.sql", "openapi.yaml", "openapi.json", "swagger.yaml", "swagger.json"}:
        return "schema"
    if ext == ".sql":
        return "database"
    if ext in {".css", ".scss", ".sass", ".less", ".styl"}:
        return "style"
    if name in CONFIG_NAMES or any(fnmatch.fnmatch(name, pat) for pat in CONFIG_PATTERNS):
        return "config"
    lang = LANG_BY_EXT.get(ext)
    if lang in CODE_LANGS:
        if parts and parts[0] in {"scripts", "script", "tools", "bin"}:
            return "script"
        return "source"
    if ext in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".conf", ".plist", ".properties"}:
        if parts and parts[0] in {"data", "fixtures", "seeds", "seed", "samples", "examples"}:
            return "data"
        return "config"
    if ext in {".csv", ".tsv", ".txt", ".jsonl", ".ndjson"}:
        return "data"
    if ext in {".html", ".htm", ".hbs", ".ejs", ".pug", ".jinja", ".j2", ".njk", ".liquid", ".twig", ".erb"}:
        return "source"
    if ext in {".sh", ".bash", ".zsh", ".ps1", ".bat"}:
        return "script"
    return "other"


def language(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if name.startswith("Dockerfile") or name.endswith(".dockerfile"):
        return "Dockerfile"
    if name in {"Makefile", "makefile", "GNUmakefile"}:
        return "Makefile"
    return LANG_BY_EXT.get(ext_of(path), "Other")


# --------------------------------------------------------------------------
# Manifests & stack detection
# --------------------------------------------------------------------------


def dep_label(dep: str):
    d = dep.lower().strip()
    if d in KNOWN_DEPS:
        return KNOWN_DEPS[d]
    for key, val in KNOWN_DEPS.items():
        if key.endswith("*") and d.startswith(key[:-1]):
            return val
    return None


def parse_requirements(txt: str):
    deps = []
    for line in txt.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http")):
            continue
        m = re.match(r"([A-Za-z0-9_.\-\[\]]+)", line)
        if m:
            deps.append(re.sub(r"\[.*\]", "", m.group(1)).lower())
    return deps


def analyze_manifests(root: str, files):
    manifests = []
    deps_by_source = defaultdict(set)
    for rel in files:
        name = rel.rsplit("/", 1)[-1]
        ab = os.path.join(root, rel)
        try:
            if name == "package.json":
                data = load_json(ab)
                if not isinstance(data, dict):
                    continue
                deps = {**(data.get("dependencies") or {}), **(data.get("peerDependencies") or {})}
                dev = data.get("devDependencies") or {}
                bin_field = data.get("bin")
                manifests.append({
                    "file": rel, "type": "npm", "name": data.get("name"),
                    "description": data.get("description"), "main": data.get("main") or data.get("module"),
                    "bin": bin_field if isinstance(bin_field, (dict, str)) else None,
                    "scripts": data.get("scripts") or {}, "workspaces": data.get("workspaces"),
                    "dependencies": sorted(deps), "devDependencies": sorted(dev),
                })
                for d in list(deps) + list(dev):
                    deps_by_source[d].add(rel)
            elif name == "pyproject.toml":
                data = load_toml(ab) or {}
                proj = data.get("project") or {}
                poetry = (data.get("tool") or {}).get("poetry") or {}
                deps = [re.split(r"[ <>=!~;\[(]", d, maxsplit=1)[0].lower() for d in (proj.get("dependencies") or []) if isinstance(d, str)]
                deps += [k.lower() for k in (poetry.get("dependencies") or {}) if k.lower() != "python"]
                for grp in (proj.get("optional-dependencies") or {}).values():
                    deps += [re.split(r"[ <>=!~;\[(]", d, maxsplit=1)[0].lower() for d in grp if isinstance(d, str)]
                scripts = dict(proj.get("scripts") or {})
                scripts.update(poetry.get("scripts") or {})
                if not data:  # tomllib unavailable: crude fallback
                    txt = read_text(ab) or ""
                    deps = re.findall(r'^\s*"([A-Za-z0-9_.\-]+)[^"]*",?\s*$', txt, re.M)
                manifests.append({"file": rel, "type": "python", "name": proj.get("name") or poetry.get("name"),
                                  "description": proj.get("description") or poetry.get("description"),
                                  "scripts": scripts, "dependencies": sorted(set(deps))})
                for d in deps:
                    deps_by_source[d].add(rel)
            elif fnmatch.fnmatch(name, "requirements*.txt") or name == "Pipfile":
                txt = read_text(ab) or ""
                if name == "Pipfile":
                    deps = re.findall(r'^\s*([A-Za-z0-9_.\-]+)\s*=', txt, re.M)
                    deps = [d.lower() for d in deps if d.lower() not in {"url", "verify_ssl", "name", "python_version"}]
                else:
                    deps = parse_requirements(txt)
                manifests.append({"file": rel, "type": "python", "dependencies": sorted(set(deps))})
                for d in deps:
                    deps_by_source[d].add(rel)
            elif name == "setup.py":
                txt = read_text(ab) or ""
                m = re.search(r"install_requires\s*=\s*\[(.*?)\]", txt, re.S)
                deps = [re.split(r"[ <>=!~;\[]", d, maxsplit=1)[0].lower() for d in re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))] if m else []
                manifests.append({"file": rel, "type": "python", "dependencies": sorted(set(deps))})
                for d in deps:
                    deps_by_source[d].add(rel)
            elif name == "go.mod":
                txt = read_text(ab) or ""
                mod = re.search(r"^module\s+(\S+)", txt, re.M)
                deps = re.findall(r"^\s*(?:require\s+)?([a-z0-9.\-]+\.[a-z]{2,}/[^\s]+)\s+v[\d.]", txt, re.M)
                manifests.append({"file": rel, "type": "go", "name": mod.group(1) if mod else None,
                                  "dependencies": sorted(set(deps))})
                for d in deps:
                    deps_by_source[d].add(rel)
            elif name == "Cargo.toml":
                data = load_toml(ab) or {}
                deps = list((data.get("dependencies") or {}).keys()) + list((data.get("dev-dependencies") or {}).keys())
                ws = (data.get("workspace") or {}).get("members")
                manifests.append({"file": rel, "type": "rust", "name": (data.get("package") or {}).get("name"),
                                  "workspace": ws, "dependencies": sorted(deps)})
                for d in deps:
                    deps_by_source[d].add(rel)
            elif name == "Gemfile":
                txt = read_text(ab) or ""
                deps = re.findall(r"^\s*gem\s+['\"]([^'\"]+)['\"]", txt, re.M)
                manifests.append({"file": rel, "type": "ruby", "dependencies": sorted(set(deps))})
                for d in deps:
                    deps_by_source[d].add(rel)
            elif name == "composer.json":
                data = load_json(ab) or {}
                deps = list((data.get("require") or {}).keys()) + list((data.get("require-dev") or {}).keys())
                manifests.append({"file": rel, "type": "php", "name": data.get("name"),
                                  "scripts": data.get("scripts") or {}, "dependencies": sorted(deps)})
                for d in deps:
                    deps_by_source[d].add(rel)
            elif name == "pom.xml" or name.startswith("build.gradle"):
                txt = read_text(ab) or ""
                if name == "pom.xml":
                    deps = re.findall(r"<artifactId>([^<]+)</artifactId>", txt)[1:]
                else:
                    deps = [m.split(":")[1] for m in re.findall(r"['\"]([\w.\-]+:[\w.\-]+)(?::[^'\"]*)?['\"]", txt)]
                manifests.append({"file": rel, "type": "jvm", "dependencies": sorted(set(deps))})
                for d in deps:
                    deps_by_source[d].add(rel)
            elif name.endswith(".csproj"):
                txt = read_text(ab) or ""
                deps = re.findall(r'PackageReference\s+Include="([^"]+)"', txt)
                manifests.append({"file": rel, "type": "dotnet", "dependencies": sorted(set(deps))})
                for d in deps:
                    deps_by_source[d].add(rel)
            elif name == "pubspec.yaml":
                txt = read_text(ab) or ""
                block = re.search(r"^dependencies:\s*\n((?:[ \t]+.*\n?)*)", txt, re.M)
                deps = re.findall(r"^[ \t]{2}([a-z_][a-z0-9_]*):", block.group(1), re.M) if block else []
                manifests.append({"file": rel, "type": "dart", "dependencies": sorted(set(deps))})
                for d in deps:
                    deps_by_source[d].add(rel)
            elif name in {"Makefile", "makefile", "GNUmakefile", "Justfile", "justfile"}:
                txt = read_text(ab) or ""
                targets = [t for t in re.findall(r"^([A-Za-z0-9][A-Za-z0-9_.\-/]*)\s*:(?!=)", txt, re.M)
                           if not t.startswith(".")]
                manifests.append({"file": rel, "type": "make", "targets": list(dict.fromkeys(targets))[:40]})
            elif fnmatch.fnmatch(name, "docker-compose*.y*ml") or fnmatch.fnmatch(name, "compose*.y*ml"):
                txt = read_text(ab) or ""
                svc = re.search(r"^services:\s*\n((?:(?:[ \t]+.*)?\n?)*)", txt, re.M)
                names = re.findall(r"^[ \t]{2}([A-Za-z0-9_.\-]+):\s*$", svc.group(1), re.M) if svc else []
                images = re.findall(r"^\s+image:\s*['\"]?([^\s'\"]+)", txt, re.M)
                manifests.append({"file": rel, "type": "compose", "services": names, "images": images})
                for img in images:
                    deps_by_source["image:" + img.split(":")[0].split("/")[-1]].add(rel)
            elif name == "Procfile":
                txt = read_text(ab) or ""
                manifests.append({"file": rel, "type": "procfile",
                                  "processes": dict(re.findall(r"^([\w\-]+):\s*(.+)$", txt, re.M))})
        except Exception as exc:  # never let one bad manifest kill the scan
            manifests.append({"file": rel, "type": "error", "error": str(exc)})

    stack = {}
    for dep, sources in deps_by_source.items():
        if dep.startswith("image:"):
            img = dep[6:].lower()
            for key, label in [("postgres", "PostgreSQL"), ("mysql", "MySQL"), ("mariadb", "MariaDB"),
                               ("mongo", "MongoDB"), ("redis", "Redis"), ("rabbitmq", "RabbitMQ"),
                               ("elasticsearch", "Elasticsearch"), ("nginx", "nginx"), ("kafka", "Kafka"),
                               ("minio", "MinIO"), ("localstack", "LocalStack")]:
                if key in img:
                    stack.setdefault(("Service (docker)", label), set()).update(sources)
            continue
        hit = dep_label(dep)
        if hit:
            stack.setdefault(hit, set()).update(sources)
    for rel in files:
        for pat, layer, label in FILE_SIGNALS:
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel.rsplit("/", 1)[-1], pat):
                stack.setdefault((layer, label), set()).add(rel)
    stack_list = [{"layer": k[0], "tech": k[1], "evidence": sorted(v)[:3]} for k, v in stack.items()]
    order = ["Frontend / full-stack", "Backend / full-stack", "Frontend", "Backend / API", "Backend / app",
             "API", "Routing", "State", "Data fetching", "Database / ORM", "Database", "Backend-as-a-service",
             "Cache / queue", "Auth", "Validation", "AI", "Data / ML", "Mobile", "Desktop", "Styling",
             "UI kit", "Language", "Build tool", "Monorepo", "Testing", "Infra", "Service (docker)",
             "Hosting", "CI/CD"]
    stack_list.sort(key=lambda s: (order.index(s["layer"]) if s["layer"] in order else 99, s["tech"]))
    # de-duplicate same tech label
    seen, deduped = set(), []
    for s in stack_list:
        if s["tech"] in seen:
            continue
        seen.add(s["tech"])
        deduped.append(s)
    return manifests, deduped


# --------------------------------------------------------------------------
# Import graph
# --------------------------------------------------------------------------

JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte", ".astro")
JS_IMPORT_RES = [
    re.compile(r"""(?:^|[;\s}])(?:import|export)\s[^'"`;]*?\sfrom\s*['"]([^'"\n]+)['"]"""),
    re.compile(r"""(?:^|[;\s])import\s*['"]([^'"\n]+)['"]"""),
    re.compile(r"""\brequire\(\s*['"]([^'"\n]+)['"]\s*\)"""),
    re.compile(r"""\bimport\(\s*['"]([^'"\n]+)['"]\s*\)"""),
]
STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"os", "sys", "re", "json", "typing", "time", "logging"}


class Graph:
    def __init__(self, root: str, files):
        self.root = root
        self.files = files
        self.fileset = set(files)
        self.edges = defaultdict(set)  # src -> {dst}
        self.ts_configs = {}
        self.py_modules = {}
        self.go_module = None
        self.go_root = ""
        self.java_index = {}

    # ---- setup -----------------------------------------------------------
    def prepare(self):
        for rel in self.files:
            name = rel.rsplit("/", 1)[-1]
            if re.fullmatch(r"(tsconfig|jsconfig)(\.[\w-]+)?\.json", name):
                data = load_json(os.path.join(self.root, rel)) or {}
                co = data.get("compilerOptions") or {}
                if not isinstance(co, dict) or not (co.get("paths") or co.get("baseUrl")):
                    continue
                d = rel.rsplit("/", 1)[0] if "/" in rel else ""
                existing = self.ts_configs.get(d)
                if existing and existing["paths"] and not co.get("paths"):
                    continue
                bu = co.get("baseUrl")
                base = posix(os.path.normpath(os.path.join(d, bu))) if bu else d
                if base == ".":
                    base = ""
                self.ts_configs[d] = {"baseUrl": base if bu else None,
                                      "paths": co.get("paths") or {}, "pathsBase": base}
            elif name == "go.mod":
                txt = read_text(os.path.join(self.root, rel)) or ""
                m = re.search(r"^module\s+(\S+)", txt, re.M)
                if m and (self.go_module is None or rel.count("/") < self.go_root.count("/")):
                    self.go_module = m.group(1)
                    self.go_root = rel.rsplit("/", 1)[0] if "/" in rel else ""
        # python module index
        for rel in self.files:
            if not rel.endswith(".py"):
                continue
            parts = rel[:-3].split("/")
            is_init = parts[-1] == "__init__"
            mod_parts = parts[:-1] if is_init else parts
            # root-relative key
            keys = set()
            if mod_parts:
                keys.add(".".join(mod_parts))
            # key relative to nearest non-package ancestor
            dir_parts = parts[:-1]
            i = len(dir_parts)
            while i > 0 and ("/".join(dir_parts[:i]) + "/__init__.py") in self.fileset:
                i -= 1
            rel_key = mod_parts[i:]
            if rel_key:
                keys.add(".".join(rel_key))
            # common source roots
            for prefix in ("src", "lib", "app", "python"):
                if mod_parts and mod_parts[0] == prefix and len(mod_parts) > 1:
                    keys.add(".".join(mod_parts[1:]))
            for k in keys:
                if k in STDLIB:
                    continue
                self.py_modules.setdefault(k, rel)
        # java / kotlin index: package path suffix
        for rel in self.files:
            if rel.endswith((".java", ".kt")):
                m = re.search(r"(?:^|/)(?:java|kotlin)/(.+)\.(?:java|kt)$", rel)
                if m:
                    self.java_index[m.group(1).replace("/", ".")] = rel

    # ---- resolution ------------------------------------------------------
    def _nearest_ts(self, rel: str):
        d = rel.rsplit("/", 1)[0] if "/" in rel else ""
        while True:
            if d in self.ts_configs:
                return self.ts_configs[d]
            if not d:
                return None
            d = d.rsplit("/", 1)[0] if "/" in d else ""

    def _try_js(self, base: str):
        base = posix(os.path.normpath(base)) if base else base
        if base.startswith("../"):
            return None
        cands = [base]
        if base.endswith((".js", ".jsx", ".mjs", ".cjs")):
            stem = base.rsplit(".", 1)[0]
            cands += [stem + e for e in (".ts", ".tsx", ".mts", ".cts")]
        cands += [base + e for e in JS_EXTS + (".json", ".d.ts")]
        cands += [f"{base}/index{e}" for e in JS_EXTS]
        for c in cands:
            if c in self.fileset:
                return c
        return None

    def resolve_js(self, src: str, spec: str):
        spec = spec.split("?")[0]
        src_dir = src.rsplit("/", 1)[0] if "/" in src else ""
        if spec.startswith("."):
            return self._try_js(os.path.join(src_dir, spec))
        cfg = self._nearest_ts(src)
        if cfg:
            for alias, targets in cfg["paths"].items():
                a_pre = alias[:-1] if alias.endswith("*") else alias
                if (alias.endswith("*") and spec.startswith(a_pre)) or spec == alias:
                    rest = spec[len(a_pre):] if alias.endswith("*") else ""
                    for t in targets:
                        t_pre = t[:-1] if t.endswith("*") else t
                        hit = self._try_js(os.path.join(cfg["pathsBase"], t_pre + rest))
                        if hit:
                            return hit
            if cfg["baseUrl"] is not None:
                hit = self._try_js(os.path.join(cfg["baseUrl"], spec))
                if hit:
                    return hit
        for pre in ("@/", "~/", "#/"):
            if spec.startswith(pre):
                for base in ("src", "", "app"):
                    hit = self._try_js(os.path.join(base, spec[len(pre):]))
                    if hit:
                        return hit
        if spec.startswith("/"):
            return self._try_js(spec.lstrip("/"))
        return None

    def resolve_py(self, src: str, module: str | None, names, level: int):
        if level:
            pkg = src.rsplit("/", 1)[0].split("/") if "/" in src else []
            if level > 1:
                pkg = pkg[: len(pkg) - (level - 1)] if level - 1 <= len(pkg) else []
            base = "/".join(pkg)
            mod_path = (base + "/" if base else "") + (module.replace(".", "/") if module else "")
            mod_path = mod_path.rstrip("/")
            pre = mod_path + "/" if mod_path else ""
            out = []
            for n in names:
                for c in (f"{pre}{n}.py", f"{pre}{n}/__init__.py"):
                    if c in self.fileset:
                        out.append(c)
                        break
            if not out and mod_path:
                for c in (mod_path + ".py", mod_path + "/__init__.py"):
                    if c in self.fileset:
                        out.append(c)
                        break
            return out
        out = []
        if module:
            for n in names:
                full = f"{module}.{n}"
                if full in self.py_modules:
                    out.append(self.py_modules[full])
            if not out:
                parts = module.split(".")
                for i in range(len(parts), 0, -1):
                    k = ".".join(parts[:i])
                    if k in self.py_modules:
                        out.append(self.py_modules[k])
                        break
        return out

    # ---- per-language extraction ----------------------------------------
    def scan_file(self, rel: str, text: str):
        ext = ext_of(rel)
        targets = set()
        if ext in JS_EXTS:
            for rx in JS_IMPORT_RES:
                for m in rx.finditer(text):
                    hit = self.resolve_js(rel, m.group(1))
                    if hit:
                        targets.add(hit)
        elif ext == ".py":
            try:
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for a in node.names:
                            targets.update(self.resolve_py(rel, a.name, [], 0))
                    elif isinstance(node, ast.ImportFrom):
                        names = [a.name for a in node.names if a.name != "*"]
                        targets.update(self.resolve_py(rel, node.module, names, node.level or 0))
            except (SyntaxError, ValueError, RecursionError):
                for m in re.finditer(r"^\s*(?:from\s+([\w.]+)\s+import\s+([\w, ]+)|import\s+([\w.]+))", text, re.M):
                    if m.group(3):
                        targets.update(self.resolve_py(rel, m.group(3), [], 0))
                    else:
                        lvl = len(m.group(1)) - len(m.group(1).lstrip("."))
                        mod = m.group(1).lstrip(".") or None
                        names = [n.strip() for n in m.group(2).split(",") if n.strip()]
                        targets.update(self.resolve_py(rel, mod, names, lvl))
        elif ext == ".go" and self.go_module:
            blocks = re.findall(r"^import\s*\((.*?)^\)", text, re.S | re.M)
            specs = re.findall(r'"([^"]+)"', " ".join(blocks)) + re.findall(r'^import\s+(?:\w+\s+)?"([^"]+)"', text, re.M)
            for spec in specs:
                if spec == self.go_module or spec.startswith(self.go_module + "/"):
                    sub = spec[len(self.go_module):].lstrip("/")
                    d = "/".join(p for p in (self.go_root, sub) if p)
                    targets.add(d + "/" if d else "./")
        elif ext in {".java", ".kt"}:
            for m in re.finditer(r"^\s*import\s+(?:static\s+)?([\w.]+)", text, re.M):
                name = m.group(1)
                while name:
                    if name in self.java_index:
                        targets.add(self.java_index[name])
                        break
                    name = name.rsplit(".", 1)[0] if "." in name else ""
        elif ext == ".rb":
            src_dir = rel.rsplit("/", 1)[0] if "/" in rel else ""
            for m in re.finditer(r"""require_relative\s*\(?\s*['"]([^'"]+)['"]""", text):
                p = posix(os.path.normpath(os.path.join(src_dir, m.group(1))))
                for c in (p, p + ".rb"):
                    if c in self.fileset:
                        targets.add(c)
        elif ext == ".rs":
            src_dir = rel.rsplit("/", 1)[0] if "/" in rel else ""
            for m in re.finditer(r"^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)\s*;", text, re.M):
                stem = rel.rsplit("/", 1)[-1][:-3]
                base = src_dir if stem in {"main", "lib", "mod"} else f"{src_dir}/{stem}".lstrip("/")
                for c in (f"{base}/{m.group(1)}.rs".lstrip("/"), f"{base}/{m.group(1)}/mod.rs".lstrip("/")):
                    if c in self.fileset:
                        targets.add(c)
            for m in re.finditer(r"\buse\s+crate::([\w:]+)", text):
                crate_src = rel.split("/src/")[0] + "/src" if "/src/" in rel else "src"
                parts = m.group(1).split("::")
                for i in range(len(parts), 0, -1):
                    p = crate_src + "/" + "/".join(parts[:i])
                    hit = next((c for c in (p + ".rs", p + "/mod.rs") if c in self.fileset), None)
                    if hit:
                        targets.add(hit)
                        break
        targets.discard(rel)
        if targets:
            self.edges[rel].update(targets)


# --------------------------------------------------------------------------
# Routes, env vars, entry points
# --------------------------------------------------------------------------

ROUTE_RES = [
    ("express", re.compile(r"""\b(?:app|router|server|api|route|routes|r|v1|v2)\.(get|post|put|patch|delete|all|use|route)\(\s*['"`]([^'"`]+)['"`]""")),
    ("decorator", re.compile(r"""@\w+\.(get|post|put|patch|delete|route|websocket|api_route)\(\s*['"]([^'"]*)['"]""")),
    ("django", re.compile(r"""\b(?:re_)?path\(\s*r?['"]([^'"]*)['"]""")),
    ("laravel", re.compile(r"""Route::(get|post|put|patch|delete|any|resource|apiResource|match)\(\s*['"]([^'"]+)['"]""")),
    ("spring", re.compile(r"""@(Get|Post|Put|Delete|Patch|Request)Mapping\(\s*(?:value\s*=\s*|path\s*=\s*)?\{?\s*["']([^"']*)["']""")),
    ("go", re.compile(r"""\.(GET|POST|PUT|PATCH|DELETE|Get|Post|Put|Patch|Delete|HandleFunc|Handle|Group|Route)\(\s*"([^"]+)\"""")),
    ("rails", re.compile(r"""^\s*(get|post|put|patch|delete|resources|resource|root|namespace|scope)\s+\(?\s*['":]?([\w/:\-\.]+)""", re.M)),
]

ENV_RES = [
    re.compile(r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"process\.env\[\s*['\"]([A-Za-z0-9_]+)['\"]"),
    re.compile(r"import\.meta\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"Deno\.env\.get\(\s*['\"]([A-Za-z0-9_]+)['\"]"),
    re.compile(r"os\.environ(?:\.get)?\(\s*['\"]([A-Za-z0-9_]+)['\"]"),
    re.compile(r"os\.environ\[\s*['\"]([A-Za-z0-9_]+)['\"]"),
    re.compile(r"os\.getenv\(\s*['\"]([A-Za-z0-9_]+)['\"]"),
    re.compile(r"\benv\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]"),
    re.compile(r"\bgetenv\(\s*['\"]([A-Za-z0-9_]+)['\"]"),
    re.compile(r"ENV\[\s*['\"]([A-Za-z0-9_]+)['\"]\s*\]"),
    re.compile(r"ENV\.fetch\(\s*['\"]([A-Za-z0-9_]+)['\"]"),
    re.compile(r"os\.(?:Getenv|LookupEnv)\(\s*\"([A-Za-z0-9_]+)\""),
    re.compile(r"env::var(?:_os)?\(\s*\"([A-Za-z0-9_]+)\""),
    re.compile(r"System\.getenv\(\s*\"([A-Za-z0-9_]+)\""),
    re.compile(r"Environment\.GetEnvironmentVariable\(\s*\"([A-Za-z0-9_]+)\""),
    re.compile(r"\$\{([A-Z][A-Z0-9_]+)(?::[^}]*)?\}"),  # docker-compose / spring placeholders
]
ENV_IGNORE = {"NODE_ENV_", "HOME", "PATH", "PWD", "USER", "SHELL", "TERM", "CI", "LANG", "TMPDIR"}

ENTRY_NAMES = [
    (r"(^|/)__main__\.py$", "Python package entry (python -m)"),
    (r"^manage\.py$", "Django management entry"),
    (r"(^|/)(wsgi|asgi)\.py$", "WSGI/ASGI server entry"),
    (r"^(src/)?(main|app|server|run|application|wsgi|cli|bot)\.py$", "Python app entry (by name)"),
    (r"^(src/)?(server|app|index|main)\.(c|m)?[jt]s$", "Node entry (by name)"),
    (r"^(src/)?main\.[jt]sx?$", "Frontend bootstrap (mounts the app)"),
    (r"^(src/)?index\.[jt]sx$", "Frontend bootstrap (mounts the app)"),
    (r"^(src/)?App\.(tsx|jsx|vue|svelte)$", "Root UI component"),
    (r"^index\.html$", "HTML shell loaded by the browser"),
    (r"(^|/)(src/)?app/layout\.(tsx|jsx|js|ts)$", "Next.js root layout"),
    (r"(^|/)(src/)?app/page\.(tsx|jsx|js|ts|mdx)$", "Next.js home page"),
    (r"(^|/)(src/)?pages/_app\.(tsx|jsx|js|ts)$", "Next.js app wrapper"),
    (r"(^|/)(src/)?pages/index\.(tsx|jsx|js|ts|vue)$", "Home page"),
    (r"(^|/)src/routes/\+layout\.svelte$", "SvelteKit root layout"),
    (r"(^|/)app/root\.(tsx|jsx)$", "Remix root"),
    (r"(^|/)nuxt\.config\.[jt]s$", "Nuxt config / entry"),
    (r"(^|/)cmd/[^/]+/main\.go$", "Go binary entry"),
    (r"^main\.go$", "Go binary entry"),
    (r"(^|/)src/main\.rs$", "Rust binary entry"),
    (r"(^|/)src/lib\.rs$", "Rust library root"),
    (r"(^|/)src/bin/[^/]+\.rs$", "Rust extra binary"),
    (r"(^|/)lib/main\.dart$", "Flutter entry"),
    (r"(^|/)Program\.cs$", ".NET entry"),
    (r"(^|/)config/routes\.rb$", "Rails routes table"),
    (r"^config\.ru$", "Rack entry"),
    (r"^(public/)?index\.php$", "PHP front controller"),
    (r"(^|/)routes/(web|api)\.php$", "Laravel routes"),
    (r"(^|/)electron/main\.[jt]s$|(^|/)main/index\.[jt]s$", "Electron main process"),
    (r"(^|/)Dockerfile$", "Container build (how the app is packaged)"),
    (r"(^|/)docker-compose\.ya?ml$|^compose\.ya?ml$", "Multi-service local stack"),
]


def find_routes(rel: str, text: str):
    out = []
    name = rel.rsplit("/", 1)[-1]
    for kind, rx in ROUTE_RES:
        if kind == "django" and not name.startswith("urls"):
            continue
        if kind == "rails" and not rel.endswith("config/routes.rb"):
            continue
        if kind == "express" and not ext_of(rel) in JS_EXTS:
            continue
        if kind == "decorator" and ext_of(rel) != ".py":
            continue
        if kind == "go" and ext_of(rel) != ".go":
            continue
        if kind == "spring" and ext_of(rel) not in {".java", ".kt"}:
            continue
        if kind == "laravel" and not rel.endswith(".php"):
            continue
        for m in rx.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            if kind == "django":
                out.append(("ANY", "/" + m.group(1).lstrip("^").rstrip("$"), rel, line))
            else:
                method, path = m.group(1).upper(), m.group(2)
                if kind == "express" and method == "USE" and not path.startswith("/"):
                    continue
                if kind == "go" and not path.startswith("/"):
                    continue
                if kind == "rails" and method in {"RESOURCES", "RESOURCE", "NAMESPACE", "SCOPE"}:
                    path = path.lstrip(":")
                out.append((method, path, rel, line))
    return out


def file_routes(files, techs):
    """Routes implied by file-system routing (Next.js, Nuxt, SvelteKit, Remix)."""
    out = []
    app_roots = {rel.rsplit("/", 1)[0] + "/" if "/" in rel else "" for rel in files
                 if rel.endswith("package.json")}
    nextish = any(t in techs for t in ("Next.js", "Nuxt"))
    remix = "Remix" in techs
    nuxt = "Nuxt" in techs

    def at_app_root(prefix):
        prefix = prefix[:-4] if prefix.endswith("src/") else prefix
        return prefix in app_roots or prefix == ""

    for rel in files:
        m = re.match(r"^(.*?)app/(?:(.*)/)?(page|route)\.(tsx|jsx|js|ts|mdx)$", rel)
        if m and at_app_root(m.group(1)) and "Next.js" in techs:
            segs = [s for s in (m.group(2) or "").split("/")
                    if s and not (s.startswith("(") and s.endswith(")")) and not s.startswith("@")]
            out.append(("API" if m.group(3) == "route" else "PAGE", "/" + "/".join(segs), rel, 1))
            continue
        m = re.match(r"^(.*?)pages/(.+)\.(tsx|jsx|js|ts|vue|mdx)$", rel)
        if m and nextish and at_app_root(m.group(1)) and not m.group(2).split("/")[-1].startswith("_"):
            p = re.sub(r"(^|/)index$", "", m.group(2))
            out.append(("API" if p.startswith("api/") or p == "api" else "PAGE", "/" + p, rel, 1))
            continue
        m = re.match(r"^(?:.*/)?src/routes/(?:(.*)/)?\+(page|server)\.(svelte|ts|js)$", rel)
        if m:
            out.append(("API" if m.group(2) == "server" else "PAGE", "/" + (m.group(1) or ""), rel, 1))
            continue
        m = re.match(r"^(.*?)server/(api|routes)/(.+)\.(ts|js)$", rel)
        if m and nuxt and at_app_root(m.group(1)):
            out.append(("API", "/" + ("api/" if m.group(2) == "api" else "") + re.sub(r"(^|/)index$", "", m.group(3)), rel, 1))
            continue
        m = re.match(r"^(.*?)app/routes/(.+)\.(tsx|jsx|ts|js)$", rel)
        if m and remix and at_app_root(m.group(1)):
            out.append(("ROUTE", "/" + m.group(2).replace(".", "/").replace("_index", ""), rel, 1))
    return out


def build_groups(paths, max_groups: int = 24):
    """Adaptively split folders into ~max_groups architecture 'boxes'."""
    current = {"": list(paths)}
    total = max(len(paths), 1)
    for _ in range(500):
        acted = False
        for g, fs in sorted(current.items(), key=lambda kv: -len(kv[1])):
            children, direct = defaultdict(list), []
            for p in fs:
                rest = p[len(g) + 1:] if g else p
                if "/" in rest:
                    children[(g + "/" if g else "") + rest.split("/", 1)[0]].append(p)
                else:
                    direct.append(p)
            if len(children) == 1 and not direct:
                (child, cfs), = children.items()
                del current[g]
                current[child] = cfs
                acted = True
                break
            n_new = len(children) + (1 if direct else 0)
            if n_new <= 1 or len(current) - 1 + n_new > max_groups:
                continue
            if len(fs) < max(4, 0.08 * total):
                continue
            del current[g]
            current.update(children)
            if direct:
                current[g] = direct
            acted = True
            break
        if not acted:
            break
    file_map = {p: g for g, fs in current.items() for p in fs}
    return current, file_map


def group_lookup(path: str, groups, file_map) -> str:
    if path in file_map:
        g = file_map[path]
    else:
        g = ""
        for cand in groups:
            if cand and (path == cand or path.startswith(cand + "/")) and len(cand) > len(g):
                g = cand
    return g or "(root)"


# --------------------------------------------------------------------------
# Main analysis
# --------------------------------------------------------------------------


def analyze(root: str, focus: str | None):
    root = os.path.abspath(root)
    gi = git_info(root)
    files = list_files(root, gi is not None)
    focus_prefix = posix(focus).strip("/") + "/" if focus else None

    info = {}
    for rel in files:
        ab = os.path.join(root, rel)
        kind = classify(rel)
        lang = language(rel)
        lines = count_lines(ab) if kind not in {"asset"} else 0
        info[rel] = {"path": rel, "kind": kind, "lang": lang, "lines": lines, "fan_in": 0, "fan_out": 0}

    manifests, stack = analyze_manifests(root, files)

    graph = Graph(root, files)
    graph.prepare()
    routes, env = [], defaultdict(set)
    entry = {}
    readable_kinds = {"source", "script", "config", "test", "migration", "ci", "schema"}
    for rel in files:
        meta = info[rel]
        if meta["kind"] not in readable_kinds:
            continue
        text = read_text(os.path.join(root, rel))
        if text is None:
            continue
        if meta["kind"] in {"source", "script", "test", "migration"}:
            graph.scan_file(rel, text)
        if meta["kind"] in {"source", "script"}:
            routes.extend(find_routes(rel, text))
            if ext_of(rel) == ".py" and re.search(r"""^if\s+__name__\s*==\s*['"]__main__['"]""", text, re.M):
                entry.setdefault(rel, "Runs as a script (`if __name__ == \"__main__\"`)")
            if ext_of(rel) == ".go" and re.search(r"^package\s+main\b", text, re.M) and "func main(" in text:
                entry.setdefault(rel, "Go `package main` with `func main()`")
            if ext_of(rel) in {".java", ".kt"} and ("@SpringBootApplication" in text or "static void main(" in text or re.search(r"^fun main\(", text, re.M)):
                entry.setdefault(rel, "JVM application entry (`main`)")
            if ext_of(rel) == ".swift" and re.search(r"^@main\b", text, re.M):
                entry.setdefault(rel, "Swift app entry (`@main`)")
            if ext_of(rel) in JS_EXTS and re.search(r"\.listen\(\s*[\w.]*(?:port|PORT|\d{2,5})", text):
                entry.setdefault(rel, "Starts the HTTP server (`.listen(...)`)")
            if ext_of(rel) in JS_EXTS and re.search(r"(createRoot|ReactDOM\.render|hydrateRoot|createApp\(|new Vue\(|bootstrapApplication|platformBrowserDynamic|mount\()", text) \
                    and re.search(r"\.(render|mount)\(|bootstrapApplication|bootstrapModule", text):
                entry.setdefault(rel, "Mounts the UI into the page")
        if meta["kind"] in {"source", "script", "config", "ci"}:
            for rx in ENV_RES:
                for m in rx.finditer(text):
                    var = m.group(1)
                    if var in ENV_IGNORE or len(var) < 2:
                        continue
                    if rx.pattern.startswith(r"\$\{") and not re.search(r"(compose|application|\.ya?ml|\.properties|\.env)", rel):
                        continue
                    env[var].add(rel)
    # env example files: names only
    for rel in files:
        name = rel.rsplit("/", 1)[-1]
        if re.fullmatch(r"\.env\.(example|sample|template|dist|defaults|local\.example)|env\.example|example\.env|\.env\.development|\.env\.test", name):
            txt = read_text(os.path.join(root, rel)) or ""
            for var in re.findall(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", txt, re.M):
                env[var].add(rel)
    routes.extend(file_routes(files, {s["tech"] for s in stack}))

    # entry points by name & manifest
    for rel in files:
        for pat, why in ENTRY_NAMES:
            if re.search(pat, rel):
                entry.setdefault(rel, why)
                break
    for man in manifests:
        if man.get("type") == "npm":
            base = man["file"].rsplit("/", 1)[0] if "/" in man["file"] else ""
            cands = []
            if man.get("main"):
                cands.append((man["main"], "package.json `main`"))
            b = man.get("bin")
            if isinstance(b, str):
                cands.append((b, "package.json `bin` (CLI)"))
            elif isinstance(b, dict):
                cands += [(v, f"package.json `bin` → `{k}` (CLI)") for k, v in b.items()]
            for sname in ("start", "dev", "serve"):
                cmd = (man.get("scripts") or {}).get(sname) or ""
                for tok in re.findall(r"[\w./\-]+\.(?:[cm]?[jt]sx?)", cmd):
                    cands.append((tok, f"npm script `{sname}`"))
            for p, why in cands:
                p = posix(os.path.normpath(os.path.join(base, p)))
                for c in (p, p.replace("dist/", "src/").rsplit(".", 1)[0] + ".ts", p.replace("build/", "src/").rsplit(".", 1)[0] + ".ts"):
                    if c in info:
                        entry[c] = why
                        break
        if man.get("type") == "python":
            for sname, target in (man.get("scripts") or {}).items():
                if isinstance(target, str) and ":" in target:
                    mod = target.split(":")[0]
                    hit = graph.py_modules.get(mod)
                    if hit:
                        entry[hit] = f"console script `{sname}` (pyproject)"

    # fan-in / fan-out
    pkg_fan_in = Counter()
    for src, dsts in graph.edges.items():
        if src in info:
            info[src]["fan_out"] = len(dsts)
        for d in dsts:
            if d in info:
                info[d]["fan_in"] += 1
            elif d.endswith("/"):
                pkg_fan_in[d] += 1

    # focus filter
    def in_focus(p):
        return focus_prefix is None or p.startswith(focus_prefix)

    scoped = [p for p in files if in_focus(p)]
    code_paths = [p for p in scoped if info[p]["kind"] in {"source", "script"}]
    groups, file_map = build_groups(code_paths or scoped)
    group_edges = Counter()
    for src, dsts in graph.edges.items():
        if not in_focus(src) or info.get(src, {}).get("kind") not in {"source", "script"}:
            continue
        g1 = group_lookup(src, groups, file_map)
        for d in dsts:
            g2 = group_lookup(d.rstrip("/") if d != "./" else "", groups, file_map)
            if g1 != g2 and in_focus(d):
                group_edges[(g1, g2)] += 1
    group_sizes = Counter(group_lookup(p, groups, file_map) for p in code_paths)

    # orphans: source files with nothing importing them
    graph_langs = {".py", ".go", ".java", ".kt", ".rb", ".rs"} | set(JS_EXTS)
    orphans = [p for p in code_paths if info[p]["fan_in"] == 0 and p not in entry
               and ext_of(p) in graph_langs and not p.endswith(("__init__.py", ".d.ts"))
               and info[p]["kind"] == "source"
               and not re.search(r"(^|/)(pages|app|routes|views|controllers|commands|migrations|handlers|api)/", p)
               and not re.search(r"\.(config|stories)\.", p)
               and not re.search(r"(^|/)(middleware|instrumentation|setup|conftest)\.[a-z]+$", p)]

    return {
        "root": root, "name": os.path.basename(root.rstrip("/")), "git": gi, "focus": focus,
        "files": [info[p] for p in scoped], "all_file_count": len(files),
        "manifests": manifests, "stack": stack,
        "entry_points": [{"path": p, "why": w} for p, w in sorted(entry.items(), key=lambda x: (x[0].count("/"), x[0])) if in_focus(p)],
        "edges": {s: sorted(d) for s, d in graph.edges.items() if in_focus(s)},
        "groups": [{"group": g, "code_files": n} for g, n in group_sizes.most_common()],
        "group_edges": [{"from": a, "to": b, "imports": n} for (a, b), n in group_edges.most_common()],
        "go_packages": [{"package": p, "imported_by": n} for p, n in pkg_fan_in.most_common()],
        "routes": [{"method": m, "path": p, "file": f, "line": ln} for m, p, f, ln in routes if in_focus(f)],
        "env": {k: sorted(v) for k, v in sorted(env.items())},
        "orphans": orphans,
    }


# --------------------------------------------------------------------------
# Markdown rendering
# --------------------------------------------------------------------------


def render(r, max_list: int) -> str:
    L = []
    files = r["files"]
    total_lines = sum(f["lines"] for f in files)
    kinds = Counter(f["kind"] for f in files)
    g = r["git"]
    L.append(f"# Repo scan: {r['name']}")
    meta = [f"root `{r['root']}`"]
    if g:
        meta.append(f"git `{g.get('branch')}` @ `{g.get('commit')}` ({g.get('last_commit_date')})")
        if g.get("remote"):
            meta.append(f"remote `{g['remote']}`")
    if r["focus"]:
        meta.append(f"focus `{r['focus']}`")
    L.append(" · ".join(meta))
    L.append("")
    L.append(f"**{len(files)} files** ({r['all_file_count']} in repo), **{total_lines:,} lines**. "
             "By kind: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common()) + ".")
    L.append("")

    # languages
    lang_lines, lang_files = Counter(), Counter()
    for f in files:
        if f["kind"] in {"asset", "lock/generated"}:
            continue
        lang_lines[f["lang"]] += f["lines"]
        lang_files[f["lang"]] += 1
    L.append("## Languages")
    L.append("| Language | Files | Lines | Share |")
    L.append("|---|---:|---:|---:|")
    tot = sum(lang_lines.values()) or 1
    for lang, n in lang_lines.most_common(12):
        L.append(f"| {lang} | {lang_files[lang]} | {n:,} | {100 * n / tot:.0f}% |")
    L.append("")

    L.append("## Stack detected")
    if r["stack"]:
        L.append("| Layer | Tech | Evidence |")
        L.append("|---|---|---|")
        for s in r["stack"]:
            L.append(f"| {s['layer']} | {s['tech']} | " + ", ".join(f"`{e}`" for e in s["evidence"]) + " |")
    else:
        L.append("_Nothing recognised automatically - read the manifests and entry points._")
    L.append("")

    L.append("## Manifests, scripts & services")
    if not r["manifests"]:
        L.append("_No manifests found._")
    for m in r["manifests"]:
        head = f"- `{m['file']}` ({m['type']})"
        if m.get("name"):
            head += f" - name **{m['name']}**"
        if m.get("description"):
            head += f": {md_escape(m['description'])[:160]}"
        L.append(head)
        if m.get("scripts"):
            for k, v in list(m["scripts"].items())[:15]:
                L.append(f"  - script `{k}` → `{md_escape(v)[:140]}`")
        if m.get("targets"):
            L.append("  - targets: " + ", ".join(f"`{t}`" for t in m["targets"][:25]))
        if m.get("services"):
            L.append("  - services: " + ", ".join(f"`{s}`" for s in m["services"]))
        if m.get("processes"):
            for k, v in m["processes"].items():
                L.append(f"  - process `{k}` → `{md_escape(v)}`")
        if m.get("workspaces") or m.get("workspace"):
            L.append(f"  - workspaces: `{m.get('workspaces') or m.get('workspace')}`")
        deps = m.get("dependencies") or []
        if deps:
            shown = ", ".join(deps[:30]) + (f", … (+{len(deps) - 30})" if len(deps) > 30 else "")
            L.append(f"  - deps ({len(deps)}): {shown}")
        if m.get("devDependencies"):
            dd = m["devDependencies"]
            L.append(f"  - devDeps ({len(dd)}): " + ", ".join(dd[:20]) + (" …" if len(dd) > 20 else ""))
    L.append("")

    L.append("## Likely entry points")
    if r["entry_points"]:
        for e in r["entry_points"][:30]:
            L.append(f"- `{e['path']}` - {e['why']}")
    else:
        L.append("_None found by heuristics - check README and manifests._")
    L.append("")

    # folders
    L.append("## Top-level folders")
    L.append("| Folder | Files | Lines | Main language | Kinds |")
    L.append("|---|---:|---:|---|---|")
    top = defaultdict(list)
    for f in files:
        parts = f["path"].split("/")
        top[parts[0] + "/" if len(parts) > 1 else "(root files)"].append(f)
    for folder, fs in sorted(top.items(), key=lambda kv: -sum(x["lines"] for x in kv[1])):
        langs = Counter(x["lang"] for x in fs if x["kind"] not in {"asset", "lock/generated"})
        ks = Counter(x["kind"] for x in fs)
        L.append(f"| `{folder}` | {len(fs)} | {sum(x['lines'] for x in fs):,} | "
                 f"{langs.most_common(1)[0][0] if langs else '-'} | " + ", ".join(f"{k} {v}" for k, v in ks.most_common(4)) + " |")
    L.append("")

    L.append("## Architecture groups and dependencies")
    L.append("_Source folders grouped into diagram-sized boxes. Use the groups as nodes and the edges as arrows "
             "in the architecture diagram. `A → B` means code in A imports code in B._")
    if r["groups"]:
        L.append("")
        L.append("Groups (source files): " + ", ".join(f"`{g['group']}` ({g['code_files']})" for g in r["groups"]))
        L.append("")
    if r["group_edges"]:
        for e in r["group_edges"][:40]:
            L.append(f"- `{e['from']}` → `{e['to']}` ({e['imports']} imports)")
    else:
        L.append("_No internal imports resolved (single-folder project, or a language the scanner does not parse)._")
    L.append("")

    hubs = sorted([f for f in files if f["fan_in"] > 0], key=lambda f: -f["fan_in"])[:20]
    L.append("## Hub files (imported by the most other files)")
    if hubs or r["go_packages"]:
        rev = defaultdict(list)
        for s, ds in r["edges"].items():
            for d in ds:
                rev[d].append(s)
        L.append("| File | Imported by | Examples of importers |")
        L.append("|---|---:|---|")
        for f in hubs:
            ex = ", ".join(f"`{x}`" for x in sorted(rev.get(f["path"], []))[:3])
            L.append(f"| `{f['path']}` | {f['fan_in']} | {ex} |")
        for p in r["go_packages"][:15]:
            L.append(f"| `{p['package']}` (Go package) | {p['imported_by']} | |")
    else:
        L.append("_No internal imports resolved._")
    L.append("")

    L.append("## Routes / endpoints found")
    if r["routes"]:
        L.append("| Method | Path | Defined in |")
        L.append("|---|---|---|")
        seen = set()
        for rt in r["routes"]:
            key = (rt["method"], rt["path"], rt["file"])
            if key in seen:
                continue
            seen.add(key)
            L.append(f"| {rt['method']} | `{md_escape(rt['path'])}` | `{rt['file']}:{rt['line']}` |")
            if len(seen) >= 80:
                L.append(f"| … | _{len(r['routes']) - 80} more_ | |")
                break
    else:
        L.append("_No routes detected._")
    L.append("")

    L.append("## Environment variables (names only)")
    if r["env"]:
        L.append("| Variable | Read / declared in |")
        L.append("|---|---|")
        for k, v in list(r["env"].items())[:80]:
            L.append(f"| `{k}` | " + ", ".join(f"`{x}`" for x in v[:4]) + (" …" if len(v) > 4 else "") + " |")
    else:
        L.append("_None detected._")
    L.append("")

    if r["orphans"]:
        L.append("## Source files nothing imports (check: dead code, dynamic loading, or framework convention)")
        L.append(", ".join(f"`{p}`" for p in r["orphans"][:30]) + (" …" if len(r["orphans"]) > 30 else ""))
        L.append("")

    L.append("## File inventory")
    L.append("_kind: source, script, config, test, docs, schema, database, migration, style, ci, data, asset, lock/generated, other. "
             "in = files that import it, out = files it imports._")
    L.append("")
    by_dir = defaultdict(list)
    for f in files:
        by_dir[f["path"].rsplit("/", 1)[0] + "/" if "/" in f["path"] else "./"].append(f)
    shown = 0
    truncated = False
    for d in sorted(by_dir):
        rows = by_dir[d]
        L.append(f"### `{d}`")
        L.append("| File | Kind | Lang | Lines | In | Out |")
        L.append("|---|---|---|---:|---:|---:|")
        for f in rows:
            if shown >= max_list:
                truncated = True
                break
            L.append(f"| `{f['path']}` | {f['kind']} | {f['lang']} | {f['lines']} | {f['fan_in']} | {f['fan_out']} |")
            shown += 1
        L.append("")
        if truncated:
            break
    if truncated:
        L.append(f"_Inventory truncated at {max_list} of {len(files)} files. Re-run with `--max-list {len(files)}` "
                 "or `--json scan.json`, or narrow with `--focus <folder>`._")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Inventory a codebase for the codebase-explainer skill.")
    ap.add_argument("root", nargs="?", default=".", help="repository root (default: current directory)")
    ap.add_argument("--focus", help="only report on this sub-folder (imports are still resolved repo-wide)")
    ap.add_argument("--json", dest="json_out", help="also write the full result as JSON to this path")
    ap.add_argument("--max-list", type=int, default=600, help="max files to list in the inventory table (default 600)")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.root):
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2
    result = analyze(args.root, args.focus)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, default=list)
    sys.stdout.write(render(result, args.max_list))
    return 0


if __name__ == "__main__":
    sys.exit(main())
