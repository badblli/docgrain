import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";
import { createHash, webcrypto } from "node:crypto";
import { File } from "node:buffer";

const require = createRequire(import.meta.url);
const webRequire = createRequire(new URL("../../apps/web/package.json", import.meta.url));
const ts = require("../../apps/web/node_modules/typescript");
const compile = path => ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
function evaluate(path, dependencies = {}) {
  const exports = {};
  const context = { exports, require: name => dependencies[name] ?? webRequire(name), AbortController, File,
    FormData, crypto: webcrypto, setTimeout, clearTimeout, ...dependencies.globals };
  vm.runInNewContext(compile(path), context);
  return exports;
}
const { createUploadQueue, sha256 } = evaluate("../../apps/web/lib/u1-upload.ts");
const file = (name, text = name) => new File([text], name, { type: "text/plain" });
const hash = async file => createHash("sha256").update(Buffer.from(await file.arrayBuffer())).digest("hex");
const response = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
async function until(predicate) {
  for (let attempt = 0; attempt < 100; attempt++) { if (predicate()) return; await new Promise(resolve => setImmediate(resolve)); }
  assert.fail("Expected async state did not arrive");
}
function server(fail = () => false) {
  const calls = [], records = new Map();
  return { calls, records, fetch: async (url, init) => {
    calls.push({ url, method: init.method, body: init.body });
    if (fail(url, init)) return response({}, 503);
    if (url.endsWith("/documents")) {
      const body = JSON.parse(init.body);
      let item = records.get(body.content_sha256);
      if (item) return response({ ...item, deduplicated: true, upload_url: item.stored ? null : item.upload_url });
      const id = String(records.size + 1);
      item = { document: { id: `doc-${id}`, filename: body.filename }, version: { id: `v-${id}`, status: "processing" },
        job_id: `job-${id}`, upload_url: `http://example.test/content/${id}`, deduplicated: false };
      records.set(body.content_sha256, item);
      return response(item, 202);
    }
    if (init.method === "PUT") {
      const item = [...records.values()].find(item => item.upload_url === url);
      assert.ok(item); assert.equal(init.body.get("file").name, item.document.filename);
      item.stored = true;
    }
    return response({ status: "queued" }, 202);
  } };
}
function queue(backend, overrides = {}) {
  const states = new Map(), registrations = [], uploaded = [];
  const worker = createUploadQueue({ apiUrl: "http://example.test", workspaceId: "ws-example", fetch: backend.fetch, hash,
    active: () => true, onState: state => states.set(state.id, state),
    onRegistered: result => registrations.push(result), onUploaded: result => uploaded.push(result), ...overrides });
  return { ...worker, states, registrations, uploaded };
}

