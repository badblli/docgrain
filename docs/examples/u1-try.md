# Onaylı bilgileri Dene

Dene bir sohbet geçmişi tutmaz. Şirket seçin, Ayarlar'da modeli açıkça etkinleştirin,
belgelerden çıkan bilgileri onaylayın ve bir soru için **Sor** düğmesine basın.
Sayfa açılması, ayar kaydetme, `GET /ai/tools` ve `POST /ai/call` model çağırmaz.
Yalnız yeni `POST /v1/workspaces/{workspace_id}/ai/ask` soru eylemi şirketin
seçtiği OpenAI uyumlu modele çağrı yapabilir. Yeni model varsayılan kapalıdır.

Sentetik örnek: `odalar.txt`, Bahçe Odası'nın büyüklüğünü 32 m², kapasitesini 2 kişi
olarak verir. Başka bir belgede önerilen 36 m² reddedilmiştir. Onaydan sonra:

```http
POST /v1/workspaces/workspace-example/ai/ask
Content-Type: application/json

{"question":"Bahçe Odası kaç metrekare ve kaç kişilik?"}
```

Cevap 32 m² / 2 kişi bilgisini gerçekten okunan kaynak ID'leriyle verir.
`sources` yalnız cevapta anılan araç kaynaklarını içerir; her kaynak `id`,
`document_name`, `locator`, `quote`, `document_id`, `source_version_id`,
`knowledge_revision_id` taşır. Dene belge adı, konum ve alıntıyı açar.
Kaynakta olmayan “2035 gecelik fiyatı nedir?” sorusunun sonucu:

```json
{
  "answer": "Bilmiyorum.",
  "abstained": true,
  "workspace_id": "workspace-example",
  "revision_id": "r1",
  "mode": "approved",
  "sources": []
}
```

## Sınırlar

Sunucu her soru başında en güncel yayını bir kez sabitler; sonraki soruda başı tekrar
çözer. Beş araç (`list_collections`, `search_records`, `get_record`,
`get_context`, WP112 ile `list_collection`) aynı şirket/yayının **onaylı** görünümünü okur. İstemci yalnız `question`
gönderir; endpoint/model/key/mode/revision ve sorgu parametresi kabul edilmez.
Modelin önizleme/başka şirket/yayın argümanları okuma yapmadan reddedilir.
Yeni retrieval veya embedding yolu yoktur.

Kapalı/eksik model, demo ve henüz yayın olmaması `409`; geçersiz soru `422` olur.
Boş onaylı içerikte model istemcisi bile kurulmaz; sonuç dış çağrısız “Bilmiyorum.” olur.
Uydurma/okunmamış kaynak ID'si, atıfsız cevap, boş yanıt veya sekiz tur sınırı da
“Bilmiyorum.” üretir. Yapılandırılmış döngü her cümle/satırda atıf bulunmasını
mekanik olarak denetler; noktalama biçimleri nedeniyle temkinli çekimserlik olabilir.
Yalnız tanınan olgusuz geçiş cümleleri için bir kez, araçsız yeniden yazma istenir;
olgusal cümleler ve kaynakları aynen korunmalıdır. Bu çağrı da sekiz tur sınırına
dahildir. Atıfsız olgular veya değişen/okunmamış kaynaklar yine reddedilir.
Liste soruları (WP112): model koleksiyonu tek `list_collection` çağrısıyla okur ve
her öğeyi ayrı satırda yazar. Bu durumda denetim satır bazlıdır: her öğe satırı bu
soruda araçların döndürdüğü bir kaydın adıyla başlar (büyük/küçük harf ve aksan
duyarsız) ve yalnız o kaydın okunmuş kaynaklarına atıf yapar; satır başına bir atıf
yeterlidir. Girintili ayrıntı satırları aynı kaydın kaynaklarını gösterir. Listeyi
tanıtan, `:` ile biten, rakamsız, olumsuzluk içermeyen ve yalnız sorudaki kelimelerle
küçük bir liste ifadesi kümesini kullanan kısa başlık satırı atıfsız olabilir. Okunmamış
kayıt/kaynak, atıfsız öğe veya olgu içeren başlık yine “Bilmiyorum.” üretir; bu
cevaplar onarıma gönderilmez.
Tekrarlı ölçüm ve liderin canlı komutu: [Dene çekimserlik ölçümü](dene-abstain.md).
Bir tur en fazla sekiz araç çağrısı kabul eder. Model transport'u istek başına 60 saniyelik
HTTP timeout (`DENE_MODEL_TIMEOUT_SECONDS`), sorunun tamamı için 120 saniye
(`DENE_QUESTION_TIMEOUT_SECONDS`; tüm model istekleri, yeniden denemeler, araç okumaları
ve onarım dahil) ve en fazla üç denemeyle sınırlıdır (WP112; önceden 20 saniye); yalnız timeout/429/seçili 5xx
yeniden denenir, beklemeler 1 ve 2 saniyedir. Bağlantı veya bozuk araç/model sonucu
`503`, zaman aşımı `504` döndürür; servis kesintisi bilinmeyen bilgi diye gizlenmez.
İstemciye sağlayıcı yanıtı, endpoint veya sır içeren hata yansıtılmaz.

Kaynak metni, belge adı, alıntı ve şema açıklaması güvenilmeyen veridir; sistem
talimatı değildir. Kaynak kaynaklı açıklamalar araç şemasının talimat açıklamalarına
taşınmaz. Kaynak ID doğrulaması **semantik doğruluk kanıtı değildir**: geçerli bir
ID'ye yanlış iddia bağlamak hâlâ mümkündür. Gerçek modelle her iddianın değeri,
birimi ve alıntı/konumu bağımsız anahtarla lider tarafından ölçülmelidir.
Sahte transport testleri bu gerçek model kabulünün yerine geçmez.

## Entegrasyon notu (WP91 / WP92 / WP93)

WP92'nin `docgrain_api.workspace_settings.resolve_workspace_model(workspace_id)`
sunucu sözleşmesi kullanılır: `enabled/base_url/model/api_key/settings_version`.
Alanlar eşleme veya nesne nitelikleri olarak okunur. Resolver kapalı/eksik profili
fail closed reddetmelidir; açık anahtarsız yerel profil `api_key=""` dönebilir.
Resolver henüz bu worktree'ye birleşmedi: eksik modül dış çağrısız `503` verir;
birleşme sonrası gerçek resolver/hata sınıfıyla entegrasyon kontrolü gereklidir.

**WP91 için gerekli:** API imajına `packages/access` kopyalanıp
`docgrain_access` import edilebilir olmalı (paketi mevcut kurulum yönteminizle
kurun veya Python yoluna ekleyin). API yeni soru servisinde `ask_result` ve
`OpenAICompatibleClient` import eder; araçları okumak yeni ağ servisi gerektirmez.
Bu WP Dockerfile/Compose değiştirmez, kurulum veya build çalıştırmaz.

**WP93 için:** `TryView({apiUrl,workspaceId,mode})` named export'u
`app/components/try/try-view.tsx` içindedir; `mode` `"live" | "demo" | null`.
Menü/page bağını WP93 yapar. Bileşen model durumunu ve mevcut onaylı listeleme
aracını salt okunur kontrol eder; şirket/bağlantı/mod değişince soru/cevap ve
bekleyen istekler temizlenir. Cevap yalnız Sor ile istenir; otomatik soru tekrarı yoktur.

Lider ayrıca 390 px açık/koyu tema, klavye, şirket değişiminde geciken yanıt ve gerçek
model/source anlam kabulünü web turunda kaydetmelidir.
