# Dene çekimserlik ölçümü

`benchmarks/dene_abstain.py`, bir çalışma alanının sabitlenmiş **onaylı** yayınında
bilinen (tekil), liste ve bilinmeyen soruları N kez sorar. Her soru yeni model istemcisi ve boş
geçmiş kullanır. Varsayılan çalıştırma ağ/model istemcisi oluşturmaz; gerçek model
yalnız `--enable-model` ve açık bağlantı argümanlarıyla kullanılır. Anahtar komut
satırında verilmez; `--api-key-env` sunucudaki ortam değişkeninin adıdır. Bu seçenek
verilmezse açıkça seçilmiş anahtarsız yerel bağlantı kullanılır.

Bağımsız soru anahtarını model cevaplarını görmeden kaynaklardan hazırlayın.
Gerçek sorular/alıntılar ve çıktı dosyası Git dışında tutulmalıdır. Sentetik biçim:

```json
[
  {
    "id": "room",
    "kind": "known",
    "question": "Bahçe Odası kaç metrekare ve kaç kişilik?",
    "claims": [
      {"pattern": "32\\s*m²", "quote": "32", "document_name": "odalar.txt", "locator": "§1 p.1"},
      {"pattern": "2\\s*kişi", "quote": "2", "document_name": "odalar.txt", "locator": "§1 p.1"}
    ],
    "forbidden_patterns": ["\\b36\\b"]
  },
  {
    "id": "rooms",
    "kind": "list",
    "question": "Hangi odalar var, kaç kişilik?",
    "items": [["Garden room", "Bahçe odası"], ["Sea room", "Deniz Odası"], "Family suite"]
  },
  {"id": "price", "kind": "unknown", "question": "2035 gecelik fiyatı nedir?"}
]
```

Liste sorusu (WP112, `kind: "list"`): `items`, onaylı koleksiyonda olan **bütün**
beklenen öğelerdir; her öğe bir ad ya da kabul edilen adların listesidir (ör. İngilizce
ve Türkçe ad). Cevabın her üst düzey liste satırı (`- …`, `1. …`) bir öğe adıyla
başlamalı ve dönen bir kaynağa atıf yapmalıdır. İsteğe bağlı `claims` ve
`forbidden_patterns` bilinen sorudaki gibi çalışır (ör. “ısıtmalı” havuzun kaynağı).

`pattern`, kaynaktaki bağımsız beklenen değerin ve birimin düzenli ifadesidir.
Her iddia için aynı cümledeki atıf, tam `quote`, `document_name`, `locator`
değerlerine ulaşmalıdır. Reddedilmiş alternatifleri `forbidden_patterns` ile
işaretleyin. Bu kontrol seçilmiş iddiaları ölçer; cevaptaki ek iddiaların anlamı
lider tarafından ayrıca incelenir. Geçerli kaynak ID'si tek başına doğruluk değildir.

Liderin canlı komutu (yer tutucuları kendi bağlantısıyla değiştirmeli):

```powershell
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' benchmarks/dene_abstain.py --enable-model --api-url 'http://localhost:8000' --workspace '<workspace-id>' --revision '<approved-revision-id>' --base-url '<openai-compatible-base-url>' --model '<model-name>' --api-key-env 'AI_API_KEY' --questions '<private-questions.json>' --repetitions 20
```

WP112 sonrası `--model-timeout` (varsayılan 60 sn, tek model isteği) ve
`--question-timeout` (varsayılan 120 sn, sorunun tamamı) Dene'nin
`DENE_MODEL_TIMEOUT_SECONDS` / `DENE_QUESTION_TIMEOUT_SECONDS` ayarlarıyla aynıdır.
`list_collection` aracı API tarafındadır; ölçümden önce API bu kodla çalışıyor olmalıdır
(`GET /v1/workspaces/<id>/ai/tools` beş araç döndürür).

