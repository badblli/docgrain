# Docgrain geliştirme planı ve harness

Bu doküman, Docgrain üzerinde çalışırken izlenecek sırayı, kalite kapılarını ve
her adımın tamamlanma ölçütlerini tanımlar. Amaç, UI prototipinden gerçek,
izlenebilir bir doküman işleme ürününe kontrollü şekilde ilerlemektir.

## 1. Çalışma döngüsü

Her özellik şu sırayla geliştirilir:

1. **Kapsamı yaz:** Kullanıcı davranışı, API etkisi ve veri/provenance etkisi
   belirtilir.
2. **Sözleşmeyi kontrol et:** Mevcut `/v1` response shape ve domain modelleri
   korunur. Değişiklik gerekiyorsa ADR veya migration note eklenir.
3. **Önce test:** Domain invariant, API contract ve gerekiyorsa fixture testi
   yazılır.
4. **Dikey dilimi uygula:** API, worker/pipeline ve UI değişiklikleri aynı
   küçük akış içinde tamamlanır.
5. **Yerelde doğrula:** `make quality` çalıştırılır. Windows'ta komutlar ayrı
   ayrı da çalıştırılabilir.
6. **Gözle kontrol et:** Web ekranı localhost'ta açılır; loading, empty,
   partial, failed ve stale durumları kontrol edilir.
7. **Commit et:** Küçük, tek amaçlı bir commit oluşturulur.

## 2. Ürün kabul ölçütleri

Her dikey dilim yalnızca metni değil dokümanın bütün yapısını korumalıdır:

- Metin, başlık, liste, tablo, görsel, grafik, diyagram, form ve caption ayrı
  yapılar olarak algılanır.
- Her yapı document version, sayfa ve mümkünse bounding box ile kaynağına bağlanır.
- Yapılar arası `described_by`, `references`, `continues_on`, `belongs_to` ve
  `sourced_from` ilişkileri document graph içinde saklanır.
- Her sayfa primary `VisionProvider` ile multimodal olarak işlenir. Kabul edilen
  OCR/layout/table extraction canonical normalized temsile katılabilir.
- Gemini/Qwen'in yorumlayıcı açıklama, özet ve ilişki çıkarımları `derived` olur.
- Vision çıktısı source region, ilgili node ID'leri, provider/model, prompt
  version, amaç ve confidence olmadan kabul edilmez.
- Chunk; metinle birlikte ilgili tablo/görsel bağlamını ve inherited metadata'yı
  taşıyabilir, fakat kullandığı her kaynağı açıkça listeler.
- Heading-first chunking esastır. Cosine similarity başlıksız metinde sınır
  sinyali, küçük overlap ise yalnızca token-aware fallback olarak kullanılır.
- Pipeline değişiklikleri golden document setinde metin, tablo, görsel-caption,
  ilişki, provenance, chunk sınırı ve primary vision extraction doğruluğuyla ölçülür.

## 3. Mevcut harness

Harness şu kalite kapılarını çalıştırır:

| Kapı | Komut | Amaç |
| --- | --- | --- |
| Python lint | `ruff check apps packages tests` | Stil, import ve güvenli Python kalıpları |
| API/domain testleri | `PYTHONPATH=apps/api:packages/domain pytest -q` | Sözleşme ve state-machine davranışı |
| Web build | `cd apps/web && npm ci && npm run build` | TypeScript ve production derleme |
| Tek komut | `make quality` | Yukarıdaki üç kapının yerel birleşimi |
| CI | `.github/workflows/quality.yml` | Push ve pull request üzerinde otomatik kontrol |

Windows PowerShell için Python test komutu:

```powershell
$env:PYTHONPATH = "apps/api;packages/domain"
py -m pytest -q
```

CI yeşil değilse özellik tamamlanmış sayılmaz. Uyarılar ayrıca incelenir;
özellikle dependency deprecation uyarıları bir sonraki bakım işine yazılır.

## 4. Aşamalar

## Altyapı servisleri ve model rolleri

Bu servisler ilk aşamada Docker Compose ile hazır edilir; uygulama kodu
olmadan tek başlarına ürün özelliği oluşturmazlar:

- **PostgreSQL:** metadata, sürümler, job kayıtları ve ileride keyword search.
- **Redis:** durable job kuyruğu; API ile worker arasındaki sınır.
- **MinIO:** orijinal dosya, sayfa render'ı ve artifact'ların lokal S3 uyumlu deposu.
- **Qdrant:** embedding tabanlı chunk retrieval için vector index.
- **Gemini Vision:** 200 DPI render edilen her sayfada primary multimodal
  extraction. Varsayılan concurrency 4, sayfa başına en fazla 3 retry; gerçek
  model adı provider config üzerinden seçilir.
