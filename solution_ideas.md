# NASA Space Apps Challenge 2026: Solution proposals and technical roadmap

## 1. Executive assessment

After reviewing the challenge description you provided, I would approach this hackathon as a geospatial science and data-analysis project, rather than a conventional software-development competition.

That distinction is important because your team does not need extensive software engineering experience to produce something genuinely useful. Python is particularly well suited to this challenge: it has mature libraries for satellite imagery, geospatial analysis, scientific computing, machine learning, and interactive data visualization.

The challenge is essentially asking you to solve this problem:

> Can we use scientific observations of Earth, the Moon, and Mars to discover, rank, and explain locations on Earth that could help scientists prepare for planetary exploration?

There are several possible interpretations of this task, and they lead to quite different projects:

- Discovery: Find previously overlooked locations on Earth that resemble specific lunar or Martian environments.
- Scientific comparison: Explain why an Earth location is analogous to a particular lunar or Martian environment, using measurable characteristics rather than visual resemblance.
- Decision support: Build a tool that helps researchers evaluate and compare potential terrestrial analog sites.
- Mission preparation: Identify locations on Earth where researchers could test equipment, mobility systems, resource-extraction technologies, or scientific instruments.
- Education and exploration: Make planetary science accessible through interactive maps, visual comparisons, and data-driven storytelling.

### My main recommendation

I would prioritize building a Python-based Terrestrial Planetary Analog Discovery Platform.

It could combine:

- Open satellite and planetary datasets.
- Geographic and environmental data processing.
- A multi-criteria similarity-ranking algorithm.
- An interactive map of candidate locations.
- Scientific explanations of why each location is interesting.
- An explicit assessment of where the Earth–Moon or Earth–Mars analogy breaks down.

Importantly, this does not have to be a sophisticated machine-learning platform. A transparent, scientifically justified scoring algorithm using several datasets could be more valuable than an impressive-looking but poorly validated AI model.

For a two-day hackathon, the most realistic strategy is to build a functioning scientific prototype with a limited geographical scope, rather than attempt to characterize the entire planet comprehensively.

## 2. What I found on the official challenge page and its data resources

The official challenge page identifies the task as suitable for all three experience levels:

- Beginner/Youth
- Intermediate
- Advanced

Its subject areas are Earth Science, Planets & Moons, Software, and Space Exploration.

spaceappschallenge.org

+1

I could retrieve the official challenge description, but the website's detailed resource tab was not accessible through the page reader. I therefore cross-checked the challenge against an independent 2026 Space Apps dataset catalogue. The catalogue explicitly states that its recommendations are independent, not NASA-endorsed, and are not a substitute for the official resource list.

spacedata.swapniltamse.com

+1

One important competition consideration: a NASA Space Apps team response published on November 6 states that teams seeking Global Awards must use at least one NASA data source included in the individual challenge's official Resources section. AI tools are permitted, but they should support rather than replace your team's contribution. Verify the exact resource requirement against the official challenge page before submission.

GitHub

### 2.1. The six particularly relevant datasets

These are the six datasets identified by the independent catalogue for this particular challenge. They are an excellent starting point for planning your architecture.

| Dataset | Provider | What it provides | Potential use |
| --- | --- | --- | --- |
| EMIT L2B Surface Mineral Identification | NASA | Mineral identification across Earth's surface | Discover terrestrial areas with mineralogical characteristics relevant to Mars |
| SRTM Global Elevation | NASA | Global elevation measurements, approximately 30 m resolution | Terrain, slopes, elevation, craters and valleys |
| Harmonized Landsat Sentinel-2 (HLS) | NASA | Multispectral surface observations at approximately 30 m | Surface reflectance, vegetation, water and environmental characteristics |
| CRISM MTRDR | NASA / Mars Reconnaissance Orbiter | Mineralogical maps of Mars | Compare Martian mineralogy with terrestrial mineral observations |
| Mars Trek WMTS | NASA JPL | Martian imagery and topography | Visual and topographical comparison with Earth |
| LRO Diviner | NASA / UCLA | Lunar surface-temperature observations | Compare terrestrial temperature characteristics with lunar environments |

Sources:

Space Data Atlas

.

Why these datasets matter:

There is a particularly interesting opportunity in combining EMIT and CRISM.

EMIT identifies minerals on Earth, while CRISM provides mineralogical observations of Mars. This creates the foundation for a meaningful cross-planetary comparison rather than simply comparing satellite photographs.

Likewise, SRTM and Mars Trek can support topographical comparisons, while HLS can help characterize vegetation, exposed ground and surface conditions.

A practical distinction: the lunar Diviner temperature data should not be interpreted as something Earth locations can reproduce. Instead, you can use it to demonstrate how terrestrial thermal conditions differ from lunar extremes.

### 2.2. Recommended additional data sources

I would also investigate these resources:

- NASA Earthdata: Access to Earth observation datasets and scientific data products. [NASA Earthdata](<https://www.earthdata.nasa.gov/?utm_source=chatgpt.com>).
- NASA Solar System Treks: Planetary surface mapping and visualization. [NASA Trek](<https://trek.nasa.gov/?utm_source=chatgpt.com>).
- NASA Planetary Data System: Archived planetary mission data. [NASA PDS](<https://pds.nasa.gov/?utm_source=chatgpt.com>).
- NASA Earth Observatory: Earth imagery and environmental explanations. [Earth Observatory](<https://earthobservatory.nasa.gov/?utm_source=chatgpt.com>).
- USGS EarthExplorer: Additional satellite imagery and terrain datasets. [EarthExplorer](<https://earthexplorer.usgs.gov/?utm_source=chatgpt.com>).

For a two-day project, I would not download everything. Pick two or three datasets that directly support your research question.

### 2.3. What I would avoid

A few tempting approaches are likely to waste your time:

- Downloading enormous satellite image collections and attempting global analysis.
- Training a neural network from scratch to classify planetary analogs.
- Building a complete 3D digital twin of a lunar or Martian environment.
- Trying to compare every environmental variable on Earth, the Moon and Mars.
- Building a sophisticated web application before you have meaningful scientific results.
- Using an LLM to generate similarity scores without an underlying scientific methodology.

Instead, make the scientific analysis the centrepiece and build the application around it.

# 3. Solution proposals ranked by relevance and suitability

I have divided the proposals into seven concepts.

The ranking considers five factors:

1. Alignment with the challenge's actual objectives.
2. Feasibility within two days.
3. Suitability for a three-person Python-oriented team.
4. Potential to produce something genuinely useful.
5. Opportunity to learn something new without requiring extensive software engineering experience.

The difficulty labels have the following meaning:

- Beginner/Youth: Mostly data collection, simple analysis, visualization and documentation. Little programming experience required.
- Intermediate: Multiple datasets, Python data processing, geographic analysis, custom logic and an application or structured scientific output.
- Advanced: More sophisticated data integration, spatial modelling, machine learning, substantial data engineering or scientific validation.

The person-hour estimates below are approximate total team effort, not elapsed time.

# 4. Proposed solutions

## Solution 1 — TerraAnalog Explorer: Interactive Planetary Analog Discovery Platform

Best overall recommendation Intermediate

Solution type: Python web application + geospatial database + scientific similarity-ranking engine.

Concept: Build an interactive platform that identifies, characterizes and ranks terrestrial environments according to their similarity to selected lunar or Martian environments.

### 1. Brief description

The application would allow users to investigate potential Earth analog locations by selecting a planetary target and defining which environmental characteristics matter most.

For example:

- Mars: mineralogy, exposed rocky terrain, low vegetation, temperature and topography.
- Lunar South Pole: rugged terrain, illumination-related considerations, surface slope and thermal extremes.
- Mars subsurface exploration: volcanic terrains, caves, lava tubes and geological structures.

The system would process a predefined set of candidate terrestrial locations, calculate similarity scores, and rank them.

Instead of telling users that a particular desert looks like Mars, it would explain why that desert may be scientifically interesting.

### 2. What is it and how will it look?

Imagine opening a website called TerraAnalog Explorer.

The main interface contains:

- A map showing potential terrestrial analog sites.
- A planetary target selector: Moon or Mars.
- A selection of comparison criteria.
- A ranked list of candidate locations.
- A scientific profile for each location.

Example user story:

A researcher wants to find terrestrial environments with characteristics relevant to Martian surface exploration.

They select:

- Target: Mars.
- Terrain: Rocky and arid.
- Mineralogy: Clay-bearing or sulfate-bearing materials.
- Vegetation: Minimal.
- Topography: Relatively flat terrain with nearby geological features.

The application returns a shortlist of candidate locations.

Each result contains:

- Location name and coordinates.
- Similarity score.
- Individual criterion scores.
- Available supporting observations.
- Strengths and limitations of the analogy.
- Potential scientific or operational applications.

For example, a hypothetical location might score:

| Criterion | Similarity |
| --- | --- |
| Surface mineralogy | 88/100 |
| Terrain characteristics | 82/100 |
| Vegetation absence | 95/100 |
| Temperature characteristics | 60/100 |
| Overall weighted score | 81/100 |

These are illustrative numbers, not measured results.

### 3. Estimated difficulty

IntermediateEstimated effort: 40–55 person-hours.

For three people, this is approximately 13–18 hours per person.

Breakdown:

- Dataset research and preparation: 8–10 hours.
- Geospatial processing: 10–14 hours.
- Similarity algorithm: 5–7 hours.
- Application and visualization: 8–12 hours.
- Testing, scientific interpretation and presentation: 9–12 hours.

Required background:

- Basic Python.
- Familiarity with pandas and NumPy.
- Ability to follow GIS and raster-processing tutorials.
- Some assistance from an AI coding agent.

You do not need professional GIS experience if you keep the geographical scope manageable.

### 4. Recommended stack

| Component | Technology |
| --- | --- |
| Main language | Python |
| Data processing | pandas, NumPy |
| Geospatial analysis | GeoPandas, Rasterio, Shapely |
| Satellite data | earthaccess |
| Visualization | Plotly |
| Interactive map | Folium |
| Application interface | Streamlit |
| Data storage | GeoPackage, CSV, GeoTIFF |
| Similarity algorithm | scikit-learn or custom weighted scoring |
| Optional database | SQLite / SpatiaLite |

No JavaScript programming is required for your application code.

Streamlit and Folium provide Python interfaces for the interactive application and map.

### 5. Tools and external requirements

- Three laptops with Python environments.
- GitHub repository for collaboration.
- Free NASA Earthdata accounts, if needed for selected downloads.
- NASA data access and planetary data resources.
- An AI coding assistant such as ChatGPT, Claude or Cursor.
- Optional: QGIS for inspecting and validating geospatial datasets.

Paid subscriptions: Not mandatory.

### 6. Division of work between three people

- Person A – Earth data specialist: Download and process SRTM, HLS and EMIT data.
- Person B – Planetary comparison specialist: Research Mars or lunar reference characteristics and implement the similarity calculations.
- Person C – Application and integration specialist: Build the Streamlit interface, map, results pages and integrate the other components.

All three can work independently initially and integrate their outputs through CSV, GeoJSON or GeoPackage files.

### 7. Why this is particularly suitable

This is probably the most balanced solution for your team.

It has a clear scientific purpose, an understandable user interface, a meaningful analytical component and a demonstrable result.

You can also keep extending it after the hackathon.

The main limitation is that you should not claim to have developed a universal planetary similarity model. Your results should be presented as preliminary, transparent comparisons based on the available datasets.

## Solution 2 — MarsMatch: Earth–Mars Mineralogical Similarity Finder

Excellent scientific alignment Intermediate

Solution type: Scientific data-analysis application + mineralogical comparison engine + interactive visualization.

### 1. Brief description

Build a tool that searches for terrestrial locations whose surface mineralogical characteristics resemble selected Martian regions.

This is a particularly interesting approach because it addresses one of the challenge's most important considerations: analogies should be based on scientific characteristics rather than visual similarity.

The central idea is to compare:

- Minerals detected on Mars by CRISM.
- Minerals identified on Earth by NASA's EMIT instrument.
- Geographic distribution of those observations.

The application would identify terrestrial regions with potentially relevant mineralogical characteristics.

### 2. What is it and how will it look?

Imagine a researcher selecting Jezero Crater on Mars.

The application displays:

1. A reference Martian mineralogical profile.
2. Earth locations with potentially similar mineral signatures.
3. A comparison of detected mineral classes.
4. A map of candidate locations.
5. An explanation of why these locations might be useful.

The interface could include side-by-side mineralogical profiles.

For example:

| Mineral characteristic | Mars reference | Earth candidate |
| --- | --- | --- |
| Clay minerals | Detected | Detected |
| Sulfates | Detected | Not detected |
| Carbonates | Detected | Detected |
| Iron-bearing minerals | Detected | Detected |

This is an illustrative comparison. Actual results would depend on the selected observations and available spectral products.

Potential use case:

A planetary geologist wants to identify terrestrial environments where equipment designed to study Martian minerals could be tested.

The tool identifies locations where comparable mineral classes occur and provides a starting point for field research.

### 3. Estimated difficulty

IntermediateEstimated effort: 35–50 person-hours.

Difficulty comes primarily from understanding the data formats and ensuring that the mineralogical comparisons are scientifically meaningful.

Tasks:

- Understanding CRISM and EMIT products: 6–10 hours.
- Downloading and inspecting data: 7–10 hours.
- Extracting mineralogical information: 8–12 hours.
- Building comparison logic: 5–7 hours.
- Visualization and presentation: 9–11 hours.

### 4. Recommended stack

- Python.
- pandas and NumPy.
- xarray.
- Rasterio.
- GeoPandas.
- Matplotlib and Plotly.
- Streamlit.
- scikit-learn for optional clustering.
- earthaccess for NASA Earthdata discovery and downloads.
- requests for suitable planetary archive APIs.

### 5. Tools and external requirements

- NASA Earthdata account for relevant Earth observations.
- Access to CRISM planetary data.
- QGIS for inspecting raster products.
- AI coding assistant for understanding unfamiliar scientific data formats.

No special paid software or hardware is necessary.

### 6. Division of work

- Person A: Research EMIT data, retrieve Earth mineralogical observations.
- Person B: Research CRISM data, retrieve Martian reference observations.
- Person C: Implement the comparison algorithm, visualization and user interface.

### 7. Why this is interesting

This project has a strong scientific narrative.

It demonstrates that an Earth analog can be meaningful even when the two locations look completely different.

For example, a terrestrial geological environment might have comparable mineral alteration processes to a Martian location without resembling its surface visually.

Main risk: CRISM and EMIT products are not automatically interchangeable. Their spectral characteristics, spatial resolutions, mineral-classification methods and observation conditions differ.

You should compare mineral classes or carefully harmonized derived characteristics, not pretend that the raw measurements are directly equivalent.

For a two-day hackathon, I would select one Martian reference region and a small number of terrestrial candidate regions rather than attempt global mineralogical matching.

## Solution 3 — AnalogQuest: Global Earth Analog Discovery and Ranking System

IntermediateSolution type: Geospatial data-analysis engine + geographic discovery application + ranked scientific catalogue.

### 1. Brief description

Instead of starting with known analog locations, build a system that searches for potentially interesting locations across a predefined geographical area.

The objective is to discover locations that might not be widely recognized as planetary analogs.

You could focus on a specific environment:

- Volcanic terrain.
- Salt flats.
- Polar deserts.
- Arid mountain environments.
- Impact craters.
- Ancient riverbeds.
- Permafrost regions.

The system would calculate environmental characteristics and identify areas that satisfy a predefined combination of criteria.

### 2. What is it and how will it look?

Think of it as a scientific search engine for terrestrial analog environments.

A user selects a target:

Find potential Mars analogs.

The system searches a predefined region and identifies candidate locations.

Each candidate receives a profile:

- Coordinates.
- Terrain classification.
- Elevation.
- Slope.
- Vegetation index.
- Surface temperature, where available.
- Mineralogical observations, where available.
- Relevant scientific interpretation.

Example user story:

A researcher is interested in identifying unexplored terrestrial analogs for Martian geological processes.

They select arid volcanic environments.

The system searches several predefined geographical areas and highlights locations with exposed volcanic surfaces, minimal vegetation and suitable terrain characteristics.

The result is a ranked shortlist for further investigation.

### 3. Estimated difficulty

IntermediateEstimated effort: 35–50 person-hours.

The main difficulty is geospatial processing and the management of multiple datasets.

A fully global search is unrealistic within two days.

I would recommend restricting the first implementation to three or four regions, potentially across different continents.

### 4. Recommended stack

- Python.
- Rasterio.
- GeoPandas.
- NumPy.
- pandas.
- SciPy.
- scikit-learn.
- Streamlit.
- Folium.
- Plotly.
- NASA SRTM and HLS datasets.
- Optional EMIT mineralogical data.

### 5. Tools and external requirements

- QGIS.
- NASA Earthdata account.
- GitHub.
- AI coding assistant.
- A computer with sufficient storage for raster processing.

No specialized paid services are necessary.

### 6. Division of work

- Person A: Select geographical regions and acquire terrain data.
- Person B: Process environmental and satellite data.
- Person C: Develop the ranking engine and application.

### 7. Why this is interesting

The strongest aspect is discovery.

The project directly responds to the challenge's encouragement to look beyond established analog sites.

However, there is a distinction between finding a location with matching environmental characteristics and proving that it is a useful planetary analog.

The application should describe its findings as candidate sites requiring scientific validation.

## Solution 4 — Lunar/Mars Terrain Twin: Comparative Digital Terrain Model

IntermediateSolution type: Digital scientific model + 2D/3D visualization + comparative terrain analysis.

### 1. Brief description

Create a digital terrain comparison tool that allows users to investigate how Earth's geological landscapes compare with selected regions of the Moon or Mars.

Rather than trying to create a complete planetary digital twin, focus on comparing terrain characteristics.

Potential characteristics:

- Elevation profiles.
- Slope distributions.
- Crater density.
- Surface roughness.
- Valley structures.
- Terrain fragmentation.
- Relative elevation differences.

### 2. What is it and how will it look?

The user selects:

- A terrestrial location.
- A lunar or Martian reference location.

The application generates:

- Two elevation maps.
- Two slope maps.
- Elevation histograms.
- Slope distributions.
- Terrain profiles.
- A quantitative similarity report.

Example user story:

A researcher wants to find a terrestrial location where a rover can be tested in an environment with terrain characteristics resembling a particular Martian region.

They select a Martian reference region and compare it against several terrestrial volcanic landscapes.

The application identifies the closest terrain match based on the selected topographical indicators.

The output could also be exported as a scientific report.

### 3. Estimated difficulty

IntermediateEstimated effort: 30–45 person-hours.

This is relatively achievable because elevation data is often easier to work with than hyperspectral mineralogical datasets.

However, obtaining compatible lunar, Martian and Earth elevation data requires attention to coordinate systems, spatial resolution and vertical reference systems.

### 4. Recommended stack

- Python.
- Rasterio.
- NumPy.
- SciPy.
- GeoPandas.
- Matplotlib.
- Plotly.
- PyVista for optional 3D visualization.
- Streamlit.
- NASA SRTM.
- Mars Trek / MOLA.
- Lunar topographic data from NASA's Lunar Reconnaissance Orbiter products.

### 5. Tools and external requirements

- QGIS.
- Python scientific environment.
- NASA planetary data archives.
- AI coding assistant.

A GPU is not mandatory.

### 6. Division of work

- Person A: Acquire and prepare terrestrial elevation data.
- Person B: Acquire planetary elevation data.
- Person C: Develop comparative metrics and visualizations.

### 7. Why this is interesting

It is tangible and easy to demonstrate.

The audience can immediately understand what is being compared.

It is also less dependent on complicated machine learning.

The principal limitation is that terrain similarity alone does not establish geological or environmental equivalence. Make that explicit in your report.

## Solution 5 — Analog Mission Planner: Find the Right Earth Environment for a Mission Experiment

IntermediateSolution type: Python decision-support application + multi-criteria evaluation system.

### 1. Brief description

This solution focuses on the practical question:

Where on Earth should we conduct an experiment before sending the relevant equipment to the Moon or Mars?

Rather than simply ranking planetary analogs, the system evaluates locations according to specific mission objectives.

Possible mission objectives:

- Test autonomous rover navigation.
- Test robotic drilling.
- Test geological sampling.
- Test equipment in extreme temperatures.
- Test autonomous navigation in rocky terrain.
- Study subsurface geological structures.
- Investigate resource-extraction methods.

Different experiments require different terrestrial analogs.

### 2. What is it and how will it look?

The interface begins with a mission selector.

For example:

Mission: Test a Mars rover's autonomous navigation.

The user chooses:

- Terrain: rocky.
- Surface: low vegetation.
- Slope: moderate.
- Terrain complexity: high.
- Accessibility: preferably accessible for field testing.

The application returns suitable terrestrial environments.

A result could look like:

Candidate A — Volcanic terrain

- Terrain characteristics: Strong match.
- Surface composition: Partial match.
- Environmental conditions: Weak match.
- Operational testing value: High.
- Limitations: Does not reproduce Martian atmospheric conditions.

### 3. Estimated difficulty

IntermediateEstimated effort: 30–40 person-hours.

This is a manageable project because you can use a relatively simple decision-support algorithm.

### 4. Recommended stack

- Python.
- pandas.
- NumPy.
- GeoPandas.
- scikit-learn, optional.
- Streamlit.
- Folium.
- Plotly.
- NASA SRTM, HLS and EMIT.

### 5. Tools and external requirements

- NASA Earthdata.
- QGIS.
- AI coding assistant.
- GitHub.

No mandatory paid subscriptions.

### 6. Division of work

- Person A: Research planetary mission requirements.
- Person B: Research and process terrestrial location data.
- Person C: Build the mission-selection and ranking interface.

### 7. Why this is interesting

This solution emphasizes the practical value of analog environments.

It also creates a more understandable use case than a generic similarity-ranking platform.

Its weakness is that you must carefully distinguish between mission suitability and environmental similarity. A site might be excellent for testing rover navigation but poor as a general Martian analog.

## Solution 6 — Planetary Analog Atlas: Interactive Scientific Storytelling and Research Catalogue

Beginner/YouthSolution type: Digital atlas + interactive map + scientific research publication.

### 1. Brief description

Create a curated digital atlas of terrestrial analog environments.

Unlike the previous projects, this does not need an automated discovery algorithm.

Instead, your team selects and investigates perhaps 8–12 locations worldwide.

Each location receives a detailed scientific profile explaining its potential relationship with the Moon or Mars.

The atlas becomes a structured resource for planetary science enthusiasts, researchers and educators.

### 2. What is it and how will it look?

The application contains an interactive world map.

Each point represents a terrestrial analog.

Clicking a location opens a profile with:

- Location overview.
- Geological characteristics.
- Terrain characteristics.
- Environmental conditions.
- Relevant NASA observations.
- Planetary comparison.
- Potential exploration applications.
- Known limitations.

You could include categories such as:

| Category | Example environment |
| --- | --- |
| Volcanic | Lava fields |
| Arid | Salt flats |
| Polar | Ice-free polar valleys |
| Geological | Impact craters |
| Subsurface | Lava tubes and caves |
| Sedimentary | Ancient dry river systems |

Example user story:

A university student wants to understand how researchers prepare for Mars exploration.

They open the atlas and explore different terrestrial environments.

Each location provides a short scientific explanation and visual evidence of its relevance to planetary exploration.

### 3. Estimated difficulty

Beginner/YouthEstimated effort: 20–30 person-hours.

This is the most approachable project for a team with limited programming experience.

### 4. Recommended stack

- Python.
- pandas.
- GeoPandas.
- Folium.
- Streamlit.
- Plotly.
- Markdown for scientific profiles.
- NASA Earth observation datasets.

### 5. Tools and external requirements

- QGIS.
- GitHub.
- NASA Earthdata.
- AI research and coding assistant.

No paid software is required.

### 6. Division of work

- Person A: Research and document 3–4 locations.
- Person B: Research and document 3–4 locations.
- Person C: Research the remaining locations and build the atlas.

All three can use a common location-profile template.

### 7. Why this is interesting

This is the safest option in terms of completion risk.

It can also be genuinely useful as an educational resource.

However, the scientific methodology needs to go beyond collecting interesting photographs and descriptions. Each profile should include at least some quantitative evidence from NASA data.

## Solution 7 — AnalogAI: AI-Assisted Planetary Analog Research Assistant

AdvancedSolution type: AI-assisted research application + scientific knowledge base + geospatial data retrieval.

### 1. Brief description

Develop an AI research assistant that helps users investigate relationships between terrestrial environments and planetary surfaces.

Instead of relying on a conventional chatbot with generic knowledge, it would use a structured collection of scientific observations, location profiles and dataset-derived measurements.

The AI would help interpret the data, generate comparative explanations and summarize scientific findings.

### 2. What is it and how will it look?

The user asks:

"Find terrestrial locations that could help scientists investigate Martian clay-bearing geological environments."

The system:

1. Identifies relevant Martian mineralogical characteristics.
2. Searches the prepared terrestrial analog database.
3. Retrieves matching locations.
4. Compares their available observations.
5. Generates a scientific summary.
6. Lists the evidence and uncertainties.

The user can ask follow-up questions:

- Why is this location a useful analog?
- Which characteristics are similar?
- What are the major differences?
- What scientific experiments could be performed there?
- Which NASA datasets support the comparison?

### 3. Estimated difficulty

AdvancedEstimated effort: 45–60 person-hours.

The difficulty is not simply integrating an LLM.

The challenge is making sure the assistant retrieves relevant scientific evidence rather than inventing explanations or treating approximate similarities as scientific conclusions.

### 4. Recommended stack

- Python.
- Streamlit.
- pandas.
- GeoPandas.
- SQLite.
- LangChain or LlamaIndex, optional.
- OpenAI API or another LLM API.
- scikit-learn.
- NASA data sources.

### 5. Tools and external requirements

- An LLM API subscription or credits.
- AI coding assistant.
- GitHub.
- NASA Earthdata.
- Optional vector database.

A local LLM is possible but unnecessary for the prototype.

### 6. Division of work

- Person A: Prepare scientific data and location profiles.
- Person B: Build data retrieval and comparison logic.
- Person C: Integrate the LLM and application interface.

### 7. Why this is interesting

It makes AI part of the scientific workflow rather than simply using it to generate text.

However, I would not recommend this as your primary project.

It introduces additional failure points, API dependencies and scientific reliability issues. A better approach would be to add a small AI explanation feature to Solution 1 after the main platform works.

# 5. Comparison of all proposed solutions

The following table ranks the seven concepts according to their overall suitability for your team and the challenge.

| Rank | Solution | Type | Difficulty | Person-hours | Main strength |
| --- | --- | --- | --- | --- | --- |
| 1 | TerraAnalog Explorer | Python web app + ranking engine | Intermediate | 40–55 | Best overall balance |
| 2 | MarsMatch | Scientific comparison application | Intermediate | 35–50 | Strong mineralogical science |
| 3 | AnalogQuest | Discovery and ranking system | Intermediate | 35–50 | Finds potentially overlooked locations |
| 4 | Terrain Twin | Digital terrain model | Intermediate | 30–45 | Strong visual demonstration |
| 5 | Analog Mission Planner | Decision-support application | Intermediate | 30–40 | Clear practical application |
| 6 | Planetary Analog Atlas | Digital atlas | Beginner/Youth | 20–30 | Lowest completion risk |
| 7 | AnalogAI | AI research assistant | Advanced | 45–60 | Interesting AI integration |

These are independent project concepts, but they are not mutually exclusive. Some can be combined into a single solution.

For example, TerraAnalog Explorer could incorporate the mineralogical comparison from MarsMatch and the mission-selection functionality from Analog Mission Planner.

That is the combination I would pursue.

# 6. My recommended project: TerraAnalog Explorer — combining the strongest ideas

I would not necessarily implement Solution 1 exactly as described. I would combine three of the proposals into a slightly more ambitious but still manageable project.

# TerraAnalog Explorer

A Python-powered planetary analog discovery and mission-preparation platform

Core proposition

Discover terrestrial locations that could help scientists prepare for lunar and Martian exploration by comparing measurable geological, topographical and environmental characteristics.

Three integrated capabilities

01Discover

Identify candidate Earth locations from a predefined collection of geographical regions.

02Compare

Compare their characteristics with selected lunar and Martian reference environments.

03Explain

Show why each location could be useful for a particular scientific experiment or exploration activity, including where the analogy breaks down.

## 6.1. Suggested application structure

I would create four main application sections.

### Section A — Planetary target selection

The user selects a reference environment.

Possible targets:

- Mars: Jezero Crater.
- Mars: Gale Crater.
- Mars: volcanic terrain.
- Moon: lunar South Pole.
- Moon: permanently shadowed regions.

Each target has a predefined scientific profile.

For the first prototype, I would limit this to:

1. Mars — Jezero Crater.
2. Moon — lunar South Pole.

Why?

These two targets provide different scientific challenges.

Jezero offers opportunities for mineralogical, geological and sedimentary comparisons. The lunar South Pole offers interesting topographical and thermal comparisons.

NASA's current Moon Base planning also focuses on the lunar South Pole, making it a particularly relevant reference environment.

NASA

+1

### Section B — Earth analog discovery

The application presents a selection of candidate locations.

I suggest beginning with six to eight locations rather than searching the entire world.

Potential research candidates:

| Location | Country/region | Main analogy to investigate |
| --- | --- | --- |
| McMurdo Dry Valleys | Antarctica | Extremely arid polar terrain |
| Dallol / Danakil Depression | Ethiopia | Extreme geology and mineral alteration |
| Salar de Uyuni | Bolivia | Salt-rich surfaces and arid environments |
| Icelandic volcanic fields | Iceland | Volcanic terrain and geological processes |
| Pilbara region | Australia | Ancient geological formations |
| Alashan Desert | China | Arid terrain and aeolian processes |
| Lanzarote volcanic fields | Spain | Basaltic volcanic terrain |
| Makgadikgadi salt pans | Botswana | Salt flats and exposed sedimentary surfaces |

These are candidate research areas, not established findings or a claim that they are previously undiscovered analogs.

Your team should select the final locations according to the actual available NASA observations.

### Section C — Scientific comparison

This is the most important section.

Each candidate should be evaluated across several dimensions.

I recommend using five dimensions for the initial implementation:

| Dimension | Suggested indicators | Potential source |
| --- | --- | --- |
| Mineralogy | Presence of relevant mineral classes | EMIT / CRISM |
| Terrain | Elevation, slope and surface roughness | SRTM / MOLA |
| Surface characteristics | Reflectance and vegetation | HLS |
| Thermal environment | Temperature range and variability | Earth observations / Diviner |
| Exploration relevance | Suitability for a defined experiment | Your team's documented assessment |

A key methodological recommendation: do not give all five dimensions equal importance automatically.

For example:

- A Mars mineralogical study should emphasize mineralogy.
- Rover navigation testing should emphasize terrain.
- A lunar thermal study should emphasize environmental and illumination-related conditions.

This is where the mission-oriented approach from Solution 5 becomes useful.

### Section D — Analog profile and scientific report

Every candidate should have its own profile.

I recommend the following structure:

Location: Candidate location name

Planetary target: Mars / Moon

Overall similarity: Calculated score, with methodology disclosed.

Strong similarities:

- Geological characteristics.
- Terrain.
- Surface materials.

Weak similarities:

- Temperature.
- Atmosphere.
- Gravity.
- Radiation environment.

Potential applications:

- Robotic testing.
- Geological field research.
- Instrument calibration.
- Exploration preparation.

Evidence:

- NASA dataset.
- Measurement or observation.
- Date and spatial resolution.
- Source reference.

Scientific limitations:

A clear explanation of what the Earth location cannot reproduce.

This last part is particularly important because the challenge explicitly encourages teams to recognize Earth's limitations as a planetary analog.

# 7. The scientific methodology: How to calculate similarity

This is the part I would spend the most intellectual effort on.

You do not need machine learning to produce a useful scientific comparison.

I would start with a multi-criteria weighted scoring model.

## 7.1. Basic concept

Every candidate location receives scores for several dimensions.

For example:

$$
S = \sum_{i=1}^{n} w_i s_i
$$

Where:

- $S$ = total similarity score.
- $w_i$ = importance weight of a criterion.
- $s_i$ = similarity score for that criterion.
- $n$ = number of criteria.

The weights must sum to 1.

For a hypothetical Mars geological investigation:

| Criterion | Weight |
| --- | --- |
| Mineralogy | 0.35 |
| Terrain | 0.25 |
| Surface characteristics | 0.20 |
| Thermal conditions | 0.10 |
| Exploration relevance | 0.10 |
| Total | 1.00 |

Suppose a candidate receives:

| Criterion | Score | Weight | Contribution |
| --- | --- | --- | --- |
| Mineralogy | 85 | 0.35 | 29.75 |
| Terrain | 90 | 0.25 | 22.50 |
| Surface characteristics | 80 | 0.20 | 16.00 |
| Thermal conditions | 60 | 0.10 | 6.00 |
| Exploration relevance | 90 | 0.10 | 9.00 |
| Total |  |  | 83.25 |

The resulting score is 83.25/100.

This would mean that the candidate has a strong match according to your selected criteria and weights. It would not mean that it is 83.25% identical to Mars.

## 7.2. Make the scoring scientifically defensible

There are several ways to implement the scoring.

Method A — Expert-defined categories

Your team defines scores based on published data and observed characteristics.

Example:

- 0–20: Very weak match.
- 21–40: Weak match.
- 41–60: Moderate match.
- 61–80: Strong match.
- 81–100: Very strong match.

This is easy to implement but requires documented reasoning.

Method B — Normalized numerical comparisons

For numerical measurements, compare the Earth and planetary reference values using a normalized distance metric.

For example:

$$
s_i = 100 \cdot \max\left(0,1-\frac{|x_E-x_P|}{R_i}\right)
$$

Where:

- $x_E$ = Earth measurement.
- $x_P$ = planetary reference measurement.
- $R_i$ = a documented comparison scale.

This is appropriate only when both measurements represent comparable physical quantities and have compatible units and meanings.

Method C — Classification-based comparisons

Some characteristics are better represented as categories.

For example:

- Basaltic terrain.
- Clay-bearing geological environment.
- Sulfate-bearing environment.
- Polar desert.
- Salt-rich surface.

For these, compare the presence, absence and confidence of relevant characteristics rather than inventing numerical distances.

### My recommendation

Use a combination of Methods A, B and C.

Keep the scoring methodology transparent. Show individual scores, data availability and confidence alongside the overall ranking.

Also introduce a missing-data rule: missing observations must not automatically count as a poor match or be silently treated as zero.

## 7.3. One additional feature that would make your project considerably better

Introduce a separate Analogy Limitations Scorecard.

For every candidate, distinguish between:

| Comparison dimension | Interpretation |
| --- | --- |
| Geological similarity | How comparable are the relevant materials and geological processes? |
| Environmental similarity | How comparable are the measured environmental conditions? |
| Operational similarity | Can the location help test specific equipment or procedures? |
| Planetary mismatch | Which essential planetary conditions cannot be reproduced? |

For example, Antarctica could be useful for investigating extreme cold and certain geological or biological processes.

However, it cannot reproduce the lunar vacuum, lunar gravity or radiation environment.

Similarly, a volcanic field could be useful for investigating basaltic terrain and rover mobility but would not reproduce the Martian atmosphere.

This approach prevents the application from producing misleading conclusions.

# 8. Technical architecture and Python development strategy

The biggest risk for your team is trying to develop too much software infrastructure.

I recommend a simple architecture in which each component has a clearly defined responsibility.

## 8.1. Technology stack

| Layer | Recommended technology | Purpose |
| --- | --- | --- |
| Programming | Python 3.12+ | Main development language |
| Data manipulation | pandas, NumPy | Data cleaning and calculations |
| Earth data acquisition | earthaccess | NASA Earthdata search and access |
| Raster processing | Rasterio, xarray | Processing satellite and elevation data |
| GIS | GeoPandas, Shapely | Geographic operations |
| Scientific calculations | SciPy, scikit-learn | Statistical analysis and optional clustering |
| Interactive maps | Folium | Geographic visualization |
| Charts | Plotly | Interactive scientific graphs |
| User interface | Streamlit | Entire application interface |
| Storage | CSV, GeoJSON, GeoPackage | Candidate data and results |
| Version control | Git / GitHub | Team collaboration |

I would avoid PostgreSQL/PostGIS for this particular prototype. A local GeoPackage and CSV files should be sufficient.

Likewise, I would not introduce Docker, microservices or cloud infrastructure unless you already have experience with them.

## 8.2. Example project structure

text

```text
terraanalog-explorer/
│
├── app.py
│
├── pages/
│   ├── planetary_targets.py
│   ├── earth_discovery.py
│   ├── comparison.py
│   └── scientific_reports.py
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── reference/
│
├── src/
│   ├── data_loader.py
│   ├── geospatial.py
│   ├── mineralogy.py
│   ├── terrain.py
│   ├── scoring.py
│   └── reporting.py
│
├── outputs/
│   ├── maps/
│   ├── charts/
│   └── reports/
│
├── requirements.txt
└── README.md
```

This is only a suggested structure. You can simplify it further during the hackathon.

## 8.3. How to make development easier

I would use preprocessed reference datasets whenever possible.

For example, instead of attempting to download and process hundreds of satellite scenes during the hackathon:

1. Select a small number of locations.
2. Download relevant data for those locations.
3. Extract a few useful measurements.
4. Store the measurements in CSV or GeoPackage format.
5. Develop the application around those processed measurements.

This separates scientific data preparation from application development.

It also allows all three team members to work independently.

# 9. Division of responsibilities: Three-person team

I would divide the team by functional responsibility rather than having everyone work on the same application.

Person 1 — Earth observation and GIS

Data and geospatial specialist- Research terrestrial candidate locations.
- Retrieve NASA Earth observation datasets.
- Process elevation, terrain and surface observations.
- Produce standardized candidate-location datasets.
- Validate geographical information.

Main deliverable: `earth_candidates.csv` and associated geospatial files.

Person 2 — Planetary science and comparison

Scientific analysis specialist- Research the selected lunar and Martian environments.
- Retrieve relevant planetary reference data.
- Define comparison criteria.
- Implement similarity calculations.
- Document scientific limitations and uncertainties.

Main deliverable: `planetary_reference.csv`, scoring logic and scientific methodology.

Person 3 — Application and integration

Application and visualization specialist- Establish the Python project.
- Build the Streamlit application.
- Integrate maps and scientific charts.
- Connect the data-processing outputs.
- Prepare the final demonstration and presentation.

Main deliverable: Working TerraAnalog Explorer application.

### Important collaboration rule

Agree on the data format before starting independent development.

For example:

`earth_candidates.csv`

| location\_id | location\_name | latitude | longitude | elevation | slope | ndvi |
| --- | --- | --- | --- | --- | --- | --- |
| E001 | Candidate A | ... | ... | ... | ... | ... |
| E002 | Candidate B | ... | ... | ... | ... | ... |

`planetary_reference.csv`

| target\_id | target\_name | terrain\_type | mineralogy | temperature |
| --- | --- | --- | --- | --- |
| M001 | Jezero | ... | ... | ... |
| L001 | Lunar South Pole | ... | ... | ... |

These are illustrative schemas, not actual measurements.

By agreeing on the schema first, each person can develop their component without waiting for everyone else.

# 10. Two-day implementation plan

The biggest challenge is not coding. It is controlling the scope.

I would organize the 48-hour hackathon into six development phases.

## Day 1 — Research, data and core functionality

| Time | Person 1 | Person 2 | Person 3 |
| --- | --- | --- | --- |
| Hours 0–2 | Select Earth locations | Select Moon/Mars targets | Set up repository and application |
| Hours 2–5 | Retrieve Earth datasets | Retrieve planetary data | Build initial interface |
| Hours 5–8 | Process terrain and surface data | Define comparison criteria | Build map and data loading |
| Hours 8–12 | Export candidate profiles | Implement scoring algorithm | Integrate scoring and visualization |

End-of-day objective:

You should have:

- At least four processed terrestrial candidate locations.
- At least two planetary reference profiles.
- A functioning similarity calculation.
- A basic application displaying results.

Do not spend the entire first day trying to build a beautiful interface.

## Day 2 — Integration, scientific validation and presentation

| Time | Person 1 | Person 2 | Person 3 |
| --- | --- | --- | --- |
| Hours 12–16 | Validate geographical data | Validate scientific comparisons | Integrate all components |
| Hours 16–20 | Add additional candidates | Improve scoring and explanations | Complete map and charts |
| Hours 20–24 | Prepare location documentation | Document methodology | Finalize application |
| Hours 24–28 | Test data and outputs | Review scientific limitations | Fix integration problems |
| Hours 28–32 | Assist with presentation | Prepare scientific narrative | Record demonstration and screenshots |

This is a suggested allocation of working hours, not a requirement to work continuously without breaks.

### Minimum viable product

By the end of the hackathon, I would insist on having these six things:

1. A working Python application.
2. At least four terrestrial candidate locations.
3. At least two planetary reference environments.
4. A transparent similarity-ranking algorithm.
5. A map and comparison visualization.
6. A scientific explanation of similarities and limitations.

A small working application with real data is much better than a large unfinished platform.

# 11. AI tools and subscriptions

You mentioned that each team member can afford a subscription.

That is useful, but I would avoid buying several overlapping subscriptions just because they are available.

Here is what I would actually consider.

| Tool | Purpose | Mandatory? |
| --- | --- | --- |
| ChatGPT | Python assistance, scientific explanations, debugging | No |
| Claude | Code generation, reviewing architecture and long scientific documents | No |
| Cursor | AI-assisted development inside the IDE | No |
| GitHub | Version control and collaboration | Strongly recommended |
| QGIS | GIS inspection and geospatial visualization | Strongly recommended |
| Google Colab | Running Python notebooks without local setup | Optional |
| Streamlit Community Cloud | Hosting the final application | Optional |
| NASA Earthdata | Accessing relevant NASA observations | Dataset-dependent |

### Suggested subscription strategy

I would use:

- One primary AI coding assistant for the application developer.
- One AI assistant for scientific research and data interpretation.
- Free tools and accounts for the other team members.

You do not need three separate premium subscriptions to complete this project.

### One important warning about AI coding

Your AI assistants will be particularly helpful with:

- Writing Rasterio and GeoPandas code.
- Understanding NASA data formats.
- Building Streamlit interfaces.
- Debugging coordinate reference system issues.
- Implementing similarity metrics.
- Generating scientific documentation.

However, ask the AI to explain the code and the scientific assumptions rather than blindly accepting generated solutions.

You should be able to explain every major calculation during the final presentation.

# 12. Data acquisition: What I would actually download

I would prioritize the following data sources.

| Priority | Dataset | What to obtain | Why |
| --- | --- | --- | --- |
| 1 | NASA SRTM | Elevation data for selected Earth locations | Relatively straightforward terrain analysis |
| 2 | NASA HLS | Multispectral observations | Surface and vegetation characterization |
| 3 | NASA EMIT | Surface mineral identification | Particularly useful for Mars comparisons |
| 4 | Mars CRISM | Selected mineralogical products | Planetary reference |
| 5 | Mars MOLA / CTX | Elevation and surface imagery | Terrain comparison |
| 6 | LRO Diviner | Lunar thermal observations | Lunar environmental comparison |

The independent catalogue provides useful entry points and Python examples for these datasets.

Space Data Atlas

### Suggested download strategy

First three hours:

- Start with SRTM.
- Download elevation data for four terrestrial regions.
- Obtain one or two relevant HLS observations if access is straightforward.
- Obtain one planetary reference dataset.

After the core application works:

- Add EMIT mineralogical observations.
- Add CRISM comparisons.
- Add lunar thermal characteristics if your chosen lunar use case requires them.

EMIT and CRISM are particularly interesting, but I would not let unfamiliar hyperspectral data formats jeopardize the entire project.

Also, NASA Earthdata registration and download access can introduce friction. Check the required account and data access before the hackathon, and cache the data locally.

# 13. Potential pitfalls and how to avoid them

| Risk | Why it matters | Recommended mitigation |
| --- | --- | --- |
| Too many datasets | Data preparation consumes the hackathon | Start with two or three |
| Excessive geographical coverage | Global raster analysis can be computationally expensive | Use predefined regions |
| Incompatible planetary data | Earth, Mars and Moon observations have different resolutions and measurement methods | Compare derived characteristics, not arbitrary raw values |
| False scientific conclusions | Similarity does not establish equivalence | Explain uncertainty and limitations |
| Overengineering | Application development can consume all available time | Build the simplest functional interface |
| AI-generated inaccuracies | LLMs can invent scientific relationships | Verify every important scientific claim |
| Team integration problems | Independently developed modules may use incompatible formats | Agree on schemas during the first hour |
| Internet dependency | Data downloads or hosted applications might fail | Cache datasets and prepare a local demonstration |

## 13.1. One particularly important scientific distinction

I would separate three concepts throughout your application:

Environmental analog: An Earth location shares certain environmental characteristics with a planetary environment.

Geological analog: An Earth location exhibits geological materials or processes relevant to the planetary environment.

Operational analog: An Earth location can be used to test equipment, procedures or exploration technologies.

These are not interchangeable.

For example, an environment can be an excellent geological analog but a poor operational analog.

Your application should allow these three dimensions to be assessed independently.

That would be a particularly good scientific design decision.

# 14. Alternative: If you want something less software-intensive

If you reach the hackathon and discover that the application development is taking too much time, there is another approach I would seriously consider.

Build a Planetary Analog Research Portfolio instead.

This would consist of:

- A curated database of terrestrial analog sites.
- Scientific comparison reports.
- Processed NASA datasets.
- A collection of comparative charts.
- A GIS project containing candidate locations.
- A Python notebook implementing the similarity methodology.
- A small Streamlit interface for browsing the results.

The primary deliverable would be a scientific research product rather than a sophisticated application.

It would still satisfy the challenge's intended objectives: identifying, characterizing and explaining terrestrial analog environments.

It could also be easier to complete and validate in two days.

# 15\. Final comparison and recommendation

Here is the consolidated ranking, including how I would prioritize the projects under your team's constraints.

| Rank | Project | Solution format | Difficulty | Estimated person-hours | Python suitability | Two-day feasibility |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | TerraAnalog Explorer | Interactive web app + scientific ranking engine | Intermediate | 40–55 | Excellent | High, with controlled scope |
| 2 | MarsMatch | Mineralogical comparison tool | Intermediate | 35–50 | Excellent | High, if limited to selected locations |
| 3 | AnalogQuest | Geographic discovery and ranking engine | Intermediate | 35–50 | Excellent | High, with predefined regions |
| 4 | Terrain Twin | Comparative digital terrain model | Intermediate | 30–45 | Excellent | High |
| 5 | Analog Mission Planner | Scientific decision-support application | Intermediate | 30–40 | Excellent | Very high |
| 6 | Planetary Analog Atlas | Digital atlas and research catalogue | Beginner/Youth | 20–30 | Excellent | Very high |
| 7 | AnalogAI | AI-assisted scientific research platform | Advanced | 45–60 | Excellent | Moderate |

## 15.1. Which one should you actually build?

My recommendation is to combine:

- TerraAnalog Explorer as the main application.
- MarsMatch as its mineralogical comparison capability.
- Analog Mission Planner as its practical application.

The result would be one cohesive project, not three separate applications.

I would call the final product:

# TerraAnalog Explorer: Finding Earth's Next Planetary Test Sites

The proposed scope would be:

- Two planetary reference environments: Jezero Crater and the lunar South Pole.
- Six terrestrial candidate locations.
- Three primary data dimensions: mineralogy, terrain and surface characteristics.
- One optional fourth dimension: thermal conditions.
- A transparent weighted similarity model.
- An interactive map.
- Individual scientific profiles.
- A mission-usefulness assessment.
- A limitations and uncertainty section.

Difficulty: Intermediate.

Estimated total effort: Approximately 45–55 person-hours.

Mandatory paid tools: None.

Main programming language: Python.

Application framework: Streamlit.

Main scientific libraries: GeoPandas, Rasterio, NumPy, pandas and Plotly.

Main data sources: NASA SRTM, HLS, EMIT, CRISM and relevant planetary topography products.

## 15.2. What would make the project genuinely useful?

I would concentrate on one feature that distinguishes it from a generic planetary visualization application:

Every location should answer the question: What specific scientific or engineering experiment could this place help prepare us for?

For example:

| Earth environment | Potential experiment | Planetary relevance |
| --- | --- | --- |
| Volcanic basaltic terrain | Rover mobility and geological sampling | Moon / Mars |
| Extremely arid desert | Autonomous operations and surface-material analysis | Mars |
| Polar desert | Extreme-environment instrument testing | Mars / Moon |
| Salt-rich environment | Mineralogical analysis and resource characterization | Mars |
| Cave or lava tube | Subsurface exploration robotics | Moon / Mars |

These are proposed research applications, not claims that every location is already validated for those experiments.

This creates a connection between planetary science and practical exploration engineering.

# 16\. My final advice before the hackathon

I would make three decisions before November 14.

1. Choose the final project scope. I recommend TerraAnalog Explorer, with MarsMatch as an additional feature if time allows.
2. Prepare your development environment and data access. Install the Python libraries, create the GitHub repository and check NASA Earthdata access.
3. Agree on the scientific methodology. Decide what you are comparing, how similarity will be calculated and what counts as a meaningful analog.

One final consideration: the official challenge resources are particularly important. Since the independent catalogue was refreshed ahead of the November 13 official resource release, check the actual Resources tab and select at least one dataset explicitly listed there. The six datasets discussed above are excellent candidates, but their inclusion in the official tab should not be assumed.

The most important thing: Don't try to build NASA's planetary exploration infrastructure in 48 hours. Build a small scientific instrument that answers one interesting question exceptionally well.

A working discovery tool that finds and scientifically explains six interesting terrestrial environments would be a very satisfying hackathon result, even without sophisticated AI, machine learning or complex software architecture.
