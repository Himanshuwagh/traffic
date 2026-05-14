# 🚦 Traffic Intelligence Platform

A real-time urban traffic monitoring and analysis system. This guide will help you deploy the platform to the cloud.

 Done fetch states (fetch_india_districts.py):   Maharashtra, Andhra Pradesh, Karnataka

## 🚀 Quick Deployment Guide

Follow these steps in order to get your system running in the cloud.

### 1. Database (Supabase)
We use Supabase because it supports **PostGIS** (spatial data).

1.  **Create a Project**: Log in to [Supabase](https://supabase.com/) and create a new project.
2.  **Enable PostGIS**: 
    *   In your Supabase dashboard, go to **Database** (left sidebar) -> **Extensions**.
    *   Search for `postgis` and click the toggle to enable it. **This is required for map data.**
3.  **Get Connection String**:
    *   Go to **Project Settings** (gear icon) -> **Database**.
    *   Find the **Connection string** section. 
    *   Copy the **URI** format. It looks like: `postgresql://postgres.[ID]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:5432/postgres`
    *   **Tip**: Add `?sslmode=require` to the end of this string if it's not there.

---

### 2. Backend API (Render)
The backend is a Python (FastAPI) service.

1.  **Connect GitHub**: Go to [Render](https://render.com/), create a new **Web Service**, and connect this GitHub repo.
2.  **Configure**:
    *   **Name**: `traffic-api` (or any name).
    *   **Root Directory**: `backend`
    *   **Runtime**: `Python 3`
    *   **Build Command**: `pip install -r requirements.txt`
    *   **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
3.  **Environment Variables**:
    *   `DATABASE_URL`: Your Supabase connection string from Step 1.
    *   `GOOGLE_API_KEY`: Your Google Maps API key.
    *   `ALLOWED_ORIGINS`: Set this to `*` for now, or your Vercel URL later for better security.

---

### 3. Frontend (Vercel)
The frontend is a React app built with Vite.

1.  **Connect GitHub**: Go to [Vercel](https://vercel.com/), import your repo.
2.  **Configure**:
    *   **Framework Preset**: `Vite`
    *   **Root Directory**: `frontend`
3.  **Environment Variables**:
    *   `VITE_MAPBOX_TOKEN`: Your Mapbox public token.
    *   `VITE_API_BASE_URL`: The URL of your Render backend (e.g., `https://traffic-api.onrender.com`).
4.  **Deploy**: Click deploy!

---

### 4. Hourly Updates (GitHub Actions)
To keep the traffic data fresh, GitHub Actions runs the TomTom hotspot-first ingestion job every hour.

1.  In your GitHub repo, go to **Settings** -> **Secrets and variables** -> **Actions**.
2.  Add two **Repository secrets**:
    *   `DATABASE_URL`: Same as Step 1.
    *   `TOMTOM_API_KEY`: Your TomTom API key.
3.  The workflow is already set up in `.github/workflows/traffic-ingestion.yml`. It runs automatically every hour and only ingests when a discovery, tracking, or baseline window is due.

The ingestion schedule is:
*   Discovery: peak hours only, hourly per supported city.
*   Tracking: active hotspot boxes every 3 hours.
*   Baseline: off-peak samples at 13:00 and 22:00 IST.

---

## 📊 Data Management

### "I already have data in my database!"
If you already have road segments and signals data in your Supabase DB, **you do not need to run the fetch scripts again.** 

The app is designed to:
1.  **Read** from your existing road geometry tables.
2.  **Update** normalized TomTom traffic observations hourly only when scheduled.
3.  **Serve past date/time map views** from stored `traffic_observations`, not live provider calls.

**Do not run** `python fetch_segments.py`, `python fetch_signals.py`, or `python fetch_india_districts.py` if your database is already populated. These are static reference imports and are not required for recurring TomTom traffic ingestion.

### "My database is empty, how do I start?"
If you are starting with a fresh database:
1.  Run the backend once (on Render or locally). It will automatically create the tables.
2.  (Optional) Run `python backend/fetch_segments.py` locally once to load the road network.
3.  (Optional) Run `python backend/fetch_signals.py` locally once to load traffic signals.

---

## 🛠 Security Reminders
*   **Rotate Keys**: If you accidentally commit your `.env` file, rotate your Supabase password, Google API key, and Mapbox token immediately.
*   **CORS**: Once your frontend is live on Vercel, update the `ALLOWED_ORIGINS` in Render to match your Vercel URL for better security.
