# wp92-u1-settings — Şirket oluşturma ve varsayılan kapalı model ayarı

- Özet: Kullanıcı boş şirket oluşturabilsin ve her şirket için model bağlantısını ayrı seçsin; anahtarlar sunucuda kalsın, model kendiliğinden çalışmasın.
- Model: derin
- Engine: codex
- Skill: frontend-design
- Phase: U1
- Branch: `codex/wp92-u1-settings` (base: `origin/dev`)
- Depends on: none
- Role: implementer
- Owner: Cem (codex)

## Goal

Şirket seçimi yükleme öncesinde mümkün olsun; model tercihi kalıcı ve şirket bazında olsun.
Yeni şirket kapalı başlar; açık kullanıcı eylemi dışında dış çağrı yapılmaz. U1 A1/A5/A6.

## Scope

- In: şirket kataloğu, model/profil API'si, iç resolver ve bağımsız Ayarlar bileşeni.
- Out: anahtar kasası/şifreleme ürünü, tarayıcıda ham anahtar girişi, auth, model listesi tarama,
  bağlantı testi, ortak menü/page bağlantısı, worker, Compose/Dockerfile.

## File ownership

- `apps/api/docgrain_api/settings.py`
- `apps/api/docgrain_api/repository.py`
- `apps/api/docgrain_api/routers/documents.py`
- `apps/api/docgrain_api/routers/workspace_settings.py`
- `apps/api/docgrain_api/workspace_settings.py`
- `apps/api/docgrain_api/workspace_settings_repository.py`
- `apps/web/app/components/settings/workspace-settings.tsx`
- `apps/web/app/components/settings/types.ts`
- `tests/unit/test_u1_settings.py`
- `tests/integration/test_u1_settings.py`
- `docs/examples/u1-settings.md`

WP93 page/sidebar/console-types sahibidir; bileşeni ona ver. WP91 main/Compose/Dockerfile sahibidir.

## Tasks

1. [U1'deki şirket/model uçlarını](../U1.md) uygula. Yeni şirket için sunucuda güvenli id üret,
   adı kalıcı sakla; boş şirket `GET /v1/workspaces` listesine gelsin. Belge kaynaklı eski şirketleri
   aynı listeyle birleştir; eski `id/documents` tüketicileri bozulmasın. `documents.workspaces_router`
   üzerinden yeni router'ı bağla; `main.py` değişmez. Katalog/ayar additive tablolarını kendi modülünde
   veya sahip olduğun repository initialize yolunda idempotent kur; demo salt okunur kalsın.
2. `enabled=false`, boş endpoint/model/profil yeni varsayılan. GET/PUT model ayarı ve settings_version;
   PUT'ta sunucu alanlarını/ham anahtarı reddet. URL'de userinfo/sır/query parametresi kabul etme.
   JSON ve düz hata anahtar içermez. Eksik/geçersiz ayarla açma isteği `422`; modelsiz işlem `409`.
3. Sunucu tarafından tanımlı `DOCGRAIN_MODEL_CREDENTIAL_PROFILES` JSON eşlemesi:
   profil kimliği → `{label,api_key_env}`; boş varsayılan. Sır ilgili env'de; profil meta JSON'unda değil.
   İstemci env adı seçemez. Anahtarsız yerel model için `{label,api_key_env:null}` profili açıkça
   tanımlanabilir; genel model env'sine/provider'a otomatik fallback yok. UI sadece id/etiket/hazır görür.
4. `resolve_workspace_model(ws, expected_version=None)` iç Python sözleşmesini WP91/WP94'e sağla:
   enabled/base_url/model/api_key/settings_version. Yanlış sürüm/kapalı/eksik sırda fail closed.
   Sır yalnız bellekte istemciye geçsin, queue/DB/response/exception repr'ye girmesin. Key rotation
   aynı profil env'sinden çözülür; persist edilen ayar yalnız credential_id tutar.
5. `WorkspaceSettings({apiUrl,workspaceId,mode,onSaved})` named export. Bağlantı/model adı,
   hazır profil seçimi, kapalı/açık kontrolü, Kaydet. Normalize içerik seçilen bağlantıya gönderilir
   açıklaması; etkinleştirme açık eylem. Ham anahtar input'u veya localStorage kaydı yok.
   Loading/empty/error/saved/missing credential durumları sade Türkçe; şirket değişince stale
   istek sonucu/form değerleri taşınmaz. Tailwind + mevcut shadcn/token'lar; yeni .css yok.
6. `docs/examples/u1-settings.md` lider için bir kez profil/env hazırlama, yerel anahtarsız örnek,
   sunucu ortam değişikliğinin servis yeniden başlatmasını gerektirdiğini anlatır. Secret değerleri
   örneğe/günlüğe yazma. Compose'a gerekli env adlarını WP91'e bildir; kurulum/build yapma.

## Tests

```powershell
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' -m pytest -q tests/unit/test_u1_settings.py tests/unit/test_workspaces_api.py tests/unit/test_bundle_ingest.py -p no:cacheprovider
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' -m ruff check apps/api tests/unit/test_u1_settings.py tests/integration/test_u1_settings.py
node apps/web/node_modules/typescript/bin/tsc --noEmit -p apps/web
```

Fake repo/transport ile boş şirket, default off, allowlisted profil, key redaction ve iki şirket
izolasyonu; model HTTP transport'una sıfır istek. Lider worker test ortamında
`python -m pytest -q tests/integration/test_u1_settings.py`: Postgres yeniden bağlantısı/servis
yeniden açılınca şirket/ayar korunur. Lider Ayarlar'ı 390 px açık/koyu tema ve klavyeyle kontrol eder;
ajan yapılmayan build/browser testini geçti saymaz.

## Acceptance criteria

- [ ] Yeni boş şirket `201`, listede 0 belge, yeniden açılınca aynı ad/id; eski belgeli şirketler korunur.
- [ ] Yeni model kapalı; GET/PUT/listeleme ve kaydetme hiçbir model isteği yapmaz.
- [ ] A şirketini açmak B'yi açmaz; genel key env'si opt-in yerine geçmez; settings_version artar.
- [ ] Bilinmeyen profil/env adı veya ham api_key kabul edilmez; yerel anahtarsız profil açıkça çalışır.
- [ ] Anahtar GET/DB/queue/log/hata/bileşen/localStorage'da yok; sentinel sır testi bunu denetler.
- [ ] Bileşen named export/sözleşmesi, Türkçe durumlar, stale şirket yanıtı guard'ı ve tsc temiz.

## Notes

AGENTS.md, ROADMAP, [U1](../U1.md), wp50/wp56/wp68 ve `docs/brand/BRAND.md` okunur.
frontend-design mevcut marka içinde uygulanır; yeniden tasarım yok.
İlk birleşen pakettir; WP91/WP94 resolver sözleşmesine göre paralel sahte istemciyle ilerler.
