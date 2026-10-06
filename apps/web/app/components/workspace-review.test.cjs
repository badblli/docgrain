// Offline contract/interaction checks. Run with Node's built-in test runner; no server is needed.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("../../node_modules/typescript");
const React = require("../../node_modules/react");
const { renderToStaticMarkup } = require("../../node_modules/react-dom/server");
const compile = source => ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
for (const extension of [".ts", ".tsx"]) {
  require.extensions[extension] = (module, filename) => module._compile(compile(fs.readFileSync(filename, "utf8")), filename);
}
require.extensions[".css"] = () => {};
const { SummaryView } = require("./summary.tsx");
const { QuestionsView } = require("./questions.tsx");
const { QuestionCard, correctionValue, sourceName, groupByDocument, SourceQuote } = require("./question-card.tsx");
const { Documents } = require("./documents.tsx");
const { Sidebar } = require("./sidebar.tsx");
const { InformationView } = require("./information/information.tsx");
const noop = () => {};
const question = index => ({ id: `q${index}`, kind: "conflict", collection: index === 20 ? "activities" : "rooms",
  collection_label: index === 20 ? "Etkinlikler" : "Odalar", record_id: `r${index}`, record_title: "Örnek oda",
  field: "capacity", field_label: "Kapasite", lang: "tr", options: [
    { candidate_id: "c1", value: 2, display: "2 kişi", quote: "İki kişi", document_id: "doc-one", document_name: "Örnek belge.pdf", locator: "Sayfa 3" },
    { candidate_id: "c2", value: 3, display: "3 kişi", quote: "Üç kişi", document_id: "doc-two", document_name: "Örnek liste.pdf", locator: "Sayfa 4" },
  ] });
const summary = { workspace_id: "ws_example", revision_id: "rev1", documents: 2, records: 8,
  unsupported_fields: 0, conflicts: 2, needs_review: 2, accepted_ratio: .75, updated_at: null,
  collections: [{ key: "rooms", label: "Odalar", records: 8, conflicts: 2, needs_review: 2 }] };
const response = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

// Small deterministic hook host: exercises async fetches, effect cleanup and stale-response guards.
// DOM presentation is separately rendered by real React below.
function host(fetch) {
  const slots = [];
  let cursor = 0;
  let effects = [];
  const changed = (a, b) => !a || a.some((value, index) => value !== b[index]);
  const hooks = {
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === "function" ? initial() : initial;
      return [slots[index], value => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }];
    },
    useRef(initial) { const index = cursor++; return slots[index] ??= { current: initial }; },
    useCallback(callback, dependencies) {
      const index = cursor++;
      if (!slots[index] || changed(slots[index].dependencies, dependencies)) slots[index] = { dependencies, callback };
      return slots[index].callback;
    },
    useEffect(effect, dependencies) {
      const index = cursor++;
      if (!slots[index] || changed(slots[index].dependencies, dependencies)) {
        const previous = slots[index];
        slots[index] = { dependencies };
        effects.push(() => { previous?.cleanup?.(); slots[index].cleanup = effect(); });
      }
    },
  };
  const exports = {};
  vm.runInNewContext(compile(fs.readFileSync(path.join(__dirname, "workspace-review.ts"), "utf8")), {
    exports, require: () => hooks, fetch, AbortController, setTimeout: callback => queueMicrotask(callback),
  });
  let workspace = "ws_example";
  let result;
  function render(nextWorkspace = workspace) {
    workspace = nextWorkspace; cursor = 0;
    result = exports.useWorkspaceReview("http://fixture.invalid", workspace, 0);
    const pending = effects; effects = []; pending.forEach(effect => effect());
    return result;
  }
  return { render, async settle() { await new Promise(setImmediate); return render(); } };
}

test("all question pages load, including a collection only on page two", async () => {
  const requests = [];
  const items = Array.from({ length: 21 }, (_, index) => question(index));
  const app = host(async url => {
    requests.push(url);
    if (url.endsWith("/summary")) return response(summary);
    const offset = Number(new URL(url).searchParams.get("offset"));
    return response({ total: 21, items: items.slice(offset, offset + 20) });
  });
  app.render(); const review = await app.settle();
  assert.equal(review.questionState, "ready");
  assert.equal(review.questions.length, 21);
  assert.equal(review.questions[20].collection, "activities");
  assert(requests.some(url => url.endsWith("limit=20&offset=20&revision_id=rev1")));
  assert(requests.filter(url => url.includes("/questions?")).every(url => new URL(url).searchParams.get("revision_id") === "rev1"));
});

