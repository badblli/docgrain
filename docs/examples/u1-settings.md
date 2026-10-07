# Çalışma alanı ve model ayarı (U1)

Yeni çalışma alanı `POST /v1/workspaces` ile `{ "name": "Örnek Şirket" }` gönderilerek
oluşturulur. Sunucu `201 {id,name,documents:0}` döndürür. Liste boş çalışma alanlarını ve
belgelerden oluşmuş eski alanları birlikte gösterir; eski `id/documents` alanları korunur.
Ad ve model ayarları PostgreSQL'de saklanır; `repository.initialize()` ek tabloları idempotent
kurar. Demo salt okunurdur.

## Lider için sunucu hazırlığı

API ve model kullanacak worker ortamında `DOCGRAIN_MODEL_CREDENTIAL_PROFILES` tanımlanır.
Varsayılanı `{}`. Örnek metadata (anahtar değeri içermez):

```json
{
  "company-cloud": {"label": "Şirket bağlantısı", "api_key_env": "COMPANY_MODEL_KEY"},
  "local": {"label": "Yerel bağlantı", "api_key_env": null}
}
```

`COMPANY_MODEL_KEY` değerini sunucunun Git dışında tutulan güvenli ortamına hazırlayın;
anahtarı belgeye, komut çıktısına veya günlüğe yazmayın. Profil metadata'sına sır koymayın.
İstemci profil kimliğini seçebilir; ortam değişkeni adı veya ham anahtar gönderemez.
`api_key_env: null` yalnız açıkça tanımlanan anahtarsız bağlantıyı belirtir.
Genel model/provider ortamına otomatik fallback yoktur.

**WP91 Compose aktarımı:** `DOCGRAIN_MODEL_CREDENTIAL_PROFILES` hem API hem worker'a;
metadata'da kullanılan `COMPANY_MODEL_KEY` gibi anahtar env adları da aynı hizmetlere
aktarılmalıdır. Bu WP Compose/worker dosyalarını değiştirmez. Sunucu ortamını veya profil
eşlemesini değiştirmek API ve worker hizmetlerini yeniden başlatmayı gerektirir. Resolver
her kullanımda aynı profil env'sini okur; anahtar yenilenince veritabanı ayarı değişmez.

Anahtarsız yerel örnek, önce `local` profili sunucuda tanımlandıktan sonra:

```json
{
  "enabled": true,
  "base_url": "http://local-model:8000/v1",
  "model": "local-model",
  "credential_id": "local"
}
```

Adres çalıştıran API/worker tarafından ulaşılabilir olmalıdır. Bu ayarı kaydetmek bağlantı
testi veya model isteği yapmaz. Etkinleştirme yalnız sonraki açık bilgi çıkarma/sorma eylemine
izin verir; normalize içerik seçilen bağlantıya o eylemde gönderilir.

## API ve paketlere aktarım

- `GET/PUT /v1/workspaces/{ws}/model`: `enabled`, `base_url`, `model`, `credential_id`,
  `credential_ready`, `settings_version`. Yeni alan kapalı, metinler boş, sürüm `0`;
  her başarılı PUT sürümü atomik olarak artırır. PUT yalnız ilk dört alanı kabul eder.
- `GET /v1/workspaces/{ws}/model/profiles`: `[{id,label,ready}]`; env adı ve sır dönmez.
  Boş/seçilmeyen veya bilinmeyen profille açma `422`. URL kullanıcı/parola, query,
  fragment veya açık anahtar yolları kabul etmez. Ham anahtar/sunucu alanları `422`;
  hata yanıtları reddedilen girdiyi tekrar etmez.
- **WP91/WP94:** `docgrain_api.workspace_settings.resolve_workspace_model(ws,
  expected_version=None)` → `ResolvedWorkspaceModel` nesnesi, alanları `enabled`,
  `base_url`, `model`, `api_key`, `settings_version`. `api_key` yalnız bellekteki istemciye
  geçirilir, repr'de gösterilmez; Pydantic JSON/dump çıktılarında da dışlanır.
  Nesneyi serialize etmeyin, kuyruğa/DB'ye yazmayın;
  kuyruğa yalnız çalışma alanı kimliği ve `settings_version` gönderin. Kapalı/eksik sır
  veya farklı sürümde `ModelSettingsError` (`status_code=409`, sade `detail`) oluşur.
  Bilinmeyen çalışma alanı `404`, hatalı sunucu profil yapılandırması `503` olur.
- **WP93:** named export `WorkspaceSettings`:
  `apps/web/app/components/settings/workspace-settings.tsx`. Props: `apiUrl`,
  `workspaceId`, `mode: "live" | "demo"`, isteğe bağlı
  `onSaved(settings: WorkspaceModelSettings)`. Tipler aynı klasörde `types.ts`.
  Menü/sayfa bağlantısını WP93 yapar. Yeni liste `name` alanını şirket seçicide kullanın.
  Bileşen yükleme, boş seçim, hata/yeniden dene, eksik bağlantı, kaydedildi ve demo
  durumlarını kapsar; alan değişiminde form yeniden kurulur ve eski istekler iptal edilir.

## Doğrulama

Worker test ortamında `DOCGRAIN_M1_TEST_DATABASE_URL` ile
`python -m pytest -q tests/integration/test_u1_settings_live.py` çalıştırılır. Test izole
PostgreSQL şemasında tablo kurulumunu tekrarlar, bağlantıları ve API lifespan'ını yeniden
açar; boş çalışma alanı/ayar kalıcılığını, belge katalog birleşimini ve sürüm artışını denetler.
Model isteği yapmaz. Lider ayrıca 390 px açık/koyu tema ve klavye turunu yapar;
TypeScript kontrolü bu görsel kabulün yerine geçmez.
