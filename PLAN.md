# Могилянський медіамоніторинг: план

## Мета
Щоденний дайджест: топові новини про НаУКМА + досягнення та публічні дописи
випускників, співробітників і студентів. Публікація: статична сторінка (GitHub Pages),
запуск: GitHub Actions за розкладом.

## Обмеження, з'ясовані на розвідці (2026-11-04)
- `alumni.ukma.edu.ua/alumni.html` віддає 403 будь-кому; Wayback тимчасово офлайн →
  архів підключимо пізніше окремим імпортером (`people/import_archive.py`).
- Bluesky search API вимагає авторизації → app password у secrets (опційно).
- Facebook/LinkedIn/X/Threads не мають відкритого API для чужих дописів →
  Facebook через Apify (опційно, `APIFY_TOKEN`), LinkedIn/X/Threads через пошуковий
  API Tavily з обмеженням за доменами (опційно, `TAVILY_API_KEY`). Без ключів колектор вимикається
  і дайджест показує, що джерело неактивне.
- Telegram: глобального пошуку без акаунта нема → канали з конфігу + handles з Wikidata
  (P3789) + `t.me`-посилання, знайдені в новинах.

## Етика та приватність
- У базу людей потрапляють лише публічні особи (Wikidata/Вікіпедія) і ті, кого медіа
  публічно назвали могилянцями. Жодного скрейпінгу приватних профілів.
- Моніторимо тільки публічні дописи; зберігаємо посилання + короткий фрагмент.

## Архітектура
```
mohyla/
  models.py            Person, Item, Edge (frozen dataclasses); спільний контракт
  http.py              ввічливий fetch: чесний User-Agent, таймаути, ретраї
  people/
    wikidata.py        SPARQL: P69/P108 = Q1133013 (НаУКМА), живі люди, соцхендли
    wikipedia.py       члени категорій uk.wikipedia (НаУКМА, kmbs)
    names.py           нормалізація, варіанти імен, відмінкові стеми, транслітерація
    graph.py           злиття джерел, ребра (спільний роботодавець, спільна згадка),
                       snowball: «випускниця Могилянки Ім'я Прізвище» → кандидати
  collectors/
    rss.py             RSS НаУКМА + Google News RSS за запитами
    telegram.py        t.me/s/<channel> (публічний веб-прев'ю)
    bluesky.py         searchPosts з app password (опційно)
    facebook_apify.py  (опційно)
    websearch.py       Tavily Search: linkedin.com|x.com|threads.com|instagram.com (опційно)
  match.py             релевантність до Могилянки + зв'язок item ↔ люди
  rank.py              скоринг, дедуп (URL + схожість заголовків), категорії
  digest.py            HTML + JSON дайджест, архів днів
  cli.py               `people` (оновити граф), `daily` (зібрати дайджест)
config/sources.yaml    фіди, канали, запити, ключові слова, ваги
data/                  people.json, graph.json, candidates.json, seen.json, digests/
docs/                  згенерований сайт для GitHub Pages
.github/workflows/daily.yml
```

## Етапи
1. Скелет: моделі, конфіг, http, CLI. ✅ спільний контракт
2. Люди та граф (Wikidata + Вікіпедія + snowball-кандидати).
3. Колектори (RSS/Google News/Telegram обов'язкові; Bluesky/FB/web-search опційні).
4. Матчинг, ранжування, рендер дайджесту.
5. GitHub Actions: щоденно 06:00 Київ (`people` щотижня).
6. Перший прогін, перевірка якості, превʼю.
7. Пізніше: імпорт архіву випускників, коли сторінка стане доступною; LLM-підсумки.
