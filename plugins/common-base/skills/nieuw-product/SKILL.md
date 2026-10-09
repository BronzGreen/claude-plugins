---
name: nieuw-product
description: >-
  Reuse-first design for a new BronzGreen project, product, app, module or
  prototype: inventories what BronzGreen/common-base already provides (auth,
  HTTP envelope, PostgreSQL + migrations, mail, events, storage, UI
  components, design tokens, API/auth clients, CI, the product template) and
  pulls it in instead of rebuilding it. Use whenever someone starts, designs,
  scaffolds or plans a new project or a sizeable new feature area — "start a
  new app", "set up a new repo", "design the architecture for X", "build a
  dashboard/portal/API for Y" — before any code or technical design is
  written, and when bringing an existing BronzGreen repo onto common-base.
---

# /common-base:nieuw-product

A new BronzGreen product starts **on** common-base. Nothing it already
provides gets rebuilt, copied or forked.

1. **Get the current common-base.** Use the copy the repo already consumes
   (`go list -m -f '{{.Dir}}' github.com/bronzgreen/common-base`,
   `node_modules/@bronzgreen`), a local clone, or a shallow read-only clone of
   the latest tag: `gh repo clone BronzGreen/common-base "$TMPDIR/common-base" -- --depth 1`.
   Read `README.md`, `CHANGELOG.md`, `template/README.md`, `docs/ci.md` and
   `docs/design-system.md`. Never work from memory: packages get added.
2. **Map the needs.** List what the project needs (login/SSO/MFA, roles,
   multi-tenancy, database, migrations, mail, files, events, background
   jobs, LLM calls, external connectors, UI shell, tables/forms, i18n, PWA,
   CI, e2e). For each, write down the common-base package or component that
   covers it, or "product" when nothing does. Show this table to the user as
   part of the design.
3. **Start from the template** when it is a new product with a Go API and/or
   a Next.js web app: copy `template/` and `compose/` into the new repo,
   rename the module/package/APP, pin one common-base tag in both
   `backend/go.mod` and `web/package.json`, add the `GH_PAT` secret, call the
   reusable workflows. (Details: `template/README.md`.) For a different stack,
   still reuse what applies (design tokens, CI workflows, conventions) and say
   which parts cannot be reused and why.
4. **Pin, don't copy.** Consumers pin a tag: no submodule, no copied files,
   no committed `replace` directive. Product-specific values go in one
   adapter in the product (an options/config file), never in common-base.
5. **Gaps.** For each need with no common-base answer, run
   `/common-base:waar-hoort-dit` on it: a generic gap becomes a common-base PR
   (neutral, an option with a neutral default), everything product-specific
   stays in the product.

Output of the design step: the needs → common-base mapping, the template
decision, the pinned tag, and the list of gaps with their placement verdict.
