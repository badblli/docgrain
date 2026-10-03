# Belge inceleme ve revision çalışma ekranı

## Yerel kullanım

`http://localhost:3000` → Dokümanlar → belgeyi aç → **Belgeyi incele**.

- **Metin:** kaynakla yan yana okunur; metin bloğundaki Düzenle düğmesi taslak açar. Listeler ve bölüm sırası korunur.
- **Tablolar:** hücreyi seçince kaynak konumu görünür. Formül, birleşik hücrenin altında kalan alan ve desteklenmeyen değerler salt okunur.
- **Görseller:** özgün dosya önizlenir. Boş açıklama, görsel anlamının henüz kabul edilmediğini gösterir. Kaynakta gördüğünüz bilgiyi yazın; model tahminini doğrulamadan kesin bilgi diye kaydetmeyin.
- **Yerel model önerisi:** seçili görsel için CPU modeli öneri üretir. Ayrı düğmeyle taslağa alabilirsiniz; mevcut açıklamayı değiştirmeden önce sorar. Üretmek veya taslağa almak kayıt yapmaz. Model ayrıntıları uydurabilir; kaynakla karşılaştırın. Yazı çıkarımı ayrı OCR aşamasındadır.
- **Belirsizlik notları:** okunamayan ölçüleri/ayrıntıları görsel kartında düzenleyin. Öneri mevcut notları kaldırmaz. Not değişiklikleri de önizlenir; JSON, Markdown ve sohbet eksikleri korur.
- **Eksikler:** kayıtlı çıkarım sorunları ve açıklanmamış görseller. Liste boş olsa da belgenin bütünü doğrulanmış sayılmaz.
- **Revision geçmişi:** önceki revision'ları salt okunur açar; yüklenen kaynak dosyanın sürümlerinden ayrıdır.
- **Belgeye sor:** seçili revision'a bağımsız Gemini sorusu. Her soruda açık gönderim onayı, isteğe bağlı en fazla üç görsel. Kaynak ve revision değişmez.

Taslak değişiklikler için **Gözden geçir ve kaydet** → inceleyen kişi/neden → **Farkları önizle** → kaynakla karşılaştırma kutusu → **Yeni revision kaydet**. Önizleme kayıt yapmaz. Eski revision, kaynak ve önceki paketler korunur; yeni revision'ın AI JSON/Markdown/parçaları birlikte yayımlanır. Genel belge onayı otomatik verilmez.

Çakışmada taslak korunur. Güncel revision'ı yüklemeden önce JSON taslağını indirin. Kaydetme isteği ağda kesilirse sunucuda tamamlanmış olabilir; geçmişi kontrol edin. Aynı işlem tekrar edilirse ikinci revision üretilmez. Formüllü bir hücreyi değiştirmek için kaynak dosya düzenleme/yeniden yükleme yolu gerekir; burada formül hesaplanmaz.

## Chat sınırı

Bu küçük deney embedding veya otomatik görsel arama kabulü değildir. Metin/tablo yanıtı ile kaynak uyuşması, seçili görselin doğru baytlarının dönmesi ve eksik soruda yanıt vermeme ayrı kontrol edilir. Açıklaması bulunmayan görseller, kullanıcı seçmeden anlamsal olarak bulunmuş sayılmaz. Modelin atıf kimlikleri doğrulanır; iddiaların doğruluğu kaynakla ayrıca karşılaştırılır.

API chat varsayılan kapalıdır (`GEMINI_CHAT_ENABLED=false`); yerel inceleme override'ı açıktır. Bu ayar worker'ın yerel normalizasyon kararını değiştirmez. Gemini anahtarı yalnız API sunucusunda kalır. Docgrain her soruyu bağımsız gönderir; sohbet geçmişini sunucuda tutmaz.

## Kabul durumu

N4'ün sınırlı insan inceleme/revision dilimi uygulandı. Otomatik görsel anlam modeli, büyük/kör corpus kabulü, tüm bağlı domain kayıtları için düzenleme ve production kimlik/yetki/günlük kontrolleri açık. N3/N5 bütünü ve embedding kapısı kapanmadı.

Kaynağa bağlı bölüm başlıkları da düzenlenebilir. Bağlı entity/relation/record olan revision'da yalnız kanıtı açıkça bağımsız alanlar düzenlenir; kesişen veya belirsiz bağımlılıklar salt okunur. Bağlı bilgi kayıtları otomatik yeniden doğrulanmaz.

Kararlar: [ADR 0021](adr/0021-end-user-source-review.md), [ADR 0022](adr/0022-canonical-gemini-qa-probe.md).


## 2026-10-03 yerel doğrulama