test("SHA-256 uses the actual file content", async () => {
  const input = file("rooms.txt", "Örnek oda 32 m²");
  assert.equal(await sha256(input), await hash(input));
  assert.equal((await sha256(input)).length, 64);
});
test("two files each register, transfer, confirm without waiting for preparation", async () => {
  const backend = server(), worker = queue(backend);
  worker.add([file("rooms.txt"), file("services.txt")]);
  await until(() => worker.uploaded.length === 2);
  assert.equal(backend.records.size, 2);
  for (const [index, item] of worker.uploaded.entries()) {
    assert.equal(item.version.status, "processing");
    assert.equal([...worker.states.values()][index].phase, "queued");
    const put = backend.calls.findIndex(call => call.url === item.upload_url);
    const confirm = backend.calls.findIndex(call => call.url.includes(item.document.id) && call.url.endsWith("/uploaded"));
    assert.ok(put >= 0 && confirm > put);
  }
  const registrations = backend.calls.filter(call => call.url.endsWith("/documents"));
  assert.equal(registrations.length, 2);
  for (const call of registrations) {
    const body = JSON.parse(call.body);
    assert.equal(body.workspace_id, "ws-example"); assert.match(body.content_sha256, /^[a-f0-9]{64}$/);
  }
});
test("a second-file error preserves the successful document and retries only that transfer", async () => {
  let broken = true;
  const backend = server(url => broken && url.endsWith("/content/2")), worker = queue(backend);
  worker.add([file("rooms.txt"), file("services.txt")]);
  await until(() => [...worker.states.values()].some(state => state.phase === "error"));
  await until(() => worker.uploaded.length === 1);
  assert.equal(worker.uploaded[0].document.id, "doc-1");
  const failed = [...worker.states.values()].find(state => state.phase === "error");
  assert.equal(failed.fileName, "services.txt");
  broken = false; worker.retry(failed.id); worker.retry(failed.id);
  await until(() => worker.uploaded.length === 2);
  assert.equal(backend.records.size, 2);
  assert.equal(backend.calls.filter(call => call.url.endsWith("/documents")).length, 2);
  assert.equal(backend.calls.filter(call => call.url.endsWith("/content/1")).length, 1);
  assert.equal(backend.calls.filter(call => call.url.endsWith("/content/2")).length, 2);
});
test("confirmation retry reuses registration and already stored bytes", async () => {
  let broken = true;
  const backend = server(url => broken && url.endsWith("/uploaded")), worker = queue(backend);
  worker.add([file("rooms.txt")]);
  await until(() => [...worker.states.values()][0]?.phase === "error");
  broken = false; worker.retry([...worker.states.keys()][0]);
  await until(() => worker.uploaded.length === 1);
  assert.equal(backend.calls.filter(call => call.method === "PUT").length, 1);
  assert.equal(backend.calls.filter(call => call.url.endsWith("/documents")).length, 1);
  assert.equal(backend.calls.filter(call => call.url.endsWith("/uploaded")).length, 2);
});
test("same-batch identical content and later repeat share one document", async () => {
  const backend = server(), worker = queue(backend);
  worker.add([file("rooms.txt", "same"), file("copy.txt", "same")]);
  await until(() => worker.uploaded.length === 2);
  worker.add([file("rooms.txt", "same")]);
  await until(() => worker.uploaded.length === 3);
  assert.equal(backend.records.size, 1);
  assert.equal(backend.calls.length, 3);
  assert.equal(new Set(worker.uploaded.map(item => item.document.id)).size, 1);
});
test("a fresh queue honors server dedup, including recovery when content is missing", async () => {
  const backend = server(), first = queue(backend);
  first.add([file("rooms.txt")]); await until(() => first.uploaded.length === 1);
  const second = queue(backend);
  second.add([file("rooms.txt")]); await until(() => second.uploaded.length === 1);
  assert.equal(backend.calls.length, 4); // repeat only registers; no transfer or preparation restart
  [...backend.records.values()][0].stored = false;
  const third = queue(backend);
  third.add([file("rooms.txt")]); await until(() => third.uploaded.length === 1);
  assert.equal(backend.records.size, 1); assert.equal(backend.calls.length, 7);
});
test("concurrency is bounded and a third file proceeds while documents still prepare", async () => {
  const hold = deferred(), backend = server(); let transfers = 0, maximum = 0;
  const worker = queue({ fetch: async (url, init) => {
    if (init.method === "PUT") { transfers++; maximum = Math.max(maximum, transfers); await hold.promise; }
    const result = await backend.fetch(url, init);
    if (init.method === "PUT") transfers--;
    return result;
  } });
  worker.add([file("one.txt"), file("two.txt"), file("three.txt")]);
  await until(() => transfers === 2);
  assert.equal(backend.records.size, 2); hold.resolve();
  await until(() => worker.uploaded.length === 3);
  assert.equal(maximum, 2);
  assert.ok(worker.uploaded.every(item => item.version.status === "processing"));
});
test("workspace switch during registration discards callbacks and stops further writes", async () => {
  let active = true; const hold = deferred(), backend = server();
  const worker = queue({ fetch: async (url, init) => { const result = await backend.fetch(url, init); await hold.promise; return result; } }, { active: () => active });
  worker.add([file("rooms.txt"), file("services.txt"), file("third.txt")]);
  await until(() => backend.calls.length === 2);
  const before = worker.states.size; active = false; hold.resolve();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(worker.states.size, before); assert.equal(worker.registrations.length, 0); assert.equal(worker.uploaded.length, 0);
  assert.equal(backend.calls.length, 2);
});
test("workspace switch during hashing sends no registration", async () => {
  let active = true; const hold = deferred(), backend = server();
  const worker = queue(backend, { active: () => active, hash: () => hold.promise });
  worker.add([file("rooms.txt")]); active = false; hold.resolve("a".repeat(64));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(backend.calls.length, 0); assert.equal(worker.uploaded.length, 0);
});

