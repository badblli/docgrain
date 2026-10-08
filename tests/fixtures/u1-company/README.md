# U1 Sentetik Şirket Kayıtları (WP95)

Bu dizin, U1 smoke testi ve kabul süreçleri için sentetik belgeler ve bağımsız anahtarı (golden) içerir.

## Dosyalar
- `odalar.txt`: Oda detaylarını içerir. İçerisinde AI eylemini test etmek için yanıltıcı bir talimat barındırır.
- `hizmetler.txt`: Hizmetler ve çelişen oda boyut bilgisini içerir.
- `golden.json`: Bu kaynaklardan çıkarılması beklenen 5 kritik alanı, kaynak pozisyonlarını, alıntıları ve kabul/red senaryolarını barındıran bağımsız doğruluk dosyasıdır. Hash'ler de bu dosyada yer alır.

## Kapsam
Bu belgeler sadece iki dosya ile temel smoke akışının çalışıp çalışmadığını test etmek ve model yargıcını/veri çıkarma kalitesini sentetik ortamda bağımsız anahtara karşı doğrulamak için kullanılır. 
Yüksek oranlı dosya çeşidi ve OCR doğrulaması için kullanılmaz; bu test ürün işleyiş pipeline'ı içindir.
