# Docgrain

> **English:** Docgrain turns a company's PDF, DOCX, XLSX, TXT and PNG/JPEG documents into one
> versioned, source-linked canonical model that people can review and edit. The goal is to publish
> that model as a shared data pool for AI assistants, mobile apps and websites; the project is
> **pre-alpha** and only the first half of that path works today.

Docgrain, şirketlerin dağınık belgelerinden (PDF, DOCX, XLSX, TXT, PNG/JPEG) kaynağına bağlı,
sürümlenebilir ve insan tarafından düzeltilebilir tek bir bilgi modeli üretir.

## Ne yapmak için var?

Dört hedef; bugün hangilerinin çalıştığı [Bugün durum](#bugün-durum) tablosundadır.

1. **Her formatı tek modele çevirir.** Altı format, kaynağa bağlı (sayfa, hücre, kutu) tek bir
   canonical modele normalize edilir. Eldeki bilginin kaynağı her zaman gösterilebilir.
2. **Yeniden işlemeden sürümler.** Bir düzeltme ya da yeni dosya sürümü tüm belgeyi baştan
   işlemeden, yalnızca değişen kısmı yeni bir revision olarak ekler. Eski revision'lar korunur.
3. **Koleksiyonları ortak veri havuzu yapar.** Odalar, restoranlar, aktiviteler gibi tipli listeler
   tek havuzda toplanır; aynı onaylı veriyi yapay zeka, mobil uygulama ve web sitesi kullanır.
4. **Model bağımsız, hızlı cevap verir.** Yapay zeka erişimi OpenAI uyumlu uçlara dayanır; embedding
   isteğe bağlıdır ve kritik yolda değildir.

```text
PDF / DOCX / XLSX / TXT / PNG / JPEG
        │  yükle + doğrula
        ▼
   canonical model  ◄── insan incelemesi (kaynakla yan yana, her düzenleme yeni revision)
        │
        ├─► yayın: JSON / Markdown / ZIP            (bugün var)
        └─► koleksiyonlar → API / yapay zeka erişimi (henüz yok)
```

Docgrain bir sohbet botu değildir; yayın paketleri, API'ler ve araç tanımları sunar. Çekirdek
genel amaçlıdır: sektöre özel şemalar (örn. otelcilik) çekirdeğin dışında kalır.

## Bugün durum

**Pre-alpha.** Aşağıdaki tablo bugün kodda çalışanı ve henüz çalışmayanı ayırır. Plan:
[`docs/plan/ROADMAP.md`](docs/plan/ROADMAP.md).

| Çalışıyor | Henüz yok |
| --- | --- |
| Altı format yükleme ve normalize etme (PDF, DOCX, TXT, XLSX, PNG, JPEG; basılı TR/EN OCR) | Bazı PDF'lerdeki tabloların doğru tablo olarak çıkarılması |
| Canonical model ve kaynak kanıtı (sayfa, hücre, kutu) | Mevcut belgeye yeni dosya sürümü yükleme ve "neler değişti" görünümü |
| Kaynakla yan yana inceleme; düzenlemeler değişmez (immutable) revision olarak kaydedilir | Koleksiyon çıkarımı (odalar, restoranlar vb. kayıtlar) |
| Yayın: canonical JSON, Markdown, `ai.json`, chunks ve ZIP | Uygulamalar için erişim API'si |
| `docgrain-eval` ile ölçüm (aşağıda) | Model bağımsız yapay zeka erişimi (araç tanımları, "Dene" ekranı) |
| Demo modu (sentetik, salt okunur) | Kimlik doğrulama, çok kiracılı yetkilendirme, kuyruk kurtarma |

Bazı ileri parçalar (retrieval, lifecycle, canlı kaynak) kodda vardır ama ürün yolunun
parçası olarak sayılmaz; ilgili aşama gerektirene kadar yeniden kullanılır. Bir işin `done`
görünmesi anlamın doğru olduğunu kanıtlamaz; ölçüm sonuçları belirleyicidir.

## Hızlı başlangıç

### Canlı yığın (Docker Compose)

```sh
cp .env.example .env
docker compose up --build
```

| Servis | Adres |
| --- | --- |
| Web arayüzü | http://localhost:3000 |
| API ve OpenAPI | http://localhost:8000/docs |
| MinIO konsolu | http://localhost:9001 |

Compose; API, worker, web, PostgreSQL, Redis, MinIO ve Qdrant servislerini başlatır. Qdrant
henüz bir özelliğe bağlı değildir. `.env` dosyası Git'e girmez; yerel değerlerdeki parolalar
yalnızca geliştirme içindir. Harici Vision ve Gemini çağrıları varsayılan olarak kapalıdır.

### Demo modu (altyapısız)

Sentetik, salt okunur veri gösterir; yükleme istekleri `409` döner, worker gerekmez.

```powershell
python -m pip install -e 'packages/domain[validation]' -e 'apps/api[dev]'
$env:USE_FIXTURES = "true"
python -m uvicorn docgrain_api.main:app --port 8000
```

Ayrı bir terminalde:

```sh
cd apps/web
npm ci
npm run dev
```

Çalışan modu `GET /healthz` yanıtındaki `mode` alanı (`live` veya `demo`) gösterir.

### Testler

Python 3.12 gerekir. CI de `pymupdf>=1.24` kurar; yoksa `pip install "pymupdf>=1.24"` ekleyin.

```sh
python -m pip install -e 'packages/domain[validation]' -e 'apps/api[dev]'
python -m pytest -q
ruff check apps packages tests benchmarks docs/examples
cd apps/web && npm ci && npm run build
```

Aynı üçü tek komutla: `make quality` (`make test`, `make lint`, `make web-build` ayrı da çalışır).
Docling, EasyOCR, PostgreSQL ve MinIO entegrasyon testleri worker Docker imajında koşar.

## Ölçüm

Bir şey ancak ölçülünce "bitti" sayılır. `docgrain-eval`, yayımlanmış belge içeriğini altın
sorular ve tablo gerçekleriyle belirleyici (deterministik) biçimde puanlar:

```sh
pip install -e packages/evaluation
docgrain-eval run --questions <sorular.jsonl> --workspace ws_local \
  --api http://localhost:8000 --dry-run
```

Model çağrısı yalnızca `--dry-run` kaldırılıp bir OpenAI uyumlu uç ve anahtar verildiğinde
yapılır. `tables` ve `compare` komutları da vardır. Ayrıntı: [`docs/plan/eval.md`](docs/plan/eval.md),
altın veri biçimi: [`docs/plan/golden-format.md`](docs/plan/golden-format.md).

Altın veri, gerçek belgeler ve ölçüm çıktıları (`data/`) **Git'te tutulmaz**; depo herkese açıktır.

## Nasıl geliştiriyoruz

- **Teknik lider Claude Code**; ürün sahibi kullanıcıdır. Lider iş paketlerini yazar, inceler,
  kabul eder ve commit/PR açar.
- **Adlandırılmış Codex ajanları** her iş paketini kendi git worktree'sinde, kendi
  `codex/<wp-id>` dalında yapar; Git'e yazmaz.
- Kurallar: [`AGENTS.md`](AGENTS.md). İş paketleri: [`docs/plan/wp/`](docs/plan/wp/). Ekip ve
  yardımcı betikler: [`docs/plan/team.json`](docs/plan/team.json), [`scripts/team/`](scripts/team/).
- Her değişiklik incelenir ve kabul kriterleriyle ölçülür. Kaynak belgelerin içindeki yönergeye
  benzeyen metin veri sayılır, talimat sayılmaz. Katkı notları: [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Mimari ve kararlar

- Güncel yapı: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Karar kayıtları (ADR): [`docs/adr/`](docs/adr/README.md). Yol haritası ile çeliştiğinde yol haritası geçerlidir.
- `docs/` altındaki eski aşama belgeleri (M1–M2, N1–N3: [`N2_SOURCE_STRUCTURE.md`](docs/N2_SOURCE_STRUCTURE.md),
  [`USER_REVIEW.md`](docs/USER_REVIEW.md), [`PRE_EMBEDDING_OUTPUT.md`](docs/PRE_EMBEDDING_OUTPUT.md) vb.) tarihçe olarak durur;
  bugünkü ürün yönü için [yol haritasına](docs/plan/ROADMAP.md) bakın.
- Güvenlik bildirimi: [`SECURITY.md`](SECURITY.md)

## License

MIT; bkz. [`LICENSE`](LICENSE).
