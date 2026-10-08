# WP102 — etiketli kanıt ölçümü

## Doğrulama kuralı

Alıntı, doğru belge ve kaynak bloğunda bulunur. Değerin metinsel karşılığı da
alıntıda ve kaynakta tam sözcük/sayı sınırlarıyla bulunur. Sayılar ondalık
virgül ve eşdeğer sıfırlarla karşılaştırılır; `2`, `132`, `2.5` veya `-2`
içinden destek kazanamaz. Metinlerde büyük/küçük harf ve bütün liste üyeleri
korunur. `value_not_in_quote` önerilen değer alıntıyla desteklenmediğinde döner.

Lider kararı uyarınca şu değerler **alana bağlıdır**: sayılar (birimli veya
birimsiz), saatler/saat aralıkları, tarihler, para tutarları, boolean ve kısa
enum/kategori değerleri. Bunlarda alıntı hem değeri hem aynı özgün kaynak
satırındaki değerin dışından en az bir tam Unicode sözcüğü veya para/birim
simgesi (`€`, `%`, `°` gibi) içermelidir. Enum
alanları `Literal` tipinden; genel string şemalarda `category`, `kind`, `type`,
`status`, `state`, `currency`, `unit`, `availability` alan adlarından tanınır.
Başka genel string alanların kategori anlamı şemada bildirilmediğinden
serbest metin sayılır. TR/EN/DE/RU için etiket çevirisi veya model çağrısı
yapılmaz.

Kimlik/ad ve betimleyici metin, değeri tam olarak kaynakta geçtiğinde kendini
tanımlar: `Bahçe Odası`, `Danışma`, `Garden room`, `Meerblick` başlıkları tek
başına geçerli kanıttır. Kimlik alanının değeri sayı/saat/tarih ise alana bağlı
değer kuralı yine uygulanır. Boolean alıntı `true`/`false` yazmadan alanın
kaynak ifadesini taşıyabilir: `available` alanında `available` veya aynı
satırdaki `Rezervasyon gerekli` gibi iki sözcüklü bir ifade kabul edilir.
Tek sözcüklü alan adı yalnız `true` için yeterlidir; `false` için nitelendirici
ifade ya da açık `false` gerekir. Bu dil bağımsız sözcüksel kural, ifadenin
olumlu/olumsuz anlamını tercüme edip tahmin etmez.

Çıplak alana bağlı değer alıntıları modelsiz genişletilir. `etiket: değer`
parçası, birimiyle birlikte satır/noktalı virgül/tablo hücresi sınırına kadar
atomik tutulur; diğer durumlarda özgün alıntıyla bir tam bağlam sözcüğünü
kapsayan en kısa aralık seçilir. Eşitlikte kaynak sırası belirler. Özgün
belgeyle tarama bölümü ayrı ayrı doğrulanır. Birim sonraki satıra taşınmışsa,
eski alıntı korunup **değerle aynı satırdaki** etiket başına eklenebilir;
`32\nm²` için kaynakta etiket yoksa onarım yapılamaz. Başka satır, blok veya
tekrarlanan tablo başlığı bağlam sağlayamaz. Genişletme olmazsa `bare_value_quote` döner;
mevcut destekli alıntıların özgün yazımı korunur.

Yalnız değer içeren Markdown tablo hücresi için locator'da doğrulanmış başlık
istisnası vardır:

```text
§1 cell={"row":1,"column":2,"column_header":"Capacity"}
```

Satır ve sütun 1 tabanlıdır; satır veri satırlarını sayar. `row_header`, aynı
satırın ilk hücresini gösterebilir. En az bir başlık gerekir; belirtilen
başlıkların tamamı kaynakta verilen koordinatlarla eşleşir. Kaynakta
bulunmayan başlık istisna sağlamaz.

## Değişiklik öncesi corpus ile karşılaştırma

