// WP120 interactions use the real components with a deterministic hook/fetch host.
// Run from apps/web: node --test ../../tests/unit/test_background_field_fill_web.cjs
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const web = path.resolve(__dirname, "../../apps/web");
const ts = require(path.join(web, "node_modules/typescript"));
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
const schema = { version: 2, collections: [{ key: "items", label: "Ürünler", identity: "name", fields: [{ key: "name", label: "Ad", type: "string" }] }] };

function host(file, name, props, fetch) {
  const slots = [], timers = new Map();
  let cursor = 0, effects = [], tree;
  const jsx = (type, props) => ({ type, props: props || {} });
  const hooks = {
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      return [slots[index], value => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }];
    },
    useRef(initial) { const index = cursor++; return slots[index] ??= { current: initial }; },
    useEffect(effect, dependencies) {
      const index = cursor++, old = slots[index];
      if (!old || dependencies.some((value, at) => value !== old.dependencies[at])) {
        slots[index] = { dependencies };
        effects.push(() => { old?.cleanup?.(); slots[index].cleanup = effect(); });
      }
    },
  };
  const modules = {
    react: hooks, "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "Fragment" },
    "../developer-mode": { useDeveloperMode: () => false },
    "../record-job-progress": { RecordJobProgress: "Progress", jobActive: job => ["queued", "running"].includes(job?.status) },
    "./collection-actions": { CollectionActions: "Actions" },
    "./labels": { displayCollectionLabel: (key, label) => label || key, getFieldLabel: key => key },
  };
  const exports = {};
  const source = ts.transpileModule(fs.readFileSync(path.join(web, file), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(source, {
    exports, fetch, AbortController,
    setInterval(callback) { const id = {}; timers.set(id, callback); return id; },
    clearInterval(id) { timers.delete(id); },
    require: key => modules[key] || new Proxy({}, { get: (_, name) => name }),
  });
  function render() {
    cursor = 0; tree = exports[name](props);
    const pending = effects; effects = []; pending.forEach(effect => effect());
    return tree;
  }
  function nodes(node) {
    if (!node || typeof node !== "object") return [];
    if (Array.isArray(node)) return node.flatMap(nodes);
    return [node, ...nodes(node.props?.children)];
  }
  return {
    render, nodes: () => nodes(tree), find: type => nodes(tree).find(node => node.type === type),
    async settle() { for (let index = 0; index < 4; index++) { await new Promise(setImmediate); render(); } },
    async tick() { [...timers.values()].forEach(callback => callback()); await this.settle(); },
    cleanup() { slots.forEach(slot => slot?.cleanup?.()); }, timers,
  };
}

test("adding a field follows its job, shows progress, then reloads schema and values once", async () => {
  let head = "initial", status = "running";
  const requests = [];
  const app = host("app/components/information/information.tsx", "InformationView", {
    apiUrl: "http://fixture.invalid", workspaceId: "example", initialCollection: "items",
    revisionId: "initial", summaries: [], questions: [], questionState: "ready", onQuestion() {},
  }, async url => {
    requests.push(url);
    if (url.includes("/record-jobs/")) return response({ job_id: "fill1", workspace_id: "example", kind: "field_fill", collection: "items", status, revision_id: status === "done" ? "filled" : null });
    if (url.endsWith("/revisions")) return response([head]);
    if (url.includes("/collection-schema")) return response(schema);
    if (url.includes("/collections?")) return response({ collections: ["items"] });
    return response([{ id: "item", name: "Örnek", details: head === "filled" ? "Yeni değer" : undefined }]);
  });
  app.render(); await app.settle();
  head = "field";
  app.find("Actions").props.onDone("Alan eklendi", "fill1");
  app.render(); await app.settle();
  assert.equal(app.find("Progress").props.job.status, "running");
  assert(requests.some(url => url.endsWith("/record-jobs/fill1")));
  status = "done"; head = "filled";
  await app.tick();
  assert.equal(app.find("Progress").props.job.status, "done");
  assert(requests.some(url => url.includes("/collection-schema?revision_id=filled")));
  assert(requests.some(url => url.includes("/revisions/filled/collections/items?")));
  const count = requests.length;
  await app.tick(); assert.equal(requests.length, count);
  app.cleanup(); assert.equal(app.timers.size, 0);
});

test("old finished field jobs stay hidden; a fill started elsewhere appears and reloads once", async () => {
  let current = { job_id: "old", status: "done" }, head = "initial";
  const requests = [];
  const app = host("app/components/information/information.tsx", "InformationView", {
    apiUrl: "http://fixture.invalid", workspaceId: "example", initialCollection: "items",
    revisionId: "initial", summaries: [], questions: [], questionState: "ready", onQuestion() {},
  }, async url => {
    requests.push(url);
    if (url.includes("/record-jobs/")) return response({ ...current, kind: "field_fill", workspace_id: "example", collection: "items" });
    if (url.endsWith("/revisions")) return response([head]);
    if (url.includes("/collection-schema")) return response(schema);
    if (url.includes("/collections?")) return response({ collections: ["items"] });
    return response([{ id: "item", name: "Örnek" }]);
  });
  app.render(); await app.settle();
  assert.equal(app.find("Progress").props.job, null);
  assert.equal(requests.filter(url => url.endsWith("/revisions")).length, 0);
  const firstPolls = requests.filter(url => url.endsWith("/record-jobs/latest")).length;
  await app.tick();
  assert(requests.filter(url => url.endsWith("/record-jobs/latest")).length > firstPolls);
  assert.equal(app.find("Progress").props.job, null);
  current = { job_id: "new", status: "running" };
  await app.tick();
  assert.equal(app.find("Progress").props.job.job_id, "new");
  head = "filled"; current = { job_id: "new", status: "done" };
  await app.tick();
  assert.equal(app.find("Progress").props.job.status, "done");
  assert.equal(requests.filter(url => url.endsWith("/revisions")).length, 1);
  await app.tick();
  assert.equal(requests.filter(url => url.endsWith("/revisions")).length, 1);
  app.cleanup();
});

test("field dialog returns the fill job id and presents the specific 409 message", async () => {
  const done = [];
  let conflict = false;
  const app = host("app/components/information/collection-actions.tsx", "CollectionActions", {
    base: "http://fixture.invalid/v1/workspaces/example", revision: "r1", schema,
    collection: "items", developerMode: false, onDone: (...args) => done.push(args),
  }, async () => conflict ? response({ detail: "Yeni alan dolduruluyor; bitince tekrar deneyin." }, 409)
    : response({ fill_job_id: "fill1", note: "Alan eklendi" }));
  app.render();
  app.nodes().find(node => node.type === "Button" && node.props.children === "Alan ekle").props.onClick();
  app.render();
  await app.find("form").props.onSubmit({ preventDefault() {} });
  assert.deepEqual(done, [["Alan eklendi", "fill1"]]);
  conflict = true;
  app.nodes().find(node => node.type === "Button" && node.props.children === "Alan ekle").props.onClick();
  app.render();
  await app.find("form").props.onSubmit({ preventDefault() {} });
  app.render();
  assert(app.nodes().some(node => node.props.children === "Yeni alan dolduruluyor; bitince tekrar deneyin."));
  assert.equal(done.length, 1);
});

test("field job titles explain progress and preserve the field on failure without exposing codes", () => {
  for (const [status, title] of [
    ["running", "Yeni alan dolduruluyor"], ["done", "Yeni alan dolduruldu"],
    ["failed", "Yeni alan doldurulamadı; değerleri elle girebilirsiniz. Alan eklendi ve korunuyor."],
  ]) {
    const app = host("app/components/record-job-progress.tsx", "RecordJobProgress", {
      job: { job_id: "private-job-code", kind: "field_fill", status, stage: "fill", completed_stages: 0, total_stages: 2 }, error: "",
    });
    app.render();
    assert.equal(app.find("h3").props.children, title);
    assert(!app.nodes().some(node => node.props.children === "private-job-code"));
  }
});
