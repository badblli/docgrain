<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="apps/web/public/brand/logo-dark.svg">
    <img src="apps/web/public/brand/logo-light.svg" alt="docgrain" width="260">
  </picture>
</p>

<p align="center">
  <b>Şirketinizin ortak hafızası, kaynağıyla birlikte.</b><br>
  Docgrain dağınık şirket belgelerini yapay zeka ve uygulamalar için güvenilir, sürümlü ve ortak bir
  bilgi kaynağına dönüştürür. Çelişki sorulur, tahmin edilmez. Belgeleri okumak
  <a href="https://github.com/docling-project/docling">Docling</a>'in işi; Docgrain üstündeki bilgi katmanıdır.
</p>

<p align="center">
  <a href="https://github.com/badblli/docgrain/actions/workflows/quality.yml"><img src="https://github.com/badblli/docgrain/actions/workflows/quality.yml/badge.svg?branch=dev" alt="Kalite"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/lisans-MIT-245d65.svg" alt="Lisans: MIT"></a>
  <img src="https://img.shields.io/badge/durum-pre--alpha-956316" alt="Durum: pre-alpha">
  <img src="https://img.shields.io/badge/python-3.12-245d65" alt="Python 3.12">
</p>

<p align="center"><a href="README.md">English</a> · <a href="docs/plan/ROADMAP.md">Yol haritası</a> · <a href="#hızlı-başlangıç">Hızlı başlangıç</a> · <a href="docs/brand/BRAND.md">Marka</a></p>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/brand/screens/ozet-dark.png">
  <img src="docs/brand/screens/ozet-light.png" alt="Docgrain konsolu: dört ölçülü şirket özeti, belgeye göre gruplu bir çelişki sorusu ve koleksiyon kartları">
</picture>
<p align="center"><sub>Marka kitindeki örnek veriler; gerçek bir şirket değildir.</sub></p>

> **Dürüstçe: pre-alpha.** Docgrain bugün bir şirketin klasörünü tek seferde alıyor, koleksiyonlarını
> keşfediyor, kaynağa bağlı kayıtlar çıkarıyor, gerçek çelişkileri insanlara soruyor ve önizleme ile onaylı
> JSON yayınlıyor. Dosya sürümleme, yapay zeka erişim katmanı ve kimlik doğrulama henüz yok. Aşağıdaki
> liste neyin çalıştığını tam olarak söylüyor.

## Neden?

- **Şirket bilgisi PDF, Excel ve Word içinde sıkışıp kalır.** Tablolar bozulur, taramalar resimdir,
  aynı bilgi birbiriyle çelişen üç dosyada durur.
- **Kaynağı olmayan RAG halüsinasyon üretir.** Cevap bir sayfayı, hücreyi ya da kutuyu
  gösteremiyorsa kimse doğrulayamaz; dolayısıyla güvenilmemelidir.
- **Tek kelimelik düzeltme tüm belgeyi baştan işletir.** Bir fiyatı güncellemek, her dosyayı yeniden
  işlemeyi ve insanların yaptığı düzeltmeleri kaybetmeyi gerektirmemeli.

## Ne yapar?

İşaretler gerçek durumu gösterir: ✅ bugün kodda çalışıyor, 🚧 yapılıyor, 🗺 planlandı.

1. **Her biçim için tek model.** ✅ PDF, DOCX, XLSX, TXT, PNG ve JPEG tek bir kanonik modele dönüşür; her
   bilgi kanıtını (sayfa, hücre, kutu, satır) taşır. ✅ Bir şirketin klasörü tek seferde kendi çalışma
   alanına yüklenir; aynı dosya ikinci kez işlenmez.
2. **Koleksiyonlar keşfedilir, sabit değildir.** ✅ OpenAI uyumlu bir model şirketin kendi koleksiyonlarını
   (odalar, restoranlar, hizmetler…) içerikten önerir; alıntılar kaynakta doğrulanır, adlar şirketler arası
   tek bir sözlüğe hizalanır. ✅ Kayıtlar belgeler ve diller arasında birleştirilir (önce İngilizce, diğer
   diller çeviri olarak).
3. **Tahmin yok.** ✅ Yayınlanan her alan kaynağını gösterir; kanıtsız alan reddedilir. ✅ Belgeler
   çeliştiğinde Docgrain tek ve net bir soru sorar; seçenekler belgeye göre gruplanır. Tekrarlayan
   programlar tanınır: cumartesileri yer değiştirmiş iki parti 32 tarih değil, tek soru olur. ✅ Her cevap
   yeni ve değiştirilemez bir sürüm yayınlar.
4. **Yapay zekayı ve uygulamaları besler.** ✅ Koleksiyon başına `preview` ve `approved` modlarında salt
   okunur JSON (ETag ile) ve kısa bir Markdown bağlamı. 🗺 OpenAI uyumlu modeller için araç tanımları;
   embedding isteğe bağlı.
5. **Yeniden işlemeden sürüm.** 🗺 Bir dosyanın yeni sürümünü yükleyip verilmiş cevapları korumak.

## Nasıl çalışır?

