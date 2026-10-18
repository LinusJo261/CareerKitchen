import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";
import ts from "typescript";

// Inspect the actual JSX branches without mounting browser-dependent UI controls.
// Stable component type/key plus retained hook state verifies wizard preservation.
function harness() {
  const modules = new Map(),
    cells = [];
  let cursor = 0,
    snapshot,
    retries = 0;
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in cells))
        cells[index] = typeof initial === "function" ? initial() : initial;
      return [
        cells[index],
        (value) => {
          cells[index] =
            typeof value === "function" ? value(cells[index]) : value;
        },
      ];
    },
    useRef(initial) {
      const index = cursor++;
      if (!(index in cells)) cells[index] = { current: initial };
      return cells[index];
    },
    useEffect() {},
  };
  const controls = new Proxy(
    { __esModule: true },
    {
      get: (target, key) =>
        key in target ? target[key] : `mock-${String(key)}`,
    },
  );
  function load(url) {
    const filename = fileURLToPath(url);
    if (modules.has(filename)) return modules.get(filename).exports;
    const module = { exports: {} };
    modules.set(filename, module);
    const source = ts.transpileModule(readFileSync(filename, "utf8"), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
      fileName: filename,
    }).outputText;
    const require = createRequire(url);
    new Function("exports", "require", "module", source)(
      module.exports,
      (name) => {
        if (name === "react") return react;
        if (name === "next/navigation")
          return { useRouter: () => ({ push() {}, refresh() {} }) };
        if (name === "next/link") return { __esModule: true, default: "a" };
        if (name === "@/lib/workspace") return { useWorkspace: () => snapshot };
        if (name.startsWith("@/lib/"))
          return load(new URL(`../${name.slice(2)}.ts`, import.meta.url));
        if (name.startsWith("@/components/") || name === "lucide-react")
          return controls;
        return name.startsWith(".")
          ? load(new URL(`${name}.ts`, url))
          : require(name);
      },
      module,
    );
    return module.exports;
  }
  const { emptyWorkspace } = load(
    new URL("../lib/workspace-types.ts", import.meta.url),
  );
  const candidate = load(
    new URL(
      "../components/onboarding/candidate-onboarding.tsx",
      import.meta.url,
    ),
  ).CandidateOnboarding;
  const employer = load(
    new URL(
      "../components/onboarding/employer-onboarding.tsx",
      import.meta.url,
    ),
  ).EmployerOnboarding;
  return {
    candidate,
    employer,
    set({ signedIn = false, error, isLoading = false, retryError } = {}) {
      const data = emptyWorkspace();
      if (signedIn)
        data.session = { id: "fixture-user", email: "fixture@example.invalid" };
      snapshot = {
        data,
        error,
        isLoading,
        refresh: async () => {
          retries++;
          if (retryError) throw retryError;
        },
      };
    },
    render(component, props = {}) {
      cursor = 0;
      return component(props);
    },
    retries: () => retries,
  };
}
function nodes(value) {
  if (Array.isArray(value)) return value.flatMap(nodes);
  if (!value || typeof value !== "object" || !value.props) return [];
  return [value, ...nodes(value.props.children)];
}
function text(value) {
  if (Array.isArray(value)) return value.map(text).join(" ");
  if (value == null || typeof value === "boolean") return "";
  return typeof value === "object"
    ? text(value.props?.children)
    : String(value);
}
const signIn = (tree) =>
  nodes(tree).find((node) => node.props.href?.startsWith("/sign-in"));
const field = (tree, id) => nodes(tree).find((node) => node.props.id === id);
const error = (status, message) => ({ status, message });

