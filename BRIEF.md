# Earth Analog Finder — Brief

[English](#english) · [Українська](#українська)

---

## English

### 1. What it is

Earth Analog Finder looks for places on Earth that resemble a chosen location on Mars (later
also the Moon) **for a specific mission purpose** — for example a rover expedition, a landing
site or a permanent base. It compares measurable properties (terrain, minerals, temperature,
dryness, vegetation, etc.) of Earth locations against a fixed reference profile of the
planetary site and ranks Earth places by how closely they match, explaining every score.

The goal is to surface **places not yet known as analogs**, while checking the method against
recognised analog sites (Atacama, Río Tinto, Lake Salda, Devon Island, Antarctic Dry Valleys…).

**Current status:** specification, plan and task list are complete (`specs/001-earth-analog-finder/`).
No application code yet. Version 1 targets one Mars profile: *rover expedition at the Jezero
crater delta*.

### 2. Core ideas

- **Reference profile ("etalon")**: a frozen, versioned JSON file describing the Mars site:
  location and footprint (20 km radius), a list of criteria with target values, tolerances,
  veto limits and weights. It is completed before any Earth data is analysed and never adjusted
  to fit Earth results.
- **Purpose decides what matters**: each purpose ranks the 8 analogy categories of the challenge
  (geology, terrain, thermal, resources, atmosphere, biology, subsurface, operations). Criteria
  are ranked inside each category. The system converts ranks into weights with a fixed formula
  (rank-order centroid). Weights are a human decision, stored in configuration, never in code.
- **Same quantity, same area**: an Earth value is only compared with a Mars value if both
  describe the same physical quantity, statistic, unit, spatial footprint and measurement scale
  (e.g. slope measured over the same distance).
- **Transparent scoring, no machine learning**: every criterion becomes a score from 0 to 1;
  one badly failing criterion cannot be hidden by good ones.
- **Honest limits**: things Earth cannot reproduce (vacuum, gravity, lunar temperatures) are
  shown as "not comparable" or scored relative to Earth's own range and labelled as such.

### 3. How it works (pipeline)

One main command (`analog run`) runs these stages; each can also run alone, and each result is
cached and reused when its inputs have not changed.

1. **Source check** — confirms every data source is reachable and logins (e.g. free NASA
   Earthdata) are configured before any work starts.
2. **Global Earth grid** (built once, reused) — all land on Earth on a 0.05° grid (~5.5 km
   cells, a few million land cells) with layers stacked from several public datasets:
   land cover, land-surface temperature and vegetation (NASA MODIS), climate (NASA POWER,
   ERA5 as fallback), terrain statistics (ETOPO 2022). Target: ≤ 10 minutes from cached
   downloads.
3. **Screening** — for every land cell the layer values are summarised over a 20 km circle
   (same footprint as the Mars target). Hard constraints (latitude, no cities/cropland/ice) and
   veto limits remove unsuitable land; values impossible on Earth are ranked against Earth's
   own distribution (percentiles). Survivors get a screening score.
4. **Candidate areas** — neighbouring good cells are grouped into areas for presentation; each
   area is represented by its best location.
5. **Refinement (expensive data, only where it can matter)** — detailed 30 m terrain (slope and
   roughness at rover scale) and EMIT mineral maps are fetched in order of each area's best
   *possible* final score. Cheap terrain comes first, heavy mineral data only for areas that can
   still reach the top results. Refinement stops once the top results are proven, or at a cap.
6. **Scoring and ranking** — per criterion score 0–1 (inside target range = 1, falling to 0 at
   the tolerance); any score below its veto rejects the area; the overall score is a **weighted
   geometric mean**, so a very low score pulls the total down hard. Missing data is "unknown"
   (not a mismatch) and lowers a **confidence** value.
7. **Calibration** — known analog sites are scored the same way; if none ranks in the top 20 %,
   the profile is flagged for review and publishing is blocked. A weight-stability check shows
   how robust the ranking is to small weight changes.
8. **Deduplication (later stage)** — candidates near known analogs are labelled "known analog",
   the rest "new candidate".
9. **Static site** — generated HTML pages with a simple SVG world map; deployable to GitHub
   Pages or Cloudflare Pages.

### 4. What comes out

- **Ranked list of candidate areas** (`results.json`, `results.csv`) — for each area:
  location and footprint, overall score, confidence, the limiting (worst) criterion, and per
  criterion the Earth value, the Mars target, the **deviation** (in the criterion's unit and as a
  share of tolerance), the score, the data source and whether it is absolute, relative or not
  comparable; plus a plain-language statement of where the analogy breaks down.
- **Run record** — exactly which profile version, data versions and settings produced the
  result, so it can be reproduced.
- **Calibration report** — ranks of known analog sites and ranking stability.
- **Labels** — "known analog" vs "new candidate" (after deduplication).
- **Website** — map + ranked table + one page per candidate + a page explaining the method;
  readable without JavaScript, no external fonts, initial download under 2 MB.

### 5. Data and technology

- Earth: NASA MODIS (MCD12C1, MOD11C3, MOD13C2), NASA POWER, NASADEM / Copernicus DEM, ETOPO 2022,
  NASA EMIT (minerals), ERA5 (fallback). Mars: CRISM, MOLA/HRSC, CTX/HiRISE DTMs, THEMIS, rover
  climate data. All free; some need a free account.
- Python 3.11 command-line pipeline (numpy, scipy, rasterio, pyhdf, h5py, STAC/earthaccess
  clients, jsonschema, Jinja2); files only (GeoTIFF, JSON, CSV), no database, no server.

### 6. Where to read more

Constitution `.specify/memory/constitution.md` · Spec `specs/001-earth-analog-finder/spec.md` ·
Plan `plan.md` · Decisions `research.md` · Tasks `tasks.md` · Validation guide `quickstart.md`.

---

## Українська

### 1. Що це

Earth Analog Finder шукає на Землі місця, схожі на обрану ділянку Марса (згодом і Місяця),
**для конкретної мети місії** — наприклад, експедиції ровера, місця посадки чи постійної бази.
Система порівнює вимірювані властивості земних місць (рельєф, мінерали, температуру, посушливість,
рослинність тощо) із фіксованим еталонним профілем планетарної ділянки та ранжує земні місця за
ступенем відповідності, пояснюючи кожну оцінку.

Мета — знайти **місця, ще не відомі як аналоги**, і водночас перевірити метод на визнаних
аналогах (Атакама, Ріо-Тінто, озеро Салда, острів Девон, Сухі долини Антарктиди…).

**Поточний стан:** специфікація, план і перелік завдань готові (`specs/001-earth-analog-finder/`).
Коду застосунку ще немає. Версія 1 охоплює один марсіанський профіль: *експедиція ровера в дельті
кратера Єзеро*.

### 2. Основні ідеї

- **Еталонний профіль**: зафіксований JSON-файл із версією, що описує марсіанську ділянку:
  розташування та зону охоплення (радіус 20 км), перелік критеріїв із цільовими значеннями,
  допусками, межами вето та вагами. Профіль заповнюється повністю до аналізу земних даних і
  ніколи не підганяється під земні результати.
- **Мета визначає важливість**: кожна мета впорядковує 8 категорій аналогічності з умов челенджу
  (геологія, рельєф, теплові умови, ресурси, атмосфера, біологія, підповерхневі структури,
  операційні умови). Критерії впорядковуються всередині категорій. Система перетворює ранги на
  ваги за фіксованою формулою (rank-order centroid). Ваги — рішення людини; вони зберігаються в
  конфігурації, а не в коді.
- **Та сама величина, та сама площа**: земне значення порівнюється з марсіанським лише тоді, коли
  обидва описують ту саму фізичну величину, статистику, одиницю, зону охоплення та масштаб вимірювання
  (наприклад, нахил, виміряний на однаковій відстані).
- **Прозоре оцінювання без машинного навчання**: кожен критерій отримує оцінку від 0 до 1;
  один критерій із дуже поганим результатом не можна «приховати» добрими.
- **Чесні обмеження**: те, чого Земля не може відтворити (вакуум, гравітація, місячні температури),
  позначається як «непорівнюване» або оцінюється відносно власного діапазону Землі з відповідною
  позначкою.

### 3. Як це працює (конвеєр)

Одна основна команда (`analog run`) виконує ці етапи; кожен можна запустити окремо, а кожен
результат кешується й повторно використовується, якщо вхідні дані не змінилися.

1. **Перевірка джерел** — підтверджує доступність усіх джерел даних і налаштування входу
   (наприклад, безкоштовного облікового запису NASA Earthdata) до початку роботи.
2. **Глобальна сітка Землі** (будується один раз і перевикористовується) — уся суходільна
   поверхня Землі на сітці 0,05° (комірки ≈ 5,5 км, кілька мільйонів комірок суходолу) із шарами з
   кількох відкритих наборів даних: земний покрив, температура поверхні й рослинність (NASA MODIS),
   клімат (NASA POWER, резервно ERA5), характеристики рельєфу (ETOPO 2022). Ціль: ≤ 10 хвилин із
   кешованих завантажень.
3. **Відбір (скринінг)** — для кожної комірки суходолу значення шарів узагальнюються в колі
   радіусом 20 км (та сама зона, що й для марсіанського еталона). Жорсткі обмеження (широта, без
   міст/ріллі/льоду) та межі вето відкидають непридатні території; значення, неможливі на Землі,
   ранжуються відносно земного розподілу (перцентилі). Решта отримує оцінку скринінгу.
4. **Області-кандидати** — сусідні придатні комірки групуються в області для відображення;
   кожну область представляє її найкраща точка.
5. **Уточнення (дорогі дані — лише там, де це може вплинути)** — детальний рельєф 30 м (нахил і
   шорсткість у масштабі ровера) та мінеральні карти EMIT завантажуються в порядку найкращої
   *можливої* підсумкової оцінки області. Спершу дешевий рельєф, важкі мінеральні дані — лише для
   областей, які ще можуть потрапити в топ. Уточнення зупиняється, щойно топ-результати доведено,
   або при досягненні ліміту.
6. **Оцінювання та ранжування** — оцінка кожного критерію 0–1 (у межах цільового діапазону = 1,
   спадає до 0 на межі допуску); будь-яка оцінка нижче вето відкидає область; загальна оцінка —
   **зважене геометричне середнє**, тож дуже низька оцінка сильно знижує підсумок. Відсутні дані —
   «невідомо» (а не невідповідність) і знижують показник **достовірності**.
7. **Калібрування** — відомі аналоги оцінюються тим самим способом; якщо жоден не потрапляє в
   топ-20 %, профіль позначається для перегляду, а публікація блокується. Перевірка стабільності
   ваг показує, наскільки ранжування стійке до невеликих змін ваг.
8. **Дедуплікація (пізніший етап)** — кандидати поблизу відомих аналогів позначаються
   «відомий аналог», решта — «новий кандидат».
9. **Статичний сайт** — згенеровані HTML-сторінки з простою SVG-картою світу; розгортаються на
   GitHub Pages або Cloudflare Pages.

### 4. Що отримуємо на виході

- **Ранжований список областей-кандидатів** (`results.json`, `results.csv`) — для кожної області:
  розташування й зона охоплення, загальна оцінка, достовірність, обмежувальний (найгірший)
  критерій, а для кожного критерію — земне значення, марсіанська ціль, **відхилення** (в одиницях
  критерію та як частка допуску), оцінка, джерело даних і тип порівняння (абсолютне, відносне чи
  непорівнюване); а також опис простими словами, де аналогія не працює.
- **Запис запуску** — які саме версія профілю, версії даних і налаштування дали результат, щоб його
  можна було відтворити.
- **Звіт калібрування** — позиції відомих аналогів і стабільність ранжування.
- **Мітки** — «відомий аналог» або «новий кандидат» (після дедуплікації).
- **Вебсайт** — карта + ранжована таблиця + окрема сторінка для кожного кандидата + сторінка з
  поясненням методу; читається без JavaScript, без зовнішніх шрифтів, початкове завантаження
  менше 2 МБ.

### 5. Дані та технології

- Земля: NASA MODIS (MCD12C1, MOD11C3, MOD13C2), NASA POWER, NASADEM / Copernicus DEM, ETOPO 2022,
  NASA EMIT (мінерали), ERA5 (резерв). Марс: CRISM, MOLA/HRSC, цифрові моделі рельєфу CTX/HiRISE,
  THEMIS, кліматичні дані роверів. Усі безкоштовні; для деяких потрібен безкоштовний обліковий запис.
- Конвеєр командного рядка на Python 3.11 (numpy, scipy, rasterio, pyhdf, h5py, клієнти
  STAC/earthaccess, jsonschema, Jinja2); лише файли (GeoTIFF, JSON, CSV), без бази даних і сервера.

### 6. Де читати детальніше

Конституція `.specify/memory/constitution.md` · Специфікація `specs/001-earth-analog-finder/spec.md` ·
План `plan.md` · Рішення `research.md` · Завдання `tasks.md` · Посібник перевірки `quickstart.md`.