- **Docling:** PDF/DOCX/PPTX/XLSX için deterministic ikinci parse; Gemini
  extraction'ını doğrulama, yapısal uzlaştırma ve fallback amacıyla kullanılır.
- **Gemini embedding:** Qdrant'a yazılacak vector üretimi için ayrıca seçilecek;
  Flash modeli embedding modeli değildir.

Önerilen sıra: render + provider contract + fake vision testleri, ardından gerçek
Gemini page extraction, document-level join/normalize, chunking, embedding ve
Qdrant/PostgreSQL index. Maliyet; sayfa concurrency, retry bütçesi, model profili
ve artifact cache ile kontrol edilir.

### Aşama A — Temeli sabitle

- [x] API/domain contract smoke testleri
- [x] Docker Compose altyapı iskeleti
- [x] Public repo ve CI kalite workflow'u
- [x] Artefact tasarımının ilk Dokümanlar ekranına aktarılması
- [x] Web UI'ı gerçek `/v1` API client'ına bağlamak
- [ ] API OpenAPI tiplerini `apps/web/lib/api/schema.d.ts` içine üretmek

**Bitti sayılır:** UI artık sahte diziden değil API response'undan beslenir ve
contract testi response shape değişikliklerini yakalar.

### Aşama B — Gerçek doküman kaydı ve durable job

- [x] Upload endpoint'i ve kaynak kaydı
- [x] Local MinIO bucket ve API upload proxy
- [ ] Web'deki `Dosya seç` akışını register → upload → confirm API zincirine bağlamak
- [ ] Upload progress, hata ve queued/running/done durumlarını göstermek
- [ ] Production için direct signed-upload adapter
- [x] PostgreSQL repository altyapısı (şema başlangıçta oluşturuluyor; versioned migration dosyaları sonraki bakım işi)
- [x] Redis job enqueue/dequeue akışı ve kalıcı `queued → running` geçişi
- [ ] Worker'ın `register -> render -> extract -> publish` dikey dilimi
- [ ] Job retry ve idempotency testi

**Bitti sayılır:** Bir PDF yükleme isteği dosyayı kaydeder, işi kuyruğa alır,
API isteği içinde extraction çalıştırmaz ve job tekrarlandığında duplicate
version üretmez.

### Aşama C — İlk gerçek artifact pipeline'ı

- [ ] PDF render ve page image storage
- [x] Docling parser adapter
- [x] Docling Markdown ve structured JSON artifact prototipi
- [ ] Primary `VisionProvider` request/response sözleşmesi
- [ ] Fake vision provider ile tüm page-level case testleri
- [ ] Her sayfada Gemini multimodal extraction (default 4 parallel, 3 retry)
- [ ] Page Markdown + structured region artifact'ları
- [ ] Document join ve heading normalization; destructive rewrite guard
- [ ] Text/table/asset/form/page-region yapılarını normalize etmek
- [ ] İlk document graph node ve relationship sözleşmesini eklemek
- [ ] Table continuation, caption ve cross-reference ilişkilerini korumak
- [ ] Extraction sonrası page-level quality gate ve Docling cross-check
- [ ] Evidence-bound semantic description/relationship enrichment
- [ ] Partial/failed sonuçların manifest'e yazılması
- [ ] Küçük multimodal golden document fixture seti

Yerel doğrulama seti (public repoya eklenmez): `C:\Users\Lenovo\Documents\docs`
içindeki otel fact sheet'leri. İlk smoke örneği 7 sayfalık Corendon Playa
Kemer fact sheet'tir; büyük Maxx/Regnum dosyaları performans/layout, menüler
tablo ve haritalar görsel-layout sınır testi içindir. CI için telifli dosyalar
yerine redakte edilmiş küçük fixture'lar üretilecektir.

Kaynak dosya PDF ile sınırlı değildir: PNG/JPEG/WebP menü ve harita yüklemeleri
de aynı immutable version akışına girer. Bunlar için sayfanın kendisi kaynak
görsel olur. Kabul edilen OCR/layout extraction canonical normalized temsile
katılabilir; semantik açıklama ve yorumlar `derived` artifact olarak saklanır.

**Bitti sayılır:** Başarılı, kısmi ve başarısız PDF'ler immutable version ve
page-level provenance ile incelenebilir.