test("initial candidate and employer service failures offer retry instead of asserting expired sign-in", async () => {
  for (const role of ["candidate", "employer"]) {
    const app = harness();
    for (const status of [503, 0]) {
      app.set({ error: error(status, "Service could not be reached") });
      const tree = app.render(app[role]);
      assert.match(text(tree), /temporarily unavailable/);
      assert.match(text(tree), /Service could not be reached/);
      assert.equal(signIn(tree), undefined);
      const retry = nodes(tree).find(
        (node) => node.props.onClick && text(node) === "Try again",
      );
      assert.ok(retry);
      await retry.props.onClick();
    }
    assert.equal(app.retries(), 2);
  }
});
test("initial loading stays a loading state, while 401 and 403 still block cached workspaces", () => {
  for (const role of ["candidate", "employer"]) {
    const app = harness();
    app.set({ isLoading: true });
    assert.match(text(app.render(app[role])), /Loading your account/);
    for (const signedIn of [false, true]) {
      app.set({ signedIn, error: error(401, "Session invalid") });
      assert.ok(signIn(app.render(app[role])));
      app.set({
        signedIn,
        error: error(403, "Organization permission was revoked"),
      });
      const forbidden = app.render(app[role]);
      assert.match(text(forbidden), /access needs attention/);
      assert.match(text(forbidden), /permission was revoked/);
      assert.equal(signIn(forbidden), undefined);
      assert.equal(field(forbidden, "org-legal-name"), undefined);
    }
  }
});

test("failed initial and background retry actions settle without leaking a rejected refresh promise", async () => {
  for (const role of ["candidate", "employer"]) {
    for (const signedIn of [false, true]) {
      const app = harness();
      app.set({
        signedIn,
        error: error(503, "Still unavailable"),
        retryError: new Error("Repeated service failure"),
      });
      let tree = app.render(app[role]);
      if (role === "candidate" && signedIn) {
        const wizard = app.render(tree.type, tree.props);
        tree = app.render(wizard.type, wizard.props);
      }
      const retry = nodes(tree).find(
        (node) => node.props.onClick && text(node) === "Try again",
      );
      assert.ok(retry);
      await assert.doesNotReject(async () => retry.props.onClick());
      assert.equal(app.retries(), 1);
    }
  }
});
test("a background failure keeps the candidate wizard mounted with the same draft and recovery action", () => {
  const app = harness();
  app.set({ signedIn: true });
  const ready = app.render(app.candidate);
  const wizard = app.render(ready.type, ready.props);
  field(wizard, "headline").props.onChange("Keep my unfinished headline");
  app.set({ signedIn: true, error: error(503, "Temporary backend outage") });
  const interrupted = app.render(app.candidate);
  assert.equal(interrupted.type, ready.type);
  assert.equal(interrupted.key, ready.key);
  const interruptedWizard = app.render(interrupted.type, interrupted.props);
  assert.equal(
    field(interruptedWizard, "headline").props.value,
    "Keep my unfinished headline",
  );
  assert.match(
    interruptedWizard.props.loadWarning,
    /current edits are still here/,
  );
  const frame = app.render(interruptedWizard.type, interruptedWizard.props);
  assert.ok(
    nodes(frame).find(
      (node) => node.props.onClick && text(node) === "Try again",
    ),
  );
  app.set({ signedIn: true });
  const recovered = app.render(app.candidate);
  assert.equal(recovered.type, ready.type);
  assert.equal(recovered.key, ready.key);
  assert.equal(
    field(app.render(recovered.type, recovered.props), "headline").props.value,
    "Keep my unfinished headline",
  );
});
test("a background employer failure preserves entered organization information through recovery", () => {
  const app = harness();
  app.set({ signedIn: true });
  const initial = app.render(app.employer);
  field(initial, "org-legal-name").props.onChange({
    target: { value: "Unfinished fixture organization" },
  });
  app.set({ signedIn: true, error: error(503, "Temporary backend outage") });
  const interrupted = app.render(app.employer);
  assert.equal(
    field(interrupted, "org-legal-name").props.value,
    "Unfinished fixture organization",
  );
  assert.match(text(interrupted), /current edits are still here/);
  assert.equal(signIn(interrupted), undefined);
  app.set({ signedIn: true });
  assert.equal(
    field(app.render(app.employer), "org-legal-name").props.value,
    "Unfinished fixture organization",
  );
});