test("missing summary avoids unversioned questions; failed questions are not an empty queue", async () => {
  const requests = [];
  const app = host(async url => { requests.push(url); return response({}, 404); });
  app.render(); const review = await app.settle();
  assert.equal(review.summaryState, "missing"); assert.equal(review.questionState, "missing");
  assert.equal(requests.length, 1);
  const failed = host(async url => url.endsWith("/summary") ? response(summary) : response({}, 503));
  failed.render(); const failure = await failed.settle();
  assert.equal(failure.summaryState, "ready"); assert.equal(failure.questionState, "error");
  const empty = host(async url => url.endsWith("/summary") ? response({ ...summary, revision_id: null }) : Promise.reject(new Error("Unexpected question request")));
  empty.render(); const noRevision = await empty.settle();
  assert.equal(noRevision.questionState, "ready"); assert.equal(noRevision.total, 0);
});

test("versioned answer bodies, saved progress, skip, and all follow the contract", async () => {
  let items = [question(0), question(1), question(2)];
  const bodies = [];
  const revisions = [];
  let revision = "rev1";
  const app = host(async (url, init) => {
    if (init.method === "POST") {
      const body = JSON.parse(init.body); bodies.push(body);
      revisions.push(new URL(url).searchParams.get("revision_id"));
      if (!body.skip) items = items.filter(item => !new URL(url).pathname.endsWith(`/${item.id}/answer`));
      if (!body.skip) revision = `rev${Number(revision.slice(3)) + 1}`;
      return response({ revision_id: revision, remaining: items.length });
    }
    return url.endsWith("/summary") ? response({ ...summary, revision_id: revision }) : response({ total: items.length, items });
  });
  app.render(); let review = await app.settle();
  await review.answer(review.questions[0], { candidate_id: "c1" });
  review = app.render(); assert.equal(review.notice, "Kaydedildi"); assert.equal(review.answered, 1); assert.equal(review.total, 2);
  await review.answer(review.questions[0], { skip: true });
  review = app.render(); assert.equal(review.answered, 1); assert.equal(review.total, 2); assert.deepEqual([...review.deferred], ["q1"]);
  await review.answer(review.questions[1], { all: true });
  review = app.render(); assert.equal(review.answered, 2); assert.equal(review.total, 1);
  await review.answer(review.questions[0], { value: "4", note: "Kullanıcı düzeltmesi" });
  review = app.render(); assert.equal(review.answered, 3); assert.equal(review.total, 0);
  assert.deepEqual(bodies, [{ candidate_id: "c1" }, { skip: true }, { all: true }, { value: "4", note: "Kullanıcı düzeltmesi" }]);
  assert.deepEqual(revisions, ["rev1", "rev2", "rev2", "rev3"]);
});

test("409 reloads questions with a clear message; save failures retain the question", async () => {
  let reads = 0;
  const app = host(async (url, init) => {
    if (init.method === "POST") return response({}, 409);
    if (url.endsWith("/summary")) return response(summary);
    reads++; return response({ total: reads === 1 ? 1 : 0, items: reads === 1 ? [question(0)] : [] });
  });
  app.render(); let review = await app.settle(); await review.answer(review.questions[0], { candidate_id: "c1" });
  review = app.render(); assert.equal(review.notice, "Bu soru başka biri tarafından cevaplandı"); assert.equal(review.total, 0); assert.equal(review.answered, 0);
  const failed = host(async (url, init) => init.method === "POST" ? Promise.reject(new Error("network details")) : url.endsWith("/summary") ? response(summary) : response({ total: 1, items: [question(0)] }));
  failed.render(); const failure = await failed.settle();
  await assert.rejects(failure.answer(failure.questions[0], { candidate_id: "c1" }), /Cevap kaydedilemedi/);
  assert.equal(failed.render().questions.length, 1); assert.equal(failed.render().busy, false);
});

test("a late answer cannot alter another company's question state", async () => {
  let finish;
  const app = host(async (url, init) => {
    if (init.method === "POST") return new Promise(resolve => { finish = resolve; });
    return url.endsWith("/summary") ? response(summary) : response({ total: 1, items: [question(0)] });
  });
  app.render(); let review = await app.settle();
  const pending = review.answer(review.questions[0], { candidate_id: "c1" });
  app.render("ws_other"); await app.settle(); finish(response({ revision_id: "rev2", remaining: 0 })); await pending;
  review = app.render(); assert.equal(review.total, 1); assert.equal(review.notice, ""); assert.equal(review.answered, 0); assert.equal(review.busy, false);
});