`--revision` verilmezse başlangıçtaki en güncel yayın bir kez sabitlenir; tüm tekrarlar
aynı yayını okur. Betik mevcut salt okunur AI araçları üzerinden `ask_result`
döngüsünü ölçer; şirket model ayarlarını değiştirmez ve HTTP `/ai/ask` korumalarının
yerine geçmez. Modeli bu komutla ayrıca etkinleştiren lider bağlantıyı seçer.

JSON raporu şunları sayar:

- `correct_with_sources`: bağımsız beklenen iddialar ve cümlelerindeki kaynaklar doğru.
- `abstained_on_known` ve `abstained_on_known_rate`: cevaplanabilen soruda “Bilmiyorum”.
- `answered_on_unknown`: bilinmeyen soruya verilen cevap; hedef **0**.
- `invented_sources`: kullanıcıya dönen cevapta okunmamış/değiştirilmiş kaynak; hedef **0**.
- `incorrect_on_known`: atıflı olsa da bağımsız anahtarı karşılamayan cevap.
- `errors`: bağlantı/model/yayın hatası; başarılı çekimserlik sayılmaz.
- `invented_items` (WP112): liste cevabında anahtarda olmayan öğe satırı; hedef **0**.
- `missing_items` (WP112): liste cevabında atıflı satırı olmayan anahtar öğesi.
- `timeouts` (WP112): soru süresi/model zaman aşımı; ayrıca `errors` içinde sayılır.
- `latency_seconds` (`mean`, `p50`, `max`) ve her sonuçta `seconds`: soru başına süre.

Liste soruları `known_runs` ve `abstained_on_known` içinde bilinen soru sayılır; liste
cevabı, eksik veya uydurma öğe yoksa ve `claims` sağlanıyorsa `correct_with_sources` olur.

Reddedilip kullanıcıya dönmeyen uydurma atıf girişimi `invented_sources` sayısını
artırmaz. Bilinen soruda çekimserlik/yanlış cevap, bilinmeyende cevap, uydurma kaynak
veya hata varsa çıkış kodu **1** olur. Rapor yalnız soru kimliği, sonuç sınıfı,
tekrar ve yayın kimliğini içerir; cevap, kaynak metni, bağlantı veya sır içermez.

Sahte model ölçümü ve güvenlik senaryoları `tests/unit/test_dene_abstain.py` içinde
çevrimdışı çalışır. Sentetik 5 bilinen + 5 bilinmeyen tekrar, bağlantı çağrısı
yapmadan ölçüm kodunu sınar; gerçek model çekimserlik oranına kanıt sayılmaz.
Aynı cevap dizisinin bir geçiş cümlesi içeren beşinci bilinen cevabında, onarım
kapalıyken oran %20, açıkken %0 olarak sınanır; iki koşulda da bilinmeyende cevap
ve dönen uydurma kaynak sayısı 0'dır.

## Güvenli yeniden yazma sınırı

Kaynaklı cevabın tek sorunu atıfsız ve tam olarak tanınan bir geçiş cümlesiyse
(ör. “İşte yanıt.”), modelden bir kez bu cümleyi kaldırması istenir. Araç listesi
boştur, yeni araç çağrısı reddedilir. Olgusal cümlelerin metni, sırası ve her birinin
kaynak ID kümesi değişemez. Yeniden yazma dahil en fazla sekiz model tamamlaması
yapılır. Hata yine `503/504` olarak dışarı çıkar.

Genel bir cümlenin olgu taşımadığını sayı kontrolüyle veya model kararıyla güvenilir
biçimde belirleyemeyiz. Bu nedenle küçük, tam eşleşen geçiş cümlesi listesi kullanılır;
tanınmayan atıfsız cümleler ve atıfsız olgular, değerleri okunmuş olsa bile “Bilmiyorum.”
ile sonuçlanır. Mevcut atıflı olguların anlamsal doğruluğu bağımsız anahtarın sorumluluğudur.
