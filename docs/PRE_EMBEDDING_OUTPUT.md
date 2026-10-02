# Embedding öncesi ortak doküman çıktısı

2026-10-01 · local integration / kullanıcı fidelity incelemesi.

## Ne doğrulandı?

PDF, DOCX, TXT ve XLSX aynı `docgrain.ai-document` **1.0.0** JSON sözleşmesine
dönüştürülür. Kaynak türüne göre consumer şeması değişmez. Typed içerik, gerçek
parent/child okuma sırası, tam tablo hücreleri, formül/cache/span bilgisi, entity/
relation/record verileri, source/producer ve evidence korunur. Canonical JSON
immutable kaynak doğrusudur; `ai.json` bundan türetilmiş bir consumer görünümüdür.

**Her türlü belgenin bütün anlamını kesin çıkardığımız doğrulanmadı.** İlk scope
dört formattır; PPTX/HTML/bağımsız image ingestion desteklenmez. Docling PDF OCR
kapalıdır; taranmış sayfa, görsel anlamı, grafik yorumu ve eksik formül cache'i
ayrı kalite/enrichment gerektirir. Binary resmin çıkarılması, içeriğinin metne
aktarılması değildir. Embedding bu boşluğu gidermez.

Kalite iki ayrı sınırı gösterir:

- `canonical_to_output: verified`: canonical → çıktı veri korunumu test edilmiştir.
- `source_to_parser: not_independently_verified`: orijinal dosyanın bütün anlamının
  parser tarafından çıkarıldığı bağımsız olarak kanıtlanmamıştır.
- `semantic_status`: `not_assessed` veya `needs_enrichment`; semantik başarı vaadi yoktur.
- `text_only_complete`: kayıtlı structural/visual gap bulunmadığı anlamındadır;
  doğruluk veya bütün anlamın çıkarıldığına dair kabul değildir.

## Otomatik yayın ve dosyalar

Yeni upload sonrası worker doğrulanmış canonical revision'dan şu dosyaları üretir:

| Dosya | İçerik |
| --- | --- |
| `ai.json` | Format bağımsız AI consumer sözleşmesi, içerik ve açık kalite boşlukları |
| `ai.schema.json` | Aynı consumer sözleşmesinin JSON Schema'sı |
| `canonical.json` | Authoritative snapshot'ın tam model JSON'u |
| `canonical.md` | Metin + tam hücre JSON'u + kanıt/kalite bilgisi içeren okunabilir görünüm |
| `chunks.jsonl` | Canonical structure-aware chunks; görsel omission açıkça kaydedilir |
| `manifest.json` | Kaynak/revision, kapsam, omissions, binary refs ve diğer dosyaların checksum'ları |

Her dosya pinned MinIO version'ıyla SHA-256/size doğrulanır. PostgreSQL immutable
publication pointer yalnız bütün dosyalar doğrulandıktan sonra yazılır. Hata
durumunda yarım paket görünür olmaz; replay mevcut byte sürümlerini yeniden
kullanır. Orphan nesneler kalabilir; Redis ingestion crash recovery henüz yoktur.
Dosya yolu `knowledge/<document>/<canonical_revision>/<projection_revision>/<file>`.
ZIP bu altı dosyayı ve SHA ile adlandırılmış binary `assets/` eklerini içerir.
Chunk bütçesi Unicode karakteri üzerinden 1600, table row sınırı 20'dir;
oversize ve omissions manifestte görünür. Embedding veya otomatik index üretilmez.

## Kullanıcı incelemesi ve API