```text
şirket klasörü (PDF / DOCX / XLSX / TXT / PNG / JPEG)
        │  ingest-folder: her şirkete bir çalışma alanı
        ▼
   kanonik model, her bilgi kanıtıyla
        │  koleksiyonları keşfet → kayıtları çıkar → eşleştir ve birleştir
        ▼
   birleşik sürüm ── gerçek çelişkiler için sorular ◄── insanlar cevaplar (Sorular)
        │                                                │ yeni, değiştirilemez sürüm
        ▼                                                ▼
   yayın: önizleme / onaylı JSON + context.md  ──►  yapay zeka, uygulamalar, web sitesi
```

## Hızlı başlangıç

Docker gerekir; demo için Python 3.12 ve Node yeterlidir.

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

```sh
python -m pip install -e 'packages/domain[validation]' -e 'apps/api[dev]'
python -m pytest -q
ruff check apps packages tests benchmarks docs/examples
cd apps/web && npm ci && npm run build
```

CI ayrıca `pymupdf>=1.24` kurar; yoksa ekleyin. Aynı üçü `make quality` ile çalışır (`make test`,
`make lint`, `make web-build` ayrı da çalışır). Docling, EasyOCR, PostgreSQL ve MinIO entegrasyon
testleri worker Docker imajında koşar.

## Ölçülür, iddia edilmez

Ölçülmeyen şey "bitti" sayılmaz. `docgrain-eval`, yayımlanmış belge içeriğini altın sorular ve
tablo gerçekleriyle belirleyici (deterministik) biçimde puanlar: cevap doğruluğu, cevaplanamayan
sorularda çekimserlik ve atıf isabeti. Sayılar her sürümde yayımlanacak. **İlk ölçüm taban çizgisi
yolda**; henüz yayımlanmış bir sayı yok, bu yüzden burada da sayı yok.

```sh
pip install -e packages/evaluation
docgrain-eval run --questions <sorular.jsonl> --workspace ws_local \
  --api http://localhost:8000 --dry-run
```

Model çağrısı yalnızca `--dry-run` kaldırılıp OpenAI uyumlu bir uç ve anahtar verildiğinde yapılır.
`tables` ve `compare` komutları da vardır. Ayrıntı: [`docs/plan/eval.md`](docs/plan/eval.md); altın
veri biçimi: [`docs/plan/golden-format.md`](docs/plan/golden-format.md). Altın veri, gerçek belgeler
ve ölçüm çıktıları (`data/`) Git'e girmez; depo herkese açıktır.

## Bir yapay zeka ekibi geliştiriyor

Docgrain'i küçük bir yapay zeka ajan ekibi, bir insan ürün sahibiyle geliştiriyor. **Claude Code teknik
lider**: iş paketlerini planlar, her değişikliği inceler, testleri yeniden çalıştırır ve birleştirmeden önce
gerçek veride ölçer. Pokémon adlı mühendisler (Charizard, Alakazam, Porygon, Jigglypuff, Bulbasaur) Codex
veya Gemini üzerinde, her biri kendi git worktree'sinde çalışır. **Smeargle** (Claude) marka ve ekranlardan
sorumlu tasarımcıdır ([marka kiti](docs/brand/BRAND.md)); **Chatot** (Claude) belgeleri yazar. Web konsolu
Next.js, Tailwind CSS ve shadcn/ui ile yazılıdır. Kaynak belgelerde talimat gibi görünen metin her zaman veri
olarak ele alınır, komut olarak değil. Kurallar: [`AGENTS.md`](AGENTS.md); iş paketleri:
[`docs/plan/wp/`](docs/plan/wp/); araçlar: [`scripts/team/`](scripts/team/).

## Yol haritası

Tam plan: [`docs/plan/ROADMAP.md`](docs/plan/ROADMAP.md).

- **D1 Ölçüm:** altın sorular ve tablolar, herhangi bir OpenAI uyumlu modele karşı `docgrain-eval`, ilk taban çizgisi.
- **D2 Çıkarım düzeltmeleri:** düzleşen tablolar gerçek tablo olur; dış görseller bağlantı olarak tutulur.
- **D3 Dosya sürümleri:** yeni sürüm yükle, farkı gör, onaylı düzenlemeleri ileri taşı.
- **D4 Koleksiyonlar:** kanıtlı tipli kayıtlar, görünür çakışmalarla çok belgeli birleştirme.
- **D5 Erişim katmanı:** uygulamalar için salt okunur REST, önceden hesaplanmış yapay zeka bağlamı, OpenAI araç tanımları.
- **D6 Değişiklik yayılımı:** bir düzenleme yalnızca etkilenen parçaları yeniden yayımlar, webhook'larla.
- **D7 Basit arayüz:** ekran başına tek ana eylem, mobil uyumlu (D3'ten itibaren paralel).

Sonra: embedding yalnızca ölçüm ihtiyaç gösterirse; kimlik doğrulama, çok kiracılı yalıtım, kuyruk kurtarma.

## Katkı

Küçük, iyi test edilmiş değişiklikler memnuniyetle karşılanır; bkz. [`CONTRIBUTING.md`](CONTRIBUTING.md).
Mimari: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); kararlar: [`docs/adr/`](docs/adr/README.md).
Güvenlik bildirimi: [`SECURITY.md`](SECURITY.md). API anahtarı ya da gerçek müşteri dosyası commit etmeyin.

## Lisans

MIT; bkz. [`LICENSE`](LICENSE).