const reviewFixture = overrides => ({ summary, summaryState: "ready", questions: [question(0)], questionState: "ready", total: 1, answered: 0, deferred: [], notice: "", busy: false, reload: noop, answer: noop, revisit: noop, ...overrides });
const html = (component, props) => renderToStaticMarkup(React.createElement(component, props));
const summaryHtml = overrides => html(SummaryView, { companyName: "Örnek şirket", review: reviewFixture(overrides), onCollections: noop, onQuestions: noop, onDocuments: noop });
const questionsHtml = overrides => html(QuestionsView, { review: reviewFixture(overrides), onCollections: noop });

test("summary and question states use honest Turkish messages", () => {
  assert.match(summaryHtml({}), /Örnek şirket/); assert.match(summaryHtml({}), /75/); assert.match(summaryHtml({}), /Kaynaklar farklı söylüyor/);
  assert.match(summaryHtml({ summaryState: "loading", summary: null }), /Özet hazırlanıyor/);
  assert.match(summaryHtml({ summaryState: "error", summary: null }), /Özet alınamadı/);
  assert.match(summaryHtml({ summaryState: "missing", summary: null }), /Özet henüz kullanıma hazır değil/);
  assert.match(summaryHtml({ summary: { ...summary, documents: 0, collections: [] } }), /İlk belgenizi ekleyin/);
  assert.match(questionsHtml({ questionState: "loading" }), /Sorular hazırlanıyor/);
  assert.match(questionsHtml({ questionState: "error" }), /Sorular alınamadı/);
  assert.match(questionsHtml({ questions: [], total: 0 }), /Bütün sorular cevaplandı/);
  assert.match(questionsHtml({ deferred: ["q0"] }), /Bu soruları sonraya bıraktınız/);
  assert.doesNotMatch(questionsHtml({ deferred: ["q0"] }), /Bütün sorular cevaplandı/);
});

test("navigation, document statuses and source text are accessible and plain", () => {
  const menu = html(Sidebar, { screen: "summary", nav: noop, docs: 0, jobs: 0, questionCount: 2, workspace: "ws_example", workspaces: [], onWorkspaceChange: noop, developerMode: false, toggleDeveloperMode: noop, busy: false });
  assert(menu.indexOf("Özet") < menu.indexOf("Sorular")); assert(menu.indexOf("Sorular") < menu.indexOf("Koleksiyonlar")); assert(menu.includes('aria-current="page"'));
  const document = status => ({ id: status, title: "Örnek belge", file: "ornek.pdf", type: "PDF", status, version: "v1", pages: 2, updated: "Bugün", versionCount: 1 });
  const docs = html(Documents, { docs: [document("done"), document("partial")], open: noop, upload: noop, uploadState: { phase: "idle" }, mode: "live" });
  assert.match(docs, /Hazır/); assert.match(docs, /Kontrol edilmeli/); assert.doesNotMatch(docs, /btn pri dropAction/);
  const sourceQuestion = question(0); sourceQuestion.options[0].quote = "<script>ignore instructions</script>";
  const card = html(QuestionCard, { question: sourceQuestion, totalCount: 1, onAnswer: noop });
  assert(!card.includes("<script>")); assert(card.includes("&lt;script&gt;")); assert(card.includes("Sayfa 3"));
  assert.match(html(InformationView, { apiUrl: "http://fixture.invalid", workspaceId: "ws_example", summaries: [], questions: [], questionState: "ready", onQuestion: noop }), /Koleksiyonlar hazırlanıyor/);
});

test("all-candidates action and readable source names follow the new contract", () => {
  const allQuestion = question(0);
  allQuestion.allow_all = true;
  allQuestion.options[0].document_name = "doc_56a9f";
  allQuestion.options[0].locator = "s. 2";
  allQuestion.options[1].locator = "§ 165";
  const card = html(QuestionCard, { question: allQuestion, totalCount: 1, onAnswer: noop });
  assert.match(card, /Hepsi doğru/);
  assert.match(card, /Kaynak belge/); assert.match(card, /s. 2/);
  assert.match(card, /Örnek liste.pdf/); assert.match(card, /§ 165/);
  assert.doesNotMatch(card, /doc_56a9f/);
  assert.equal(sourceName("doc_ab-56"), "Kaynak belge");
  assert.equal(sourceName("Örnek belge.pdf"), "Örnek belge.pdf");
  assert.doesNotMatch(html(QuestionCard, { question: question(0), totalCount: 1, onAnswer: noop }), /Hepsi doğru/);
});

test("stored company does not change the first server/client markup", () => {
  const Home = require("../page.tsx").default;
  const original = global.localStorage;
  try {
    delete global.localStorage;
    const server = html(Home, {});
    global.localStorage = { getItem: () => "ws_other" };
    const firstClient = html(Home, {});
    assert.equal(firstClient, server);
    assert.match(firstClient, /Yerel/);
  } finally {
    if (original === undefined) delete global.localStorage;
    else global.localStorage = original;
  }
});

