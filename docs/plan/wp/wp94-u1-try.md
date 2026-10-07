# wp94-u1-try — Onaylı AI araçlarından kaynaklı Dene

- Özet: Kullanıcı Dene'de soru sorsun; seçilen model onaylı bilgi araçlarını kullansın, kaynağıyla cevap versin veya Bilmiyorum desin.
- Model: derin
- Engine: codex
- Skill: frontend-design
- Phase: U1
- Branch: `codex/wp94-u1-try` (base: `origin/dev`)
- Depends on: wp92-u1-settings runtime sözleşmesi; mevcut wp68 AI araçları
- Role: implementer
- Owner: Ada (codex)

## Goal

Web'deki küçük deneme yüzeyi wp68'in dört aracını şirketin seçtiği OpenAI uyumlu modelle kullansın.
Yeni retrieval/chat altyapısı kurmadan U1 A15–A17'yi doğrula.

## Scope

- In: açık `/ai/ask`, sınırlı araç döngüsü, yapılandırılmış kaynak sonucu ve bağımsız Dene bileşeni.
- Out: preview seçeneği, sohbet geçmişi, source normalization, vendor revision chat, embeddings,
  ayarlar/secret kasası, main/page/sidebar ve Dockerfile.

## File ownership

- `apps/api/docgrain_api/routers/ai.py`
- `apps/api/docgrain_api/routers/try_ai.py`
- `apps/api/docgrain_api/try_ai.py`
- `packages/access/docgrain_access/ask.py`
- `apps/web/app/components/try/try-view.tsx`
- `apps/web/app/components/try/types.ts`
- `tests/unit/test_u1_try.py`
- `tests/unit/test_u1_try_client.py`
- `docs/examples/u1-try.md`

WP93 ekran/menüyü, WP91 access paketinin Docker imajlarına alınmasını yapar; ortak dosyaları değiştirme.

## Tasks

1. [U1 ask sözleşmesini](../U1.md) uygula. `ai.router` üzerinden yeni relative `/ask` router'ını
   bağla; mevcut GET tools / POST call salt okunur ve modelsiz kalır. POST ask yalnız açık soru eylemi.
   `resolve_workspace_model` ile şirket ayarını al; istemci endpoint/model/key/mode/revision veremez.
   Demo/kapalı/eksik model/yayın yok guard'ı, boş onaylı içerikte dış çağrısız abstain.
2. `packages/access/docgrain_access/ask.py` mevcut SYSTEM, OpenAICompatibleClient ve ask döngüsünü
   yeniden kullan. Yapılandırılmış sonuç için geriye uyumlu ek fonksiyon/result ekle; var olan
   `ask()` string çıktısı ve CLI/MCP davranışı bozulmasın. AccessClient veya AIAccess adaptörü
   `specs/call` ile wp68 dört aracı kullansın; tek soru başında newest revision bir kez sabitlensin.
   Sekiz tur/sonlu timeout-retry; ikinci soru yeni başı alır. Read için farklı retrieval yolu ekleme.
3. Approved server enforced; modelin preview/başka workspace isteği reddedilir. Source text, schema
   descriptions, document names ve quotes yalnız untrusted data. Yapılandırılmış sources sadece
   döngüde gerçekten okunan ve final answer'da anılan ID'lerdir. Atıfsız/uydurma ID/tur sınırı
   “Bilmiyorum.” döndürür; var olan ID'nin doğru iddiayı desteklemesi bağımsız goldende denetlenir.
4. Model/araç transport hatasında sır/model yanıtı yansıtmayan `503/504` ve sade kullanıcı mesajı;
   bağlantı arızası “Bilmiyorum” diye başarılı gizlenmez. API key repr/log/body'ye girmesin.
5. `TryView({apiUrl,workspaceId,mode})` named export; soru alanı + Sor düğmesi, loading, boş yayın,
   kapalı model, cevap/kaynak ve ayrı bağlantı hatası. Cevapta belge adı/konum/alıntı açılır;
   kaynakta olmayan soruda yalnız “Bilmiyorum.” görünür. Şirket değişimi ekranı ve gecikmiş yanıtı
   temizler. frontend-design, mevcut Tailwind/shadcn ve marka; yeni .css yok. WP93 navigasyonu bağlar.
6. Kullanım/sınırları `docs/examples/u1-try.md` içinde sentetik örnekle anlat. Kaynak ID doğrulaması
   semantik doğruluk kanıtı değildir. Yeni ask'ın model çağırdığı, tools/call'ın çağırmadığı açık olsun.
   WP91'e access package import/image gereksinimini bildir; kurulum/build yapma.

## Tests

```powershell
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' -m pytest -q tests/unit/test_u1_try.py tests/unit/test_u1_try_client.py tests/unit/test_ai_access.py tests/unit/test_ai_clients.py -p no:cacheprovider
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' -m ruff check apps/api packages/access tests/unit/test_u1_try.py tests/unit/test_u1_try_client.py
node apps/web/node_modules/typescript/bin/tsc --noEmit -p apps/web
```

Fake model/transport: opt-in/empty zero calls, gerçek araç çağrısı ve doğru kaynak, uydurma/atıfsız
cevap, preview kaçışı, source injection, pinned revision değişimi, timeout/retry/key redaction ve
geri uyumlu ask string. Lider build ve sentetik/gerçek soru anahtarıyla kaynak anlamını ölçer.

## Acceptance criteria

- [ ] Kapalı model ve boş onaylı veri dış çağrı 0; GET tools/POST call mevcut davranışta kalır.
- [ ] Fake model approved araçlarla okur; cevap kaynakları tek workspace/revision'a bağlıdır.
- [ ] Fixture oda cevabı 32 m² / 2 kişi; reddedilmiş 36 ve önizleme olguları döngüye giremez.
- [ ] Atıfsız/uydurma ID/yanıtsız/tur sınırında “Bilmiyorum.”; servis kesintisi `503/504` ayrı hata.
- [ ] Kaynak talimatı sistem yetkisi olmaz; model/API key hiçbir payload/log/hata/publication'da yok.
- [ ] İki ardışık soru arasında yayın değişince ikincisi güncel revision'ı kullanır; tek soru karışmaz.
- [ ] tsc ve offline testler geçer; liderin gerçek model/source anlam kabulü ayrıca kaydedilir.

## Notes

Oku: AGENTS.md, ROADMAP, [U1](../U1.md), wp68, `docs/examples/ai-access.md`,
`docs/brand/BRAND.md`. Merge WP92 → **WP94** → WP91 → WP93 → WP95.