### Aşama D — Review console'u tamamla

- [ ] Document detail ve version görünümü
- [ ] Pipeline ekranı ve stage detail
- [ ] Page render + Markdown/JSON inspector
- [ ] Chunk explorer ve provenance bağlantıları
- [ ] Tables/assets gallery
- [ ] Jobs ve providers ekranları
- [ ] Loading/empty/partial/failed/stale state'leri
- [ ] 2 saniyelik terminal olana kadar polling

**Bitti sayılır:** Bir operatör dokümandan başlayıp herhangi bir chunk veya
artifact'ın kaynak sayfasına geri gidebilir; derived content canonical
extraction'dan görsel olarak ayrıdır.

### Aşama E — Retrieval-ready output

- [ ] Heading-aware chunker
- [ ] Başlıksız metin için cosine-similarity boundary değerlendirmesi
- [ ] Yalnızca token-aware fallback için ölçülü overlap
- [ ] Text + table/asset context taşıyan multimodal chunk sözleşmesi
- [ ] Contextual `embedding_text`
- [ ] Embedding provider interface
- [ ] Qdrant/vector index adapter
- [ ] PostgreSQL keyword search
- [ ] Chunk boundary evaluation fixture'ları
- [ ] Metadata/provenance filtreleri ve graph ilişki referansları

**Bitti sayılır:** Her chunk document version, page, section ve kaynak URI
provenance'ını korur; retrieval çıktısı aynı kaynağa geri bağlanır.

### Aşama F — Üretim güvenilirliği

- [ ] Provider timeout, retry ve circuit-breaker politikaları
- [ ] Correlation ID ve structured logging
- [ ] Metrics/tracing
- [ ] Tenant/access scope enforcement
- [ ] Signed URL ve secret boundary testleri
- [ ] Backup, retention ve operasyon runbook'u

**Bitti sayılır:** Hatalı provider veya worker yeniden başlatması veri
provenance'ını bozmaz; hassas belge içeriği loglara veya public repo'ya düşmez.

## 5. Golden document değerlendirme seti

Public ve sentetik fixture'lar en az şu sınıfları kapsar:

- Basit metin ve heading hiyerarşisi
- Taranmış/OCR gerektiren sayfa
- Çok kolonlu ve karmaşık layout
- Birleşik hücreli ve birden fazla sayfaya taşan tablo
- Grafik/diyagram ve caption ilişkisi
- Görseli çevre metninden anlam kazanan sayfa
- Form alanları ve işaret kutuları
- Türkçe ve İngilizce içerik

Her pipeline sürümünde metin doğruluğu, tablo yapısı, görsel-caption eşleşmesi,
document-graph ilişkileri, provenance bütünlüğü, chunk sınır kalitesi, primary
vision extraction ve retry/partial davranışı karşılaştırılır.

## 6. Her iş için mini spec şablonu

Yeni bir issue/branch açarken şu şablon doldurulur:

```md
## Amaç

## Kullanıcı akışı

## API/domain etkisi

## Provenance ve güvenlik etkisi

## Multimodal/document-graph etkisi

## Test planı
- [ ] Domain/unit
- [ ] API contract
- [ ] Fixture/integration
- [ ] UI state
- [ ] Golden document/evaluation

## Tamamlanma ölçütü

## ADR veya migration gerekiyor mu?
```

## 7. Branch ve commit kuralı

- `dev`: günlük entegrasyon branch'i.
- Özellikler: `feat/<kısa-ad>`, düzeltmeler: `fix/<kısa-ad>`.
- Her PR CI yeşil olmalı ve bir sonraki aşamanın tamamlanma ölçütüne bağlanmalı.
- Contract değişiklikleri UI değişikliğinden önce belgelenmeli.
- Public repo'ya gerçek belge, secret, signed URL veya generated storage
  çıktısı gönderilmemeli.

## Sıradaki iş

Bir sonraki dikey dilim: **Aşama B — web'deki gerçek upload akışını register →
upload → confirm API zincirine bağlamak; ardından job'u terminal duruma kadar
polling ile izlemek.** Bu akış küçük sentetik PDF ile doğrulandıktan sonra worker
artifact/provenance zinciri tamamlanacak. Ardından fake provider ile page-level
case'ler sabitlenip Gemini her 200 DPI sayfada primary multimodal extractor olarak
çalıştırılacak. Cosine similarity ve overlap ise heading-aware chunking sonrasında
kontrollü fallback olarak eklenecek.
