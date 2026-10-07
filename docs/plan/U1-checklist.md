# U1 — 10 dakikalık kullanıcı kabul turu

Bu tur **uygulama paketleri birleşince** çalıştırılır. Bugün ürün kabulü yapılmış değildir.
Yalnız sentetik “Örnek Şirket” kullanın; ekran görüntülerinde gerçek şirket veya anahtar bulunmasın.

## Başlamadan (lider hazırlar, süreye dahil değil)

Web `http://localhost:3000`, API, worker, PostgreSQL, Redis ve MinIO çalışır; API live modundadır.
Model profili/anahtarı sunucuda bir kez hazırlanır; şirket modeli hâlâ kapalıdır.
WP95'in `tests/fixtures/u1-company/odalar.txt` ve `hizmetler.txt` dosyaları hazırdır.
Bunlar bu plan WP'sinde oluşturulmadı; WP95 teslimatıdır. Kaynaklarda Bahçe Odası büyüklüğü
32/36 m² olarak çelişir; kapasite 2, Danışma saatleri 08:00–20:00; 2035 fiyatı yoktur.
Küçük tur için sağlıklı model bağlantısı gerekir; büyük gerçek belge işleme süresi 10 dakika değildir.
Süre aşılırsa neden kaydedilir, tur geçti sayılmaz.

## Tur (ara komut/SQL/CLI yok)

| Süre | Kullanıcının işlemi | Geçmesi için |
| --- | --- | --- |
| 0:00–1:00 | Şirket seçicisinde “Yeni şirket” → Örnek Şirket; ayrıca boş bir Deneme Şirketi oluşturun, geri dönün. | İki şirket yükleme öncesi seçilebilir. Sayfayı yenileyince Örnek Şirket kalır. |
| 1:00–2:00 | Belgeler'de iki TXT dosyasını tek seçimle yükleyin. | Her dosyanın ayrı ilerlemesi var; ikisi Hazır olur. Hazır'ın belgeye ait olduğu açık. |
| 2:00–2:30 | Aynı dosyaları tekrar seçin; “Bilgileri çıkar”ı model ayarlamadan deneyin. | Belge sayısı hâlâ 2; model seçmek için Ayarlar yönlendirmesi var. İş başlamaz. |
| 2:30–3:00 | Ayarlar'da bağlantı/model ve hazır anahtar profili seçin; gönderim açıklamasını okuyup modeli açın. | Anahtarın kendisi görünmez. Kaydetmek bilgi çıkarmaz. Diğer boş şirketin modeli kapalı kalır. |
| 3:00–5:00 | Örnek Şirket → Belgeler → Bilgileri çıkar. Düğmeyi tekrar deneyin; sayfayı yenileyin. | Tek iş; gerçek aşamalar ilerler. Yenileme işi kaybetmez. Bitişte Sorular'a yönlendirme var. |
| 5:00–6:00 | Koleksiyonlar'da oda/hizmet kayıtlarını açın, Kaynakta göster'i kullanın; Onaylı görünümü kontrol edin. | Bahçe Odası, Danışma ve beş alan bulunur; 32/36 çelişkisi görünür. Henüz onaylanmamış değerler Onaylı'da yok. |
| 6:00–7:30 | Sorular'da oda büyüklüğü için `odalar.txt` içindeki 32'yi seçin; diğer dört alanı kaynaktan kontrol edip onaylayın. | Tek aday kartları onay ister; iki farklı kaynak çelişki olarak sunulur. Her cevap kaydedilir; soru sayısı azalır. |
| 7:30–8:00 | Koleksiyonlar → Onaylı; sayfayı yenilemeden okuyun. | Oda 32 m² / 2 kişi, Danışma 08:00–20:00; reddedilmiş 36 yok; 5/5 alan doğru, kaynaksız bilgi 0. |
| 8:00–9:00 | Dene: “Bahçe Odası kaç metrekare ve kaç kişilik?” | 32 m² ve 2 kişi; belge adı/gerçek konum/alıntı bu iki iddiayı destekliyor. |
| 9:00–9:30 | Dene: “2035 gecelik fiyatı nedir?” | “Bilmiyorum.”; uydurulmuş fiyat veya kaynak yok. |
| 9:30–10:00 | Boş şirkete geçin; sonra 390 px genişlikte ve koyu temada aynı menüleri açın. | Önceki şirketin belge/cevap/ayarları görünmez; boş durum ne yapacağınızı söyler; yatay sayfa taşması yok. |

## Liderin ayrı kontrolleri

- [ ] WP95 live smoke bütün adımlarda geçti; rapor yerel konumu ve süreleri kaydedildi.
- [ ] Sentetik hata dosyasında başarılı yüklemeler korunuyor; kısmi/başarısız belge bilgi işini engelliyor.
- [ ] Model kapalıyken dış model çağrısı 0; bağlantı/model kesilince sade hata var, “Bilmiyorum” ile karışmıyor.
- [ ] Başarısız/ölmüş bilgi işi eski yayını koruyor; sonsuza kadar “çalışıyor” göstermiyor.
- [ ] Önceki yayın açıkça seçildiğinde hâlâ okunuyor; eski revision ile cevap `409` ve yenileme uyarısı veriyor.
- [ ] Kaynak içi talimat görünümlü metin sistem davranışını değiştirmiyor.
- [ ] Yeni soru son onaylı yayını kullanıyor; tek sorunun kaynakları aynı revision'dan geliyor.

## Gerçek şirket kabulü (lider; süre sınırı yok)

Lider bir gerçek şirketi **aynı web yoluyla**, ara komut olmadan yeni çalışma alanında doğrular.
Kaynaklardan önceden seçtiği en az 5 kritik alan, varsa 1 gerçek çelişki ve 1 bilinmeyen soru
anahtarını kullanır. Seçilmiş alanlar %100 doğru, kaynaksız iddia 0, çelişki kararı yayında ve
Dene'de aynı olmalı. Formatlar, kapsama eksikleri ve işleme süreleri kaydedilir.
Gerçek kaynak/anahtar/ekranlar Git dışında kalır; kamu raporuna müşteri adı girmez.

## Sonuç kaydı

- Çalıştıran / tarih / yığın sürümü:
- Sentetik web turu: geçer / başarısız / engelli — başarısız adım ve nedeni:
- Live smoke: geçer / başarısız / engelli — yerel rapor konumu:
- Gerçek şirket: doğrulandı / doğrulanmadı — Git dışı kanıt konumu:
- Liderin U1 kararı: açık / tamamlandı:

Bir kutu, `done`, ekranın açılması veya test sayısı tek başına U1 kabulü değildir.
