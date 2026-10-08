# Kayıt çıkarma motorları karşılaştırması (WP99)

Bu protokolü lead özel şirket dosyaları ve **çıktılardan bağımsız hazırlanmış anahtar** ile çalıştırır.
Bu WP gerçek model çağrısı veya şirket ölçümü yapmaz. Motor varsayılanı `docgrain` kalır.
Anahtarı, belge içeriğini ve ham model günlüklerini Git'e veya terminal çıktısına taşımayın.

## Kurulum ve sabit girdiler

Lead kendi venv/worker ortamında `packages/records[graph]` ekini kurar. Sabit sürümler:
`docling-graph==1.9.1`, `litellm==1.82.6`; 1.82.7/1.82.8 kullanılmaz.
Bu pin bir güvenlik sertifikası değildir; lead dağıtım hash'lerini ayrıca doğrulayıp saklar.
Kurulum sonrası `python -m pip check` ve aşağıdaki isteğe bağlı sahte taşıma testi çalıştırılır:

```powershell
$python = 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python'
& $python -m pytest -q tests/unit/test_graph_adapter.py
```

API'nin belge başlarını ölçüm süresince değiştirmeyin. Aynı kabul edilmiş `schema.v<N>.json`,
aynı belge kimlikleri, kaynak sürümleri, revision/hash ve `context.md` byte'ları üç kolda aynı olmalı.
Kaynaklar ve anahtar yerel/özel kalır. `documents.json` yalnızca belge kimliklerinden oluşan bir JSON listesi.
API çıktılarının pinlerini dondurulmuş manifestin orijinalleriyle lead karşılaştırır.

PowerShell oturumunda şu değişkenleri özel girdilere göre ayarlayın. Anahtarın değeri komuta yazılmaz;
`DOCGRAIN_BENCH_KEY` oturumda zaten tanımlı olmalı. Bağımsız **golden anahtarı** bu API anahtarından farklıdır.

```powershell
$python = 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python'
$env:PYTHONPATH = 'packages/records;packages/evaluation;packages/domain'
$private = Join-Path $PWD 'data/extract-engine-ab'
$schema = Join-Path $private 'schema.v1.json'
$documents = Get-Content -LiteralPath (Join-Path $private 'documents.json') -Raw | ConvertFrom-Json
$api = 'http://localhost:8000'
$baseUrl = 'https://your-compatible-endpoint.example/v1'
$model = 'your-workspace-model'
$manifest = Join-Path $private 'manifest.frozen.json'
$golden = Join-Path $private 'golden.records.jsonl'
$questions = Join-Path $private 'golden.questions.jsonl'

& $python -m docgrain_eval.record_golden validate --manifest $manifest --golden $golden --questions $questions
if ($LASTEXITCODE -ne 0) { throw 'Bağımsız anahtar ölçüme hazır değil' }
```

## Üç kol, en az üç tekrar

`docgrain`, `graph-plain`, `graph-quoted` ayrı çalışır. Aynı workspace model/endpoint,
sıcaklık 0 ve retry sınırı kullanılır. Graph'ta direct/many-to-one, chunking/gleaning kapalı,
tek worker ve 32k context limiti sabittir. Docgrain'in bölümleme ve ek taramaları mevcut
varsayılanlarıyla korunur; farkları maliyet/kapsam karşılaştırmasının parçasıdır.
Graph bölümleme/concurrency/focused-pass bayraklarını kullanmaz.