- İzole PostgreSQL/MinIO/Docling/EasyOCR runtime: **426 passed, 0 skipped**; son kayıt-zamanı düzeltmesinden sonra **104 unit + 13 gerçek review integration** yeniden geçti (bir yeni saat/sıralama regression). Rapor `data/reviews/review-tests.xml` (ignore edilen yerel kanıt).
- Gerçek modern/legacy review kaydı, art arda revision, birebir replay, değişmiş operation ID payload çatışması, eşzamanlı CAS, depolama hash/eksik sürüm ve çıktı yayını sonrası transaction rollback testleri geçti. Onay işaretçisi ve eski snapshot/paket değişmiyor.
- TypeScript, production web build, API/web Docker image build ve değişen Python dosyaları için Ruff geçti; Compose config doğrulandı. Repo genel Ruff seçili kurallarında mevcut eski import/dict uyarıları ayrıca görüldü; bu teslim değişen dosyaları temiz doğrular.
- Gerçek Corendon UI: 7 sayfa kaynağı, 4 tablo/13 görsel; hücre taslağı, server önce/sonra farkı, kaynak bbox, zorunlu kaynak onayı, değişiklik sonrası önizleme iptali ve geciktirilmiş çift tıklamada tek POST. 390 px ekranda yatay sayfa taşması yok. Taslak geri alındı; kullanıcı verisine kayıt yapılmadı.
- **Üç gerçek Gemini çağrısı**, `gemini-3.7-flash`, Corendon `revision_d04ca9c2d318b99892a0653ab217dfc8`: standart oda **24–27 m²** ve telefon **+ (90) 242 824 98 00**, sayfa 3/2 kanıtlarıyla döndü. Kullanıcının seçtiği sahil fotoğrafı aynı canonical asset/547×265 bayt önizlemesiyle döndü. 2035 gecelik fiyatı bulunmadığından `abstained=true`, atıf/görsel yok. Fotoğraf yorumunun inceleme statüsü değişmedi.
- Bu, küçük bir smoke turudur; otomatik doğru görsel bulma/semantik corpus kabulü değildir. Açıklamasız görseller seçim olmadan anlamsal bulunmuş sayılmaz. Kanıt `data/reviews/chat-smoke-results.json`; browser console 0 error.
- Beş live head ve **30 stored + 30 regenerated** dosyanın SHA-256 değerleri pre-N1 baseline ile aynı. Worker remote vision kapalı, kuyruğu 0; yeni ingestion veya embedding yok. Üç model çağrısı yalnız chat tüketici deneyine aittir.

### Sonraki kaynak düzeltme turu — 2026-10-03

- Full runtime **472 passed, 0 skipped**; son float/supplemental-evidence guard ardından **129 ilgili unit test** yeniden geçti (bir yeni regression). Ruff, TypeScript ve production/API/web builds başarılı. CPU öneri, taslak farkı/özgün değere dönüş, read-only history ve 390 px görünüm kontrol edildi; console 0 error/0 warning.
- **Corendon:** 13 görsel açıklaması kaynak PDF/özgün PNG karşılaştırmasıyla yeni revision'a eklendi. Oda fotoğrafı/planı kaynak bölüm başlığı kanıtına bağlandı. Dört plan ve küçük bir fotoğrafın altı belirsizlik notu hâlâ açık.
- **Dobedan:** 10 logo açıklaması ve sayfa 2 üst tablosunun üç hücre düzeltmesi yeni revision'da yayımlandı; altı bağımsız kaynak golden 6/6 geçti. Kara Manzaralı başlığındaki yanlış önek kaldırıldı; Engelli Odası toplamı 7 doğru sütuna taşındı.
- Bu turda inceleyen **Codex source review** olarak kaydedildi. İki PDF'in güncel head'i ilerledi; üç diğer head, beş özgün kaynak ve eski revision/paketler korundu. Genel onay işaretçisi değişmedi. Beş güncel JSON/ZIP paketine erişim doğrulandı.
- Gemini'ye görsel seçmeden sorulan Family fotoğrafı, standart oda planı ve havuz fotoğrafı üç doğru asset döndürdü. Kaynakta olmayan kesin yatak eni sorusu boş atıf/görselle abstain döndü. Bu dört çağrı normalize bilgi tüketicisi denemesidir; belgeler bulutta normalize edilmedi.
- CPU modeli hâlâ deneysel: bazı plan/text yorumları hatalıydı, uygulanmadı. Kaynak kontrolüyle eklenen açıklamalar otomatik model kabulü değildir. N3 semantic gate, kapsamlı N4 ve N5 açık; embedding en son.

Güncel kullanım: **Dokümanlar → Corendon → Belgeyi incele → Görseller / Belgeye sor**. [ADR 0023](adr/0023-local-cpu-visual-proposals.md) model, endpoint ve sınır kararlarını içerir.