[Web](http://localhost:3000) → **Dokümanlar → bir doküman → AI çıktısı** varsayılan
sekmedir. İçerik, Eksikler ve Ortak JSON görünümleri; exact tablolar, binary resim
önizlemeleri, evidence bağlantıları, tek dosya ve ZIP indirmeleri bulunur.
Pipeline eski job'un çalıştığı tarihteki aşamaları gösterir. Backfill eski stage
kayıtlarını değiştirmez; güncel paketi AI çıktısı sekmesinden kontrol edin.

Salt okunur endpoint'ler:

```text
GET /v1/documents/{document_id}/knowledge
GET /v1/knowledge/revisions/{revision_id}/outputs
GET /v1/knowledge/revisions/{revision_id}/outputs/{filename}
GET /v1/knowledge/revisions/{revision_id}/package
```

Okuma yalnız stored/version-addressed byte'ları servis eder; GET parse/derivation
çalıştırmaz. Eksik çıktı `404`, checksum uyuşmazlığı `503`; demo sahte AI çıktısı
üretmez. API'nin mevcut document/workspace scope sınırları tenant authorization
yerine geçmez.

## Gerçek beş dokümanın kabul kanıtı

Kaynak SHA/version ve canonical hash/head korunarak mevcut snapshot'lardan
yayın yapıldı. Yeniden ingestion ve ücretli model çağrısı yapılmadı.

| Kaynak / belge | TextBlock karakteri | Tablo / hücre | Görsel | Chunks | Kayıtlı açık boşluk |
| --- | ---: | ---: | ---: | ---: | --- |
| F&B XLSX `doc_09ab90f4` | 0 | 2 / 88 | 0 | 9 | 0 |
| Misafir ilişkileri DOCX `doc_0f906728` | 4423 | 0 / 0 | 0 | 3 | 0 |
| Dobedan PDF `doc_22977bfd` | 5519 | 28 / 1683 | 10 | 178 | 10 görsel açıklaması eksik |
| Corendon PDF `doc_237edd14` | 4178 | 4 / 94 | 13 | 28 | 13 görsel açıklaması eksik |
| TXT `doc_2a54df6f` | 4705 | 0 / 0 | 0 | 4 | 0 |

23 görsel node, 17 unique binary dosya vardır; tekrar kullanılan asset'lar
birden fazla node'a bağlı olabilir. TextBlock sayacı section heading'lerini
içermez; XLSX'in 0 metin karakteri göstermesi 88 hücrenin kaybolması değildir.
`data/reviews/ai-output-review/` ignored yerel çıktı/report dizinidir; gerçek
belgeler Git'e eklenmez. Kullanıcı kaynakla karşılaştırmalı inceleme henüz açık.

## Doğrulama ve tekrar yayın

Gerçek worker + PostgreSQL + versioned MinIO + Docling suite: **208 geçti**.
PDF table/image-only, DOCX text/list/image, multilingual TXT, XLSX
formula/cache/merged/image/chart; corrupt/unsupported gates, semantic negatives,
immutable publication, pinned reads, failure/replay ve ZIP byte fidelity kapsanır.
Ruff, TypeScript, production web/API/worker Docker build ve Compose config geçti.

Mevcut verified head'lere explicit backfill (worker ortamı ve bağımlılıklarıyla):

```sh
python docs/examples/publish_existing_outputs.py --workspace ws_local --bucket docgrain --report data/reviews/ai-output-review/report.json
```

Bu komut **derived publication/lineage ve storage yazar**; source/canonical/head
değiştirmez. Yeniden çalıştırma idempotent'tir. Gereken env için worker Compose
ayarlarını kullanın; report/generated source verisini Git'e eklemeyin.

Yerel inceleme profili `data/reviews/ai-output-local.compose.yml` yeni üç image'i
seçer ve worker Gemini key'ini boş bırakır. `.env` credential'ları korunur.
Sıradaki kalite kapısı kaynak↔çıktı golden karşılaştırması ve ihtiyaç olan
görseller/sayfalar için selective OCR/Vision + evidence reconciliation'dır.
Sonrasında embedding kararı verilebilir.

## Kaynak doğrulaması / seçili Gemini turu — 2026-10-02

Kullanıcının mevcut Gemini anahtarını seçilmiş alanlarda kullanma onayıyla dört
Corendon oda planı ve Dobedan sayfa 2 üst tablo için beş gerçek çağrı yapıldı.
Önceki kabul turunun model çağrısı içermediği bilgisi o tur için geçerlidir.
Kaynak karşılaştırması ve ayrıntılı sonuçlar:
[Source fidelity review](SOURCE_FIDELITY_REVIEW.md).

Yeni sonuçlar halen **öneri / inceleme çıktısıdır**; ana UI ve yayımlanmış paketler
eski immutable revision'ı gösterir. Kaynakta doğrulanan üç hücre düzeltmesi ayrı
önizlemede hazırdır. Modelin kaynakta olmayan harf eklemesi reddedildi. Oda planı
açıklamalarındaki belirsizlikler korunur. Bir sonraki adım kanıtlı alan değişikliklerini
yeni review/processing revision'a uygulayıp yeni paketi yayımlamaktır.
