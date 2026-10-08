# wp100-oss-small-fixes — Küçük açık kaynak katkıları

- Özet: Alan adı ve yükleme kuyruğu testlerini genişlet; çoklu dosya seçimini anlat ve kurulum komutlarını düzelt.
- Phase: D7
- Branch: `test/oss-small-fixes` (base: `dev`, 95e97d7)
- Depends on: none
- Role: implementer
- Owner: Ece (Codex · test / kalite)
- Assignment: Kullanıcının bu konuşmadaki dört küçük katkı talebi.

## Goal

Yeni bağımlılık veya özellik eklemeden küçük, doğrulanabilir katkılar hazırlamak.

## Scope

- In: Etiket sınır durumları, yükleme hatasından sonra kuyruk ilerlemesi, çoklu seçim açıklaması ve README kurulum komutları.
- Out: Backend/parser değişiklikleri, yeni bağımlılıklar, model çağrıları, merge/deploy.

## File ownership

- `tests/web/test_u1_upload.mjs`
- `apps/web/app/components/documents.tsx`
- `README.md`
- `README.tr.md`
- `docs/plan/wp/wp100-oss-small-fixes.md`

## Tasks

1. Mevcut test düzeneğinde boş ve bilinmeyen alan/collection etiketlerinin okunabilir fallback davranışını doğrula.
2. İlk dosya yüklenemediğinde tek çalışanlı kuyruğun sıradaki dosyayı tamamladığını ve sadece hata dosyasının yeniden denendiğini doğrula.
3. Belgeler ekranında birden fazla dosyanın birlikte seçilebildiğini sade Türkçeyle açıkla.
4. İngilizce/Türkçe README demo ve test kurulumunu yerel paket bağımlılıkları ve CI komutlarıyla uyumlu yap.

## Acceptance criteria

- [x] Etiket sınır durumları yeni Node testiyle doğrulanır.
- [x] İlk dosya hatası kuyruğu durdurmaz; yeniden deneme başarılı dosyayı tekrar yüklemez.
- [x] Varsayılan yükleme ekranı çoklu seçimi Türkçe açıklar.
- [x] İki README gerekli yerel paketleri kurar ve Node testinin nasıl çalıştırıldığını gösterir.
- [x] Node testleri, TypeScript kontrolü ve web build sonucu raporlanır; eksik ortam kontrolleri açıkça belirtilir.

## Notes

Oku: [Roadmap](../ROADMAP.md), [U1](../U1.md), [WP93](wp93-u1-web-flow.md), [AGENTS](../../../AGENTS.md).
Mevcut Node/TypeScript test düzeneği yeniden kullanılır. Örnekler sentetiktir.
Python/entegrasyon kontrolü gerekiyorsa yalnız takımın repo venv'i/worker Docker imajı kullanılır.

## Validation

- Baseline: `node --test tests/web/test_u1_upload.mjs apps/web/app/components/workspace-review.test.cjs` → 43 passed, 0 failed.
- Final: aynı komut → 45 passed, 0 failed. Yeni testler ilk yükleme hatasından sonra kalan iki dosyanın tamamlanmasını, yalnız başarısız transferin yeniden denenmesini ve boş/bilinmeyen etiket fallback'lerini doğrular.
- `node apps/web/node_modules/typescript/bin/tsc --noEmit -p apps/web` → exit 0.
- `npm run build` (`apps/web` içinde) → exit 0; sayfalar üretildi. Next.js üst klasördeki ikinci lockfile için ortam uyarısı verdi.
- `git diff --check` → exit 0.
- README kurulum zinciri `apps/api/pyproject.toml`, `packages/records/pyproject.toml`, `packages/evaluation/pyproject.toml` ve `.github/workflows/quality.yml` ile kontrol edildi.
- Python demo kurulumu/pytest/Ruff çalıştırılmadı: AGENTS.md'deki sabit repo venv yolu ve bu checkout'ın `.venv` dizini mevcut değil. Docling/EasyOCR/PostgreSQL/MinIO Docker entegrasyonu ve tarayıcı turu yapılmadı.
- `npm ci` lockfile'ı değiştirmedi; mevcut bağımlılıklarda 1 moderate ve 9 high güvenlik bildirimi verdi. Bağımlılık yükseltmeleri bu WP kapsamı dışında.
