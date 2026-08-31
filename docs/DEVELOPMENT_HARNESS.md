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

## 2. Mevcut harness

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

## 3. Aşamalar

## Altyapı servisleri ve model rolleri

Bu servisler ilk aşamada Docker Compose ile hazır edilir; uygulama kodu
olmadan tek başlarına ürün özelliği oluşturmazlar:

- **PostgreSQL:** metadata, sürümler, job kayıtları ve ileride keyword search.
- **Redis:** durable job kuyruğu; API ile worker arasındaki sınır.
- **MinIO:** orijinal dosya, sayfa render'ı ve artifact'ların lokal S3 uyumlu deposu.
- **Qdrant:** embedding tabanlı chunk retrieval için vector index.
- **Docling:** PDF/DOCX/PPTX/XLSX gibi dosyalardan canonical Markdown ve
  structured JSON çıkaran birincil parser. Henüz kurulmadı; C aşamasında adapter
  arkasına alınarak kurulacak.
- **Gemini Flash:** kalite kapısına takılan taranmış veya layout-complex
  sayfalarda vision fallback/enrichment. Her çıktısı `derived` olarak işaretlenir.
- **Gemini embedding:** Qdrant'a yazılacak vector üretimi için ayrıca seçilecek;
  Flash modeli embedding modeli değildir.

Önerilen sıra: önce Docling + MinIO ile artifact üretimi, sonra yalnızca gerekli
sayfalarda Gemini Vision, ardından embedding ve Qdrant. Böylece her sayfayı
gereksiz yere modele göndermeyiz ve maliyet/provenance kontrol altında kalır.

### Aşama A — Temeli sabitle

- [x] API/domain contract smoke testleri
- [x] Docker Compose altyapı iskeleti
- [x] Public repo ve CI kalite workflow'u
- [x] Artefact tasarımının ilk Dokümanlar ekranına aktarılması
- [ ] Web UI'ı gerçek `/v1` API client'ına bağlamak
- [ ] API OpenAPI tiplerini `apps/web/lib/api/schema.d.ts` içine üretmek

**Bitti sayılır:** UI artık sahte diziden değil API response'undan beslenir ve
contract testi response shape değişikliklerini yakalar.

### Aşama B — Gerçek doküman kaydı ve durable job

- [ ] Upload endpoint'i ve kaynak kaydı
- [ ] Object storage adapter arayüzü; önce MinIO implementasyonu
- [ ] PostgreSQL repository ve migration altyapısı
- [ ] Redis job enqueue/dequeue akışı
- [ ] Worker'ın `register -> render -> extract -> publish` dikey dilimi
- [ ] Job retry ve idempotency testi

**Bitti sayılır:** Bir PDF yükleme isteği dosyayı kaydeder, işi kuyruğa alır,
API isteği içinde extraction çalıştırmaz ve job tekrarlandığında duplicate
version üretmez.

### Aşama C — İlk gerçek artifact pipeline'ı

- [ ] PDF render ve page image storage
- [ ] Docling parser adapter
- [ ] Canonical Markdown ve structured JSON artifact'ları
- [ ] Page-level quality gate
- [ ] Partial/failed sonuçların manifest'e yazılması
- [ ] Küçük golden PDF fixture seti

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
- [ ] Contextual `embedding_text`
- [ ] Embedding provider interface
- [ ] Qdrant/vector index adapter
- [ ] PostgreSQL keyword search
- [ ] Chunk boundary evaluation fixture'ları

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

## 4. Her iş için mini spec şablonu

Yeni bir issue/branch açarken şu şablon doldurulur:

```md
## Amaç

## Kullanıcı akışı

## API/domain etkisi

## Provenance ve güvenlik etkisi

## Test planı
- [ ] Domain/unit
- [ ] API contract
- [ ] Fixture/integration
- [ ] UI state

## Tamamlanma ölçütü

## ADR veya migration gerekiyor mu?
```

## 5. Branch ve commit kuralı

- `dev`: günlük entegrasyon branch'i.
- Özellikler: `feat/<kısa-ad>`, düzeltmeler: `fix/<kısa-ad>`.
- Her PR CI yeşil olmalı ve bir sonraki aşamanın tamamlanma ölçütüne bağlanmalı.
- Contract değişiklikleri UI değişikliğinden önce belgelenmeli.
- Public repo'ya gerçek belge, secret, signed URL veya generated storage
  çıktısı gönderilmemeli.

## Sıradaki iş

Bir sonraki dikey dilim: **Aşama A — UI'ı gerçek `/v1/documents` endpoint'ine
bağlamak ve OpenAPI tip üretimini eklemek.** Bu iş tamamlanınca sahte veri
ekranı ile API ekranı aynı contract üzerinden doğrulanabilecek.