```powershell
foreach ($arm in @('docgrain', 'graph-plain', 'graph-quoted')) {
    foreach ($repeat in 1..3) {
        $runRoot = Join-Path $private "$arm/run-$repeat"
        if (Test-Path -LiteralPath $runRoot) { throw 'Eski ölçümü ezmeyin' }
        foreach ($document in $documents) {
            $out = Join-Path $runRoot "sources/$document"
            $engineArgs = @('--engine', 'docgrain')
            if ($arm -ne 'docgrain') {
                $variant = $arm.Substring(6)
                $engineArgs = @('--engine', 'docling-graph', '--graph-variant', $variant)
            }
            $elapsed = [System.Diagnostics.Stopwatch]::StartNew()
            & $python -m docgrain_records extract --document $document --schema $schema `
                --api $api --base-url $baseUrl --model $model --api-key-env DOCGRAIN_BENCH_KEY `
                --timeout 60 --retries 3 --out $out @engineArgs
            $exitCode = $LASTEXITCODE
            $elapsed.Stop()
            New-Item -ItemType Directory -Path $out -Force | Out-Null
            @{ engine = $arm; repeat = $repeat; exit_code = $exitCode; seconds = $elapsed.Elapsed.TotalSeconds } |
                ConvertTo-Json | Set-Content -LiteralPath (Join-Path $out 'benchmark.json') -Encoding utf8
            if ($exitCode -ne 0) { throw 'Eksik motor çalışması: başarısızlığı ayrıca kaydedin' }
        }

        & $python -m docgrain_records match --records (Join-Path $runRoot 'sources') `
            --schema $schema --out (Join-Path $runRoot 'match') --auto-accept strong
        if ($LASTEXITCODE -ne 0) { throw 'Eşleştirme başarısız' }
        & $python -m docgrain_records merge --records (Join-Path $runRoot 'sources') `
            --schema $schema --matches (Join-Path $runRoot 'match/match_proposals.json') `
            --out (Join-Path $runRoot 'merge')
        if ($LASTEXITCODE -ne 0) { throw 'Birleştirme başarısız' }
    }
}
```

`match` model kullanmaz; yalnızca aynı mevcut güçlü eşleştirme kuralları uygulanır.
Graph'ın `knowledge_graph` çıktısındaki keep-first değerleri alınmaz; `extracted_models`
adayları ortak doğrulayıcı ve mevcut Docgrain birleştiricisinden geçer.

## Doğruluk, kararlılık, kapsam ve destek

Ham kayıt doğruluğunu **inceleme/düzeltme öncesinde**, kayıt dosyaları ve aynı context ile ölçün.
Ölçüm aracı çatışmaları `{candidates, review_state}` zarfında bekler; çıkarma artifact'i ise
birincil değer ve kaybeden aday listesini ayrı tutar. Aşağıdaki yalnız biçim dönüşümü bu farkı
giderir; hiçbir değer, kaynak, dil veya inceleme kararı değiştirilmez. Ham artifact saklanır.
Mevcut `record_golden` hizalaması `name` alanına dayanır. Kabul edilmiş şema başka bir kimlik
kullanıyorsa bağımsız golden kimliklerini bu çıktılara önceden belirlenmiş ID eşlemesiyle hizalayın;
otomatik isim eşleşmesinin o şemada çalıştığını varsaymayın. Aynı kaydın birden fazla belgedeki
görünümleri anahtarda ayrı belge/kayıt kimlikleriyle tutulmalı; yinelenen ID'leri gizlemeyin.

```powershell
foreach ($arm in @('docgrain', 'graph-plain', 'graph-quoted')) {
    foreach ($repeat in 1..3) {
        $runRoot = Join-Path $private "$arm/run-$repeat"
        @'
import json
import sys
from pathlib import Path
from docgrain_eval.consistency import coverage, load_run, load_sources

root = Path(sys.argv[1])
records = []
for path in sorted((root / 'sources').rglob('records.json')):
    batch = json.loads(path.read_text(encoding='utf-8'))
    for record in batch['records']:
        for field, losing in record.get('conflicts', {}).items():
            candidates = [record.get(field), *losing]
            candidates.extend(group.get(field) for group in record.get('i18n', {}).values())
            unique = {json.dumps(f, sort_keys=True): f for f in candidates if f is not None}
            record['conflicts'][field] = {'candidates': list(unique.values()),
                                         'review_state': record['review_state']}
        records.append(record)
(root / 'score-records.json').write_text(json.dumps(records, ensure_ascii=False), encoding='utf-8')
run = load_run(root / 'sources')
report = coverage(run, load_sources(root / 'sources', run.workspace))
(root / 'raw-coverage.json').write_text(json.dumps(report), encoding='utf-8')
'@ | & $python - $runRoot
        if ($LASTEXITCODE -ne 0) { throw 'Ölçüm biçimi dönüşümü başarısız' }
        $contextArgs = @()
        foreach ($document in $documents) {
            $contextArgs += @('--context', "$document=$(Join-Path $runRoot "sources/$document/context.md")")
        }
        & $python -m docgrain_eval.record_golden score --manifest $manifest --golden $golden `
            --questions $questions --records (Join-Path $runRoot 'score-records.json') `
            @contextArgs --out (Join-Path $runRoot 'accuracy')
        # 2: ölçüm tamamlandı ama hedef tutmadı; 1: girdi/çalışma hatası. İkisini ayırın.
    }
    & $python -m docgrain_eval.cli stability --runs (Join-Path $private "$arm/run-1/sources") `
        (Join-Path $private "$arm/run-2/sources") --out (Join-Path $private "$arm/stability-1-2")
    & $python -m docgrain_eval.cli stability --runs (Join-Path $private "$arm/run-2/sources") `
        (Join-Path $private "$arm/run-3/sources") --out (Join-Path $private "$arm/stability-2-3")
}
```

`support` **yalnız onaylı birleştirilmiş alanları** sayar. Lead her kolun birleştirme revision'ını
aynı inceleme politikasıyla inceleyip ayrı `reviewed/merge_revision.json` çıktısı oluşturur.
Tüm önerileri topluca kabul etmek, çelişkilere kazanan seçmek veya düzeltmelerden sonra elde edilen
skoru ham motor doğruluğu diye sunmak bu karşılaştırmayı geçersiz kılar.
İncelenmeyen alana ait 0 destek hatası başarı değildir; payda da raporlanır.

```powershell
foreach ($arm in @('docgrain', 'graph-plain', 'graph-quoted')) {
    $runRoot = Join-Path $private "$arm/run-1"
    & $python -m docgrain_eval.cli support --revision (Join-Path $runRoot 'reviewed/merge_revision.json') `
        --sources (Join-Path $runRoot 'sources') --out (Join-Path $runRoot 'support.json')
}
```

Her kolda `support.json.coverage` kaynak tablo/liste satırı kapsamını, golden raporu
alan/öğe kapsamını ve doğruluğu gösterir. Destek raporunun kapsama ölçümü incelenmiş revision'a
aittir; ham çıkarma kapsamını ayrı ölçmek için `docgrain_eval.consistency.coverage(load_run(sources),
load_sources(sources, workspace))` kullanın. Düz metin satırları bu satır paydasına dahil değildir.
Önceden anahtara yazılmış çelişkilerin **tüm adayları ve kaynakları**, ham kayıtların `conflicts`
alanında ve birleşim adaylarında görünmeli; durumları `needs_review` kalmalı. Golden raporunun
`hidden_conflict`, `wrong_conflict_candidate`, `unexpected_conflict` bulgularını kontrol edin.
Çelişkiyi Graph daha önce düşürdüyse doğrulayıcı geri üretemez; bu kol başarısız sayılır.

## Çağrı, belirteç, süre ve karar

`source.json.usage.calls` fiziksel taşıma denemelerini, başarılı raporlanan kullanım toplamını
ve `missing_usage_calls` eksik kullanım sayısını içerir. Graph'ın LiteLLM iç retries'i 0;
adapter retries'i ve Graph fallback istekleri ayrı sayılır. Bir hata yanıtında kullanım gelmediyse
gerçek maliyet bilinmez; 0 diye yorumlamayın. Sağlayıcının bağımsız faturalama kaydıyla doğrulayın.
`benchmark.json.seconds` tüm CLI süresidir (API okuma ve yazma dahil), saf model gecikmesi değildir.

Karar tablosunda her kol/tekrar için: alan doğruluğu, unsupported/published alan sayısı,
stability kayıt/alan oranı, golden recall/list coverage, kaynak satırı kapsamı,
korunan/beklenen çelişki sayısı, reddedilen alan ve failures, calls/tokens/eksik kullanım,
toplam süre ve maliyet bulunmalı. Ortalama yanında en kötü tekrarı da gösterin.
Geçiş ancak doğruluk farkı ≤1 yüzde puanı, unsupported 0 (payda >0), kararlılık eşit/iyi,
hiç kayıp çelişki yok ve maliyet ≤1.5× ise değerlendirilebilir. Bu WP geçiş yapmaz.

## Doğrulanmış sözleşmeler ve açık riskler

- 1.9.1 kaynak incelemesi: [`PipelineConfig`](https://github.com/docling-project/docling-graph/blob/v1.9.1/docling_graph/config.py),
  [`stages`](https://github.com/docling-project/docling-graph/blob/v1.9.1/docling_graph/pipeline/stages.py),
  [`connection override`](https://github.com/docling-project/docling-graph/blob/v1.9.1/docling_graph/llm_clients/config.py),
  [`LiteLLM client`](https://github.com/docling-project/docling-graph/blob/v1.9.1/docling_graph/llm_clients/litellm.py),
  [`provenance models`](https://github.com/docling-project/docling-graph/blob/v1.9.1/docling_graph/core/provenance/models.py).
  Repoda grep/Select-String ve bu kaynaklar import öncesi incelendi. Yerel optional paket kurulu değildi.
- İki kurulu-paket sahte LiteLLM testi paket eksikken skip olur. Gerçek `run_pipeline`, runtime
  `graph_id_fields` (özellikle quoted identity nesnesi), Graph dedup/truncation/fallback davranışı,
  chunk refs ve boş koleksiyon davranışı burada **çalıştırılarak doğrulanmadı**.
- Worker henüz orijinal DoclingDocument JSON'unu revision artifact olarak sunmuyor. Adapter bu nedenle
  aynı §N projection'ını metin öğeleri olan DoclingDocument JSON'una sarar; parser/OCR tekrar çalışmaz.
  Orijinal tablo/geometry korunmuş Docling artifact üzerinden benchmark bu WP'de yoktur.
- `plain`: ledger chunk `doc_item_refs` → §N; chunk ledger yoksa pre-parsed document text refs → §N.
  Kimlik ve tüm değer parçaları aynı, tekil blokta literal bulunmalı. Sayı alt dizileri reddedilir;
  unit dönüşümü/çeviri yok. Belirsiz bloklar reddedilir. Bu yaklaşım alanın anlamını ispatlamaz;
  özellikle aynı blokta birden çok kayıt/sayı varsa bağımsız anahtar gereklidir.
- `quoted`: her alan `{value, quote}`. Tekil §N eşleşmesi gerekir; tekrarlanan kısa alıntılar reddedilir.
  İki varyant belge dilini kullanır; karışık dilli belge için alan başına dil algılama/i18n kapsamı
  ölçülmelidir. Çok dilli ve çok uzun belgeler için eşit kapsam iddiası yoktur.
- Kaynak komutlarını reddeden guard her model isteğinde system mesajına eklenir. Upstream'ın özel
  istemci metotları (`_prepare_messages`, `_call_api`) 1.9.1'e bağlıdır. Import sırasında upstream
  `load_dotenv()` çağırır; adapter anahtarı yalnız connection override ile verir, env'e yazmaz.
  Upstream'ın logging/redaction ve LiteLLM yardımcı ağ davranışları lead'in kurulu ortamında ayrıca
  kontrol edilmelidir; debug/disk export kapalı tutulur.