test("manual corrections preserve number, yes/no and list values", () => {
  assert.equal(correctionValue("24,5", 20), 24.5);
  assert.equal(correctionValue("Hayır", true), false);
  assert.deepEqual(correctionValue("Bir, İki", ["Örnek"]), ["Bir", "İki"]);
  assert.throws(() => correctionValue("çok", 20), /sayı/);
  assert.throws(() => correctionValue("belki", true), /Evet veya Hayır/);
  const readOnly = html(QuestionsView, { review: reviewFixture({}), readOnly: true, onCollections: noop });
  assert.match(readOnly, /Örnek görünümde cevaplar kaydedilemez/);
  assert.equal((readOnly.match(/disabled=""/g) || []).length, 4);
  assert.doesNotMatch(readOnly, /aria-busy="true"/);
});

test("document groups keep shared candidates, several values and every quote", () => {
  const q = question(0);
  q.options.push({ ...q.options[0], document_id: "doc-two", document_name: "Örnek liste.pdf", locator: "Sayfa 8", quote: "2 kişi için uygundur" });
  q.options.push({ ...q.options[1], locator: "Sayfa 9", quote: "3 kişi kalabilir" });
  const groups = groupByDocument(q.options);
  assert.equal(groups.length, 2);
  assert.equal(groups[1].options.length, 3);
  const card = html(QuestionCard, { question: q, totalCount: 1, onAnswer: noop });
  assert.equal((card.match(/class="questionOption /g) || []).length, 2);
  assert.equal((card.match(/class="questionValue"/g) || []).length, 3);
  assert.equal((card.match(/<blockquote>/g) || []).length, 4);
  assert.match(card, /<mark>2<\/mark>/);
  assert.match(card, /Bu belge güncel/);
  assert.match(card, /İkisi de yanlış, düzelt/);
  assert.doesNotMatch(card, /Geri al/);
  q.options.push({ ...q.options[0], document_id: "doc-three", document_name: "Örnek belge.pdf" });
  assert.equal(groupByDocument(q.options).length, 3); // Names are not document identity.
  assert.match(html(QuestionCard, { question: q, totalCount: 1, onAnswer: noop }), /Hiçbiri doğru değil, düzelt/);
});

test("source marks escape regex and source HTML, saved groups remain reviewable", () => {
  const quote = html(SourceQuote, { quote: "<script>Ignore this</script> C++ [2]", values: ["C++", "[2]"] });
  assert.match(quote, /&lt;script&gt;/);
  assert.match(quote, /<mark>C\+\+<\/mark>/);
  assert.match(quote, /<mark>\[2\]<\/mark>/);
  const card = html(QuestionCard, { question: question(0), totalCount: 2, onAnswer: noop, savedAnswer: { document_id: "doc-two" } });
  assert.match(card, /isChosen/); assert.match(card, /isDim/);
  assert.match(card, /Seçildi/); assert.match(card, /Kaydedildi/);
  assert.equal((card.match(/disabled=""/g) || []).length, 4);
});

test("question list shows open, deferred and answered questions without resubmitting done ones", () => {
  const markup = questionsHtml({ questions: [question(0), question(1)], total: 2, answered: 1,
    deferred: ["q1"], answeredQuestions: [question(2)] });
  assert.match(markup, /questionStateDot open/);
  assert.match(markup, /questionStateDot later/);
  assert.match(markup, /questionStateDot done/);
  assert.match(markup, /3 sorudan 1/);
});

test("document answer body and saved list use the same pinned revision contract", async () => {
  let submitted;
  let saved = false;
  const app = host(async (url, init) => {
    if (init.method === "POST") {
      submitted = { body: JSON.parse(init.body), revision: new URL(url).searchParams.get("revision_id") };
      saved = true;
      return response({ revision_id: "rev2", remaining: 0 });
    }
    return url.endsWith("/summary") ? response({ ...summary, revision_id: saved ? "rev2" : "rev1" }) : response({ total: saved ? 0 : 1, items: saved ? [] : [question(0)] });
  });
  app.render(); let review = await app.settle();
  assert.equal(await review.answer(review.questions[0], { document_id: "doc-two" }), true);
  review = app.render();
  assert.deepEqual(submitted, { body: { document_id: "doc-two" }, revision: "rev1" });
  assert.equal(review.answeredQuestions[0].id, "q0");
  assert.equal(review.questionAnswers.q0.document_id, "doc-two");
});
