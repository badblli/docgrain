# Kaynak karşılaştırması ve seçili görsel yorumlama

2026-10-02 · `codex/source-fidelity-acceptance` · yerel inceleme.

## Sonuç

Beş gerçek dosya SHA-256/byte size ile canonical kaynak sürümüne bağlanarak bağımsız
okundu. Ortak JSON sözleşmesinin korunması, kaynak anlamının doğru çıkarıldığını
kanıtlamıyor: Dobedan oda tablosunda bir toplam yanlış sütuna atanmıştı.

| Kaynak | Bağımsız karşılaştırma | Sınır |
| --- | --- | --- |
| TXT | 4.705 karakter; NFKC/boşluk normalizasyonuyla metin eşleşiyor | Anlam kabulü değil |
| DOCX | 41 gövde paragrafının 41'i eşleşiyor | Header/footer, stiller ve görsel anlamı incelenmedi |
| XLSX | 76 dolu kaynak hücresinin değer/formül/cache/span/koordinatı eşleşiyor | Canonical 88 koordinatın 12'si boş; görsel/stil anlamı incelenmedi |
| Dobedan PDF | Sayfa yerel native token tanılama + 6 bağımsız tablo hücresi assertion'ı | 3 assertion mevcut tabloda hatayı gösteriyor |
| Corendon PDF | Native token tanılama, binary görsel ve oda planı incelemesi | Kapak kerning'i token farkı yaratıyor; semantik tamlık kanıtlanmadı |

## 23 görsel ne içeriyor?

- Dobedan: 10 logo node'u, tekrar kullanılan 4 binary. Bunlar on ayrı oda planı değil.
- Corendon: 9 fotoğraf ve 4 oda planı; 13 ayrı binary.
- Dört oda planında okunabilir metin/ölçü bulunmadı. OCR tek başına oda yerleşimini
  metne aktaramaz. Vision yerleşim açıklaması üretir; düşük çözünürlük ve belirsiz
  mobilya türleri açık kalmalıdır. Fotoğrafların yorumu bu seçili çağrı turuna dahil değil.

## Gerçek Gemini turu

Kullanıcı mevcut Gemini anahtarının seçilmiş alanlarda kullanımını açıkça onayladı.
Yapılandırılmış `gemini-3.7-flash` ile dört plan ve bir tablo için **5 başarılı
çağrı** yapıldı; provider usage toplamı **11.561 token** (prompt/output/thoughts).
Para maliyeti hesaplanmadı. Anahtar raporlara veya Git'e yazılmadı.

Her öneri source/revision/node/evidence/input hash, model, prompt/response hash,
usage, literal OCR, görsel açıklaması, tablo satırları ve belirsizlikleri taşır.
Durumu `proposed` kalır. Dört planın büyük yerleşimleri görselle karşılaştırıldı;
mobilya, ıslak hacim elemanı ve erişilebilirlik hakkında kesinlik üretilmedi.

### Dobedan sayfa 2 — 19 × 12 üst tablo

Sıfır tabanlı hücre koordinatları:

| Hücre | Canonical | Model önerisi | Kaynak incelemesi |
| --- | --- | --- | --- |
| (0,0) | ODA TİPİ & ODA BİLGİLER | ODA TİPİ & ODA BİLGİLERİ | Modelin eklediği İ kaynakta yok; reddedildi |
| (0,2) | m 2 | m² | Görsel kaynak m²; ayrı normalizasyon değerlendirmesi, bu önizlemede değiştirilmedi |
| (0,6) | Manzaralı Kara Manzaralı | Kara Manzaralı | Kaynakla doğrulandı; önizlemede düzeltildi |
| (18,6) | 7 | boş | Kaynakla doğrulandı; önizlemede boşaltıldı |
| (18,7) | boş | 7 | Kaynakta **Engelli Odası** sütunu; önizlemede doğru sütuna taşındı |

Genel toplam 724 ve “Yandan Deniz” başlığı kaynakta mevcut halleriyle doğrulandı.
Üç hücre düzeltmesi dışındaki 225 hücre önizlemede korunur. Altı golden assertion
mevcut snapshot'ta 3 hata bulur; yalnız kaynakla doğrulanan hücrelerin değiştiği
önizlemede 6/6 eşleşir. Modelin bütün tablosu topluca kabul edilmedi.

## Nerede incelenir?

Gerçek kaynak ve öneriler Git'e eklenmeyen `data/reviews/fidelity-review/` altında:

- `audit-summary.json`, belge başına `audit.json`.
- `doc_22977bfd/golden.json`, `table-review.json` (karar + önce/sonra hücreler).
- `dobedan-header-detail.png`, `dobedan-total-detail.png`.
- `proposals/corendon-plan-{6,8,9,12}.json`, `proposals/dobedan-room-table-page-2.json`.

**Ana Web UI halen yayımlanmış eski snapshot'ı gösterir.** Bu tur yeni ingestion,
canonical/head değişikliği, çıktı yayını veya embedding yapmadı. Bir sonraki işlem:
kaynakla doğrulanan alanları kanıt/producer/review durumu ile yeni immutable
revision'a uygulama, CAS ile head ilerletme, yeni AI JSON/ZIP yayını ve kaynak ↔
UI tekrar kontrolü. Öneri açıklamaları kalite boşluklarını kendiliğinden kapatmamalı.

## Tekrar çalıştırma

Worker bağımlılıklarının bulunduğu ortamda, `docgrain_domain` ve `docgrain_worker`
paketleri import edilebilir olmalıdır. Salt okunur kaynak kontrolü:

```sh
python docs/examples/audit_source_fidelity.py --snapshot canonical.json --source original.pdf --golden golden.json --output audit.json
```

Seçili tek alan için açık model çağrısı (API kullanımı oluşturur; anahtar yalnız
`GEMINI_API_KEY` environment variable'ından okunur):

```sh
python docs/examples/extract_selected_visual.py --snapshot canonical.json --source original.pdf --node TABLE_NODE_ID --task table --page 2 --context "Only the first upper table" --model MODEL_ID --output proposal.json
```

Oda planı için `--task room_plan --image verified-asset.png`; page kullanılmaz.
Aynı request/model için mevcut öneri dosyası tekrar kullanılır; yeni çağrı yapılmaz.
Farklı request/model aynı dosyaya yazılmaz. Tablo PNG'si kaynak PDF'den üretilir;
başka görüntü, kaynak SHA/revision/evidence veya artifact uyuşmazlığı reddedilir.

## Testler

12 yeni sözleşme testi: kaynak/binding uyuşmazlığı, bütün kelimeler korunurken sütun
kayması, yinelenen DOCX paragrafı, XLSX koordinat/formül korunumu, yanlış PNG/page/
artifact, düzensiz/aşırı büyük model tablosu, bozuk JSON/boş sonuç, immutable öneri
dosyası, stale revision, shape değişikliği ve yalnız kaynakla doğrulanan hücreleri
kullanan önizleme. Provider testleri mock kullanır, API çağrısı yapmaz.

Güncel host suite: **161 geçti, 59 opt-in integration atlandı**; Ruff geçti.
Önceki container kabul turunun 208/208 sonucu tarihsel kanıttır; bu turda yeniden
çalıştırılmadı. Yeni DB/publication/frontend davranışı eklenmedi.