Başlangıç commit'i `f24497ec8a4ce2a429dbe7d218e4fc0018607768` idi.
Fixture'lar değiştirilmeden önce tam pytest paketindeki 434 başarılı
`verify_response` çağrısının girdisi ve eski çıktısı yerel
`.pytest_cache/wp102/corpus.json` dosyasında yakalandı. Aynı girdiler yeni
doğrulayıcıya yeniden verildi. Sayılar tekrarlanan sentetik test çağrılarının
alan örnekleridir; bağımsız gerçek şirket doğruluk oranı değildir.
Primary/i18n ve conflict adayları `(record_id, alan, dil, değer)` bazında
sayılmıştır.

| Ölçüt | Önce | Sonra |
| --- | ---: | ---: |
| Çıktıdaki kabul edilmiş alan örneği | 1405 | 1402 |
| Kanıt alıntısı genişleyen alan örneği | — | 477 |
| Alıntısı değişmeyen alan örneği | — | 925 |
| Çıktıdan düşen alan örneği | — | 3 |
| Yeni kabul edilen alan örneği | — | 0 |

Önceki katı denemede reddedilen **485 tek başına kimlik kanıtı**, onlara bağlı
**464 `amount` alanı** ve `available` sözcüğüyle desteklenen **26 boolean**
geri geldi. Önceki raporda kimlik reddine bağlanan dört `size_m2` alanı ise
gerçekte satır bölünmesi yüzünden kaybolmuştu: `32` önceki satırdaki oda
etiketiyle, `m²` sonraki satırdaydı. Etiket, değerin aynı satırında kaldığından
alıntı birimi koruyarak genişletildi. Böylece önceki denemede kaybolan
**468 sayısal alanın tamamı** geri geldi; neden ayrımı da düzeltildi.

Kalan üç kaybın gerekçeleri:

| Alan | Sayı | Gerekçe |
| --- | ---: | --- |
| `name` | 2 | Önerilen `Consultation` adı için alıntı `40 EUR`; ad alıntıda yok (`value_not_in_quote`). |
| `conditions` | 1 | Önerilen metin alıntıda yok (`value_not_in_quote`). |

Testte NFKC/boşluk davranışını sınayan sentetik satır özgün iki satırlı
haliyle tutuldu; onarımın alıntısı doğrulandı. Değerin bulunduğu satırda
etiket yoksa ret yeni testle ayrıca doğrulandı. Eski `conditions`
önerisindeki kaynakta bulunmayan değer düzeltildi. Diğer
kimlik/boolean fixture değişiklikleri geri alındı. Tablo ve dil örneklerinde
eski sözleşmeden kalan geçerli alanlar yeni kuralla korunuyor.

## U1 önce / sonra

| Alan | Önce | Sonra |
| --- | --- | --- |
| Oda adı | `Bahçe Odası` | `Bahçe Odası` |
| Oda büyüklüğü | `32` | `Büyüklük: 32 m2` |
| Kapasite | `2` | `Kapasite: 2 kişi` |
| Hizmet adı | `Danışma` | `Danışma` |
| Çalışma saati | `08:00–20:00` | `Çalışma saatleri: 08:00–20:00` |

Hash'li U1 belgeleri değiştirilmedi. Doğrulayıcı testi, bu özgün metinlerden
oda ve hizmet kaydının kimlikleriyle birlikte çıktığını ve üç alıntının tam
olarak yukarıdaki biçimde saklandığını denetler. `u1_smoke.py --fake` dokuz
adımda geçer; bu fake API önceden hazırlanmış yayını kullanır, doğrulayıcıyı
çalıştırmaz. U1 kaynak metninin doğrulayıcı testi bu sınırı ayrıca kapatır.

## Çalıştırma

Pinli Python yorumlayıcısı
`C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python` kullanılır.
Windows'un varsayılan pytest geçici dizinine erişim engellendiğinden
`--basetemp=.pytest_cache/wp102/...` verilmiştir. Canlı
Docling/EasyOCR/PostgreSQL/MinIO entegrasyonları worker Docker ortamı
gerektirdiğinden burada çalıştırılmadı. Son tam pytest, Ruff ve fake smoke
komutları WP son raporundadır.
