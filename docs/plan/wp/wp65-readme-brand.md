# wp65-readme-brand — the GitHub README wears the brand

- Özet: Marka kiti web'e uygulandıktan sonra GitHub README'sini de aynı kimliğe getir: logo (açık/koyu tema), kısa ürün cümlesi, ekran görüntüsü, renk ve yazı dili.
- Model: lead (Claude) with Smeargle's assets
- Engine: claude
- Phase: D7
- Depends on: wp63 (brand applied to the web)
- Role: lead

## Tasks

1. Header: `<picture>` with light and dark logo variants (`apps/web/public/brand/`), so the logo reads
   on GitHub's light and dark themes; one-line product statement under it.
2. A screenshot of the console made from **synthetic data only** (the brand board's invented company, or a
   fixture workspace) — never a real customer workspace; light and dark if practical.
3. Keep the README's existing technical sections; restyle headings/badges to the brand's calm tone
   (sentence case, no emoji clutter).
4. Public repo rule: `git grep` the scrub term list before pushing; no partner names in README or images.

## Acceptance criteria

- [ ] README renders the logo correctly in GitHub light and dark themes.
- [ ] Screenshot contains no real company data.
- [ ] Scrub check clean.
