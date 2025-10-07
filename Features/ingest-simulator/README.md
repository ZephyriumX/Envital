# 🌍 Envital

Envital is a **geo-aware health intelligence system** that simulates wearable data, ingests it into a backend, detects anomalies, and visualizes health risks on an interactive city heatmap.

Built for real-time health monitoring and hackathon demo purposes.

---

## 🚀 Features (Planned / In Progress)

- ✅ **Wearable Data Simulator** (HR, SpO₂, steps, GPS) with anomaly injection
- ⏳ **Data Ingestion API** (`/ingest_event`) via FastAPI
- ⏳ **Anomaly Detection Models** (rule-based, Isolation Forest, LSTM Autoencoder)
- ⏳ **Geo Heatmap Dashboard** (Streamlit + H3 + Mapbox)
- ⏳ **Recovery Score Calculation**
- ✅ GitHub Project Board for task tracking

---

## 📂 Repository Structure

```
ingest-simulator/
└── data/
├── simulator.py # Wearable data simulator
└── samples/ # Generated sample JSONL events
└── scripts/
└── validate_events.py # Validate JSONL event schema
```

---

## ⚡ Quickstart

### 1. Clone repo & setup venv

```bash
git clone https://github.com/Uttam1611/Envital.git
cd Envital

python -m venv .venv
source .venv/bin/activate   # Linux/Mac
.\.venv\Scripts\activate    # Windows PowerShell

pip install -r requirements.txt
```

### 2. Run Data Simulator

```bash
# Print events to console
python data/simulator.py --users 3 --minutes 1

# Save events to JSONL file
python data/simulator.py --users 3 --minutes 1 --out data/samples/events.jsonl

# Validate events
python scripts/validate_events.py < data/samples/events.jsonl
```

### 3. Run Backend (future)

```bash
uvicorn backend.main:app --reload
```

### 4. Run Dashboard (future)

```bash
streamlit run dashboards/geo_heatmap.py
```

---

## 🛠️ Development Workflow

- **Branches**
  - `main` → stable, release-ready
  - `dev` → active development
  - `feature/*` → each feature/issue branch
- **PRs**: Open from `feature/*` → `dev`. Use Conventional Commit messages:
  - `feat:` new feature
  - `fix:` bug fix
  - `chore:` infra / configs
  - `test:` test cases
- **Issues**: All tasks are tracked in GitHub Project board.

---

## 📊 Example Event JSON

```json
{
  "id": "c63f83...",
  "timestamp": "2025-10-07T14:22:05Z",
  "user_id": "user_1",
  "hr": 75,
  "spo2": 97,
  "steps": 12,
  "lat": 28.6123,
  "lon": 77.2099
}
```

---

## 🔮 Roadmap

- [ ] Finish ingestion API and DB schema
- [ ] Implement anomaly detection models
- [ ] Build geo heatmap visualization
- [ ] Integrate recovery score
- [ ] Polish Streamlit dashboard for demo

---

## 👥 Team

- **Uttam Singh** — Geo Heatmap, Simulator, Preprocessing
- **Mehul** — Anomaly Detection, Recovery Score, Backend Core

---

## 📜 License

MIT License. See [LICENSE](LICENSE).