// A deterministic hook host runs the real hook, timers and fetch callbacks without installing a framework.
function hookHost(path, fetcher, dependencies = {}) {
  const slots = [], effects = [], intervals = new Map(), storage = new Map(); let cursor = 0, timer = 0;
  const changed = (a, b) => !a || a.length !== b.length || a.some((value, index) => value !== b[index]);
  const hooks = {
    useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = initial; return [slots[index], value => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }]; },
    useRef(initial) { const index = cursor++; return slots[index] ??= { current: initial }; },
    useCallback(callback, deps) { const index = cursor++; if (!slots[index] || changed(slots[index].deps, deps)) slots[index] = { callback, deps }; return slots[index].callback; },
    useEffect(effect, deps) { const index = cursor++; if (!slots[index] || changed(slots[index].deps, deps)) { const old = slots[index]; slots[index] = { deps }; effects.push(() => { old?.cleanup?.(); slots[index].cleanup = effect(); }); } },
  };
  const module = evaluate(path, { react: hooks, "@/components/ui/card": {},
    "./information/labels": evaluate("../../apps/web/app/components/information/labels.ts"),
    globals: { fetch: fetcher, localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
      setInterval: (callback, ms) => { intervals.set(++timer, { callback, ms }); return timer; }, clearInterval: id => intervals.delete(id) }, ...dependencies,
  });
  return { module, storage, intervals, render: (...args) => { cursor = 0; const result = (module.useRecordJob || module.useWorkspaceReview || module.InformationView)(...args); while (effects.length) effects.shift()(); return result; }, tick: () => { for (const interval of intervals.values()) interval.callback(); } };
}
const readyModel = { enabled: true, base_url: "http://model.test", model: "example", credential_ready: true };
const job = (workspace = "ws-a", status = "running") => ({ job_id: "job-a", workspace_id: workspace, status, stage: "extract", completed_stages: 2, total_stages: 6, revision_id: status === "done" ? "rev-new" : null });
test("record job resumes latest, polls at two seconds, and refreshes once at completion", async () => {
  const calls = []; let result = job(), refreshed = 0;
  const host = hookHost("../../apps/web/app/components/record-job-progress.tsx", async (url, init) => { calls.push({ url, init }); return response(url.endsWith("/model") ? readyModel : result); });
  const render = () => host.render("http://example.test", "ws-a", "live", 0, () => refreshed++);
  render(); await until(() => render().job?.status === "running");
  assert.ok([...host.intervals.values()].every(interval => interval.ms <= 3000));
  assert.equal(calls.filter(call => call.init?.method === "POST").length, 0);
  result = job("ws-a", "done"); host.tick(); await until(() => render().job?.status === "done");
  host.tick(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(refreshed, 1); assert.ok(calls.some(call => call.url.endsWith("/record-jobs/job-a")));
});
test("double click and uncertain start retry keep a single request id; model save does not start a job", async () => {
  const posts = []; let failed = true;
  const host = hookHost("../../apps/web/app/components/record-job-progress.tsx", async (url, init) => {
    if (init?.method === "POST") { posts.push(JSON.parse(init.body)); if (failed) throw new Error("offline"); return response({ job_id: "job-a" }, 202); }
    return url.endsWith("/model") ? response(readyModel) : response({}, 404);
  });
  const render = (key = 0) => host.render("http://example.test", "ws-a", "live", key, () => {});
  render(); await until(() => render().loaded && render().modelState === "ready");
  const view = render(); await Promise.all([view.start(true), view.start(true)]);
  assert.equal(posts.length, 1); failed = false;
  await render().start(true); assert.equal(posts.length, 2); assert.equal(posts[0].request_id, posts[1].request_id);
  render(1); await new Promise(resolve => setImmediate(resolve)); assert.equal(posts.length, 2);
});
test("closed model, demo and unready documents cannot POST a job", async () => {
  const posts = [];
  const host = hookHost("../../apps/web/app/components/record-job-progress.tsx", async (url, init) => {
    if (init?.method === "POST") posts.push(url);
    return url.endsWith("/model") ? response({ ...readyModel, enabled: false }) : response({}, 404);
  });
  const render = (mode = "live") => host.render("http://example.test", "ws-a", mode, 0, () => {});
  render(); await until(() => render().modelState === "off"); await render().start(true);
  await render("demo").start(true); assert.equal(posts.length, 0);
  const open = hookHost("../../apps/web/app/components/record-job-progress.tsx", async url => url.endsWith("/model") ? response(readyModel) : response({}, 404));
  const ready = () => open.render("http://example.test", "ws-a", "live", 0, () => {});
  ready(); await until(() => ready().loaded && ready().modelState === "ready"); await ready().start(false);
  assert.equal(ready().job, null);
});
test("late job and model replies for A cannot enter workspace B", async () => {
  const hold = deferred();
  const host = hookHost("../../apps/web/app/components/record-job-progress.tsx", async url => {
    if (url.includes("/ws-a/")) { await hold.promise; return response(url.endsWith("/model") ? readyModel : job()); }
    return url.endsWith("/model") ? response({ ...readyModel, enabled: false }) : response({}, 404);
  });
  host.render("http://example.test", "ws-a", "live", 0, () => {});
  const render = () => host.render("http://example.test", "ws-b", "live", 0, () => {});
  render(); hold.resolve(); await until(() => render().loaded);
  assert.equal(render().job, null); assert.equal(render().modelState, "off");
});
const summary = revision => ({ workspace_id: "ws-a", revision_id: revision, documents: 2, records: 1, collections: [], unsupported_fields: 0, conflicts: 0, needs_review: 1, accepted_ratio: 0, updated_at: null });
const question = { id: "q-one", kind: "needs_review", collection: "rooms", collection_label: "Özel odalar", record_id: "room-one", record_title: "Örnek oda", field: "capacity", field_label: "Kişi sayısı", options: [], lang: "tr" };
test("an answer sends the read revision and reloads the returned publication revision", async () => {
  const calls = [];
  const host = hookHost("../../apps/web/app/components/workspace-review.ts", async (url, init) => {
    calls.push({ url, init });
    if (init?.method === "POST") return response({ revision_id: "rev-new", remaining: 0 });
    if (url.includes("/summary")) return response(summary(url.includes("revision_id=rev-new") ? "rev-new" : "rev-old"));
    return response({ total: url.includes("rev-new") ? 0 : 1, items: url.includes("rev-new") ? [] : [question] });
  });
  const render = () => host.render("http://example.test", "ws-a", 0);
  render(); await until(() => render().questionState === "ready");
  assert.equal(await render().answer(question, { candidate_id: "c-one" }), true);
  const post = calls.find(call => call.init?.method === "POST");
  assert.match(post.url, /answer\?revision_id=rev-old$/);
  assert.equal(render().summary.revision_id, "rev-new"); assert.equal(render().total, 0);
  assert.equal(render().fieldLabels.rooms.capacity, "Kişi sayısı");
});
test("stale answer 409 reloads current questions without claiming success", async () => {
  let newer = false;
  const host = hookHost("../../apps/web/app/components/workspace-review.ts", async (url, init) => {
    if (init?.method === "POST") { newer = true; return response({}, 409); }
    return url.includes("/summary") ? response(summary(newer ? "rev-new" : "rev-old")) : response({ total: 1, items: [question] });
  });
  const render = () => host.render("http://example.test", "ws-a", 0);
  render(); await until(() => render().questionState === "ready");
  assert.equal(await render().answer(question, { candidate_id: "c-one" }), false);
  assert.equal(render().answered, 0); assert.equal(render().summary.revision_id, "rev-new");
  assert.match(render().notice, /kaydedilmedi/); assert.notEqual(render().notice, "Kaydedildi");
});
test("approved field display labels survive refresh without entering another workspace", async () => {
  const host = hookHost("../../apps/web/app/components/workspace-review.ts", async url => url.includes("/summary") ? response(summary("rev-new")) : response({ total: 0, items: [] }));
  host.storage.set("docgrain.field-labels:ws-a", JSON.stringify({ rooms: { capacity: "Kişi sayısı" } }));
  const a = () => host.render("http://example.test", "ws-a", 0);
  a(); await until(() => a().questionState === "ready"); assert.equal(a().fieldLabels.rooms.capacity, "Kişi sayısı");
  const b = () => host.render("http://example.test", "ws-b", 0);
  b(); await until(() => b().questionState === "ready"); assert.equal(b().fieldLabels.rooms, undefined);
});
test("late answer and review replies for A cannot populate B", async () => {
  const hold = deferred();
  const host = hookHost("../../apps/web/app/components/workspace-review.ts", async (url, init) => {
    if (init?.method === "POST") { await hold.promise; return response({ revision_id: "rev-a-new", remaining: 0 }); }
    return url.includes("/summary") ? response(summary(url.includes("/ws-b/") ? "rev-b" : "rev-a")) : response({ total: 1, items: [question] });
  });
  const a = () => host.render("http://example.test", "ws-a", 0);
  a(); await until(() => a().questionState === "ready"); const saving = a().answer(question, { candidate_id: "c-one" });
  const b = () => host.render("http://example.test", "ws-b", 0);
  b(); hold.resolve(); assert.equal(await saving, false); await until(() => b().questionState === "ready");
  assert.equal(b().summary.revision_id, "rev-b"); assert.equal(b().answered, 0); assert.equal(b().notice, "");
});

test("job 409 remains visible after subsequent status reads and never becomes a started job", async () => {
  const host = hookHost("../../apps/web/app/components/record-job-progress.tsx", async (url, init) => {
    if (init?.method === "POST") return response({}, 409);
    return url.endsWith("/model") ? response(readyModel) : response({}, 404);
  });
  const render = () => host.render("http://example.test", "ws-a", "live", 0, () => {});
  render(); await until(() => render().loaded && render().modelState === "ready"); await render().start(true);
  host.tick(); await new Promise(resolve => setImmediate(resolve));
  assert.match(render().error, /Onaylı yayın/); assert.equal(render().job, null);
});
test("missing record-job routes show a clear message after start without treating an empty latest as failure", async () => {
  const host = hookHost("../../apps/web/app/components/record-job-progress.tsx", async url => url.endsWith("/model") ? response(readyModel) : response({}, 404));
  const render = () => host.render("http://example.test", "ws-a", "live", 0, () => {});
  render(); await until(() => render().loaded && render().modelState === "ready");
  assert.equal(render().error, ""); assert.equal(render().job, null);
  await render().start(true);
  assert.match(render().error, /Bilgi çıkarma hizmeti henüz kullanılamıyor/);
  assert.equal(render().job, null);
});
test("a missing job detail remains an error and disables another start", async () => {
  const host = hookHost("../../apps/web/app/components/record-job-progress.tsx", async (url, init) => {
    if (init?.method === "POST") return response({ job_id: "job-a" }, 202);
    return url.endsWith("/model") ? response(readyModel) : response({}, 404);
  });
  const render = () => host.render("http://example.test", "ws-a", "live", 0, () => {});
  render(); await until(() => render().loaded && render().modelState === "ready");
  await render().start(true); host.tick();
  await until(() => render().error.includes("kaydı bulunamadı"));
  assert.equal(render().loaded, false);
});
test("reload after an uncertain start retries the persisted request id", async () => {
  const posts = [];
  const host = hookHost("../../apps/web/app/components/record-job-progress.tsx", async (url, init) => {
    if (init?.method === "POST") { posts.push(JSON.parse(init.body)); throw new Error("offline"); }
    return url.endsWith("/model") ? response(readyModel) : response({}, 404);
  });
  const render = key => host.render("http://example.test", "ws-a", "live", key, () => {});
  render(0); await until(() => render(0).loaded && render(0).modelState === "ready"); await render(0).start(true);
  render(1); await until(() => render(1).loaded && render(1).modelState === "ready"); await render(1).start(true);
  assert.equal(posts.length, 2); assert.equal(posts[0].request_id, posts[1].request_id);
});

const React = webRequire("react");
const { renderToStaticMarkup } = webRequire("react-dom/server");
const labels = evaluate("../../apps/web/app/components/information/labels.ts");
const element = tag => ({ children, ...props }) => React.createElement(tag, props, children);
const { QuestionCard } = evaluate("../../apps/web/app/components/question-card.tsx", {
  react: React, "@/components/ui/button": { Button: element("button") }, "@/components/ui/card": { Card: element("section") },
  "@/components/ui/input": { Input: element("input") }, "@/components/ui/label": { Label: element("label") },
  "@/lib/utils": { cn: (...parts) => parts.filter(Boolean).join(" ") }, "./console-ui": { Icon: () => null }, "./information/labels": labels,
});
const option = (candidate, document, value) => ({ candidate_id: candidate, document_id: document, document_name: `${document}.txt`,
  value, display: String(value), quote: `Oda ${value} kişiliktir. <script>ignored()</script>`, locator: "Satır 2" });
test("one-candidate approval and actual conflict have distinct actions and accessible evidence", () => {
  const single = renderToStaticMarkup(React.createElement(QuestionCard, { question: { ...question, options: [option("c1", "rooms", 2)] }, totalCount: 1, onAnswer: () => {} }));
  assert.match(single, /Bu bilgiyi onaylayın/); assert.match(single, /Bu bilgiyi onayla/);
  assert.doesNotMatch(single, /Bu belge güncel|hangisi\?/); assert.match(single, /rooms.txt/); assert.match(single, /Satır 2/);
  assert.match(single, /&lt;script&gt;/); assert.doesNotMatch(single, /<script>/);
  const conflict = renderToStaticMarkup(React.createElement(QuestionCard, { question: { ...question, kind: "conflict", options: [option("c1", "rooms", 2), option("c2", "services", 3)] }, totalCount: 1, onAnswer: () => {} }));
  assert.match(conflict, /Kaynaklar farklı söylüyor/); assert.equal((conflict.match(/>Bu belge güncel</g) || []).length, 2);
  assert.match(conflict, /rooms.txt/); assert.match(conflict, /services.txt/);
});
test("localized discovered labels take priority and known/unknown key fallbacks remain readable", () => {
  assert.equal(labels.displayCollectionLabel("rooms", "Misafir odaları"), "Misafir odaları");
  assert.equal(labels.getFieldLabel("capacity", "Kişi sayısı"), "Kişi sayısı");
  assert.equal(labels.displayCollectionLabel("rooms", "rooms"), "Odalar");
  assert.equal(labels.getFieldLabel("capacity", "capacity"), "Kapasite");
  assert.equal(labels.getFieldLabel("example_field").includes("_"), false);
});
test("stage counts, schema review and timeout are honest terminal presentations", () => {
  const { RecordJobProgress } = evaluate("../../apps/web/app/components/record-job-progress.tsx", { react: React, "@/components/ui/card": { Card: element("section") } });
  const markup = status => renderToStaticMarkup(React.createElement(RecordJobProgress, { job: { ...job("ws-a", status), error_code: "stage_timeout" }, error: "" }));
  assert.match(markup("running"), /Bilgiler çıkarılıyor/); assert.match(markup("running"), /2 \/ 6 aşama tamamlandı/);
  assert.match(markup("needs_review"), /Bilgi yapısı kontrol edilmeli/); assert.doesNotMatch(markup("needs_review"), /Bilgiler hazır/);
  assert.match(markup("failed"), /bekleme süresi doldu/); assert.match(markup("failed"), /Önceki bilgiler korunuyor/);
  assert.match(markup("done"), /onay bekleyenleri Sorular/); assert.doesNotMatch(markup("running"), /%|dakika|saniye/);
});

function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  if (!tree?.props) return [];
  return [tree, ...nodes(tree.props.children)];
}
test("approved collections discard old rows and reload the answer revision with discovered field labels", async () => {
  const calls = [];
  const dependencies = {
    "@/components/ui/button": { Button: element("button") }, "@/components/ui/card": { Card: element("section") },
    "@/components/ui/label": { Label: element("label") }, "@/components/ui/skeleton": { Skeleton: element("div") },
    "../review-states": { ReviewBadge: () => null }, "../developer-mode": { useDeveloperMode: () => false },
    "../console-ui": { Head: element("header"), Ep: () => null, Icon: () => null },
    "../collection-card": { CollectionCard: () => null }, "./labels": labels, "../question-card": { SourceQuote: () => null },
  };
  const host = hookHost("../../apps/web/app/components/information/information.tsx", async url => {
    calls.push(url);
    if (url.endsWith("/revisions")) throw new Error("Expected explicit publication revision");
    if (url.includes("/collections?")) return response({ collections: ["rooms"] });
    return response([{ id: "room-one", name: "Örnek oda", capacity: url.includes("/rev-new/") ? 2 : 3,
      _meta: { review_state: "accepted", fields: { capacity: { label_tr: "Kişi sayısı" } } } }]);
  }, dependencies);
  const props = { apiUrl: "http://example.test", workspaceId: "ws-a", initialCollection: "rooms", summaries: [], questions: [], questionState: "ready", onQuestion: () => {} };
  const render = revisionId => host.render({ ...props, revisionId });
  render("rev-old"); await until(() => JSON.stringify(render("rev-old")).includes("Kişi sayısı: 3"));
  const approvedSwitch = nodes(render("rev-old")).find(node => node.type === "input" && node.props.role === "switch");
  approvedSwitch.props.onChange({ target: { checked: true } });
  render("rev-old"); await until(() => calls.some(url => url.includes("/collections/rooms?mode=approved")));
  const boundary = calls.length;
  const loading = render("rev-new"); // cleanup immediately aborts the old publication's reader
  await until(() => nodes(render("rev-new")).some(node => node.props.collection?.key === "rooms"));
  nodes(render("rev-new")).find(node => node.props.collection?.key === "rooms").props.onOpen();
  await until(() => JSON.stringify(render("rev-new")).includes("Kişi sayısı: 2"));
  assert.ok(calls.slice(boundary).every(url => url.includes("/rev-new/") && url.includes("mode=approved")));
  assert.doesNotMatch(JSON.stringify(render("rev-new")), /Kişi sayısı: 3/);
  assert.ok(loading);
});
