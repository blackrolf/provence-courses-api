# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Provence Courses API is a FastAPI-based service for optimizing delivery routes using OR-Tools VRP solver. The API handles tour generation, optimization, and management for a logistics/delivery system.

## Key Commands

### Running the API
```bash
# Development mode with auto-reload
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Production mode (via systemd service)
sudo systemctl start provence-courses-api
sudo systemctl status provence-courses-api
sudo systemctl restart provence-courses-api

# Monitor logs in real-time
./monitor_logs.sh
# or
sudo journalctl -u provence-courses-api -f
```

### Testing
```bash
# Run all tests
python3 -m pytest

# Run specific test file
python3 -m pytest test_filename.py

# Run with verbose output
python3 -m pytest -v
```

### Dependencies
```bash
# Install/update dependencies
pip install -r requirements.txt

# Activate virtual environment
source venv/bin/activate
```

## Architecture Overview

### Core Components

1. **API Layer** (`app/api/v1/routes/`)
   - `tours.py`: Main tour management endpoints including generation, optimization, and testing endpoints

2. **Services Layer** (`app/services/tours/`)
   - `or_tools_vrp_solver.py` / `or_tools_vrp_solver_v3.py`: OR-Tools VRP optimization implementation
   - `data_retriever.py`: Supabase data access layer
   - `route_generator.py`: Tour generation logic
   - `daily_processor.py`: Daily batch processing
   - `optimization_orchestrator.py`: Coordinates optimization workflow
   - `directions_enricher.py`: Enriches routes with directions data
   - `osrm_distance_matrix.py`: OSRM integration for distance calculations
   - `solution_saver_v4.py`: Persists optimization results to database
   - `tour_reconstructor.py` / `tour_reconstructor_v2.py`: Rebuilds tour structure from optimization results

3. **Data Models** (`app/models/`)
   - Request/response models for API endpoints
   - Domain models for tours and shipments

4. **Integration Layer** (`app/integrations/`)
   - External service integrations (Supabase, OSRM, Google Maps)

### Key Workflows

1. **Tour Generation & Optimization Flow**:
   - Retrieve shipments from Supabase
   - Generate initial tour structure
   - Apply OR-Tools VRP solver for optimization
   - Enrich with directions/distance data
   - Save optimized solution back to Supabase

2. **Two-Phase Optimization**:
   - Phase 1: Optimize with relaxed constraints
   - Phase 2: Re-optimize with full constraint set

### Environment Configuration

Required environment variables (in `.env`):
- `SUPABASE_URL`: Supabase instance URL
- `SUPABASE_ANON_KEY`: Supabase anonymous key
- `SUPABASE_SERVICE_ROLE_KEY`: Supabase service role key
- `OSRM_URL`: OSRM server URL (default: http://localhost:5000)
- `GOOGLE_MAPS_API_KEY`: Google Maps API key (optional)
- `API_KEY`: API authentication key

### Database Schema

The system uses Supabase with key tables:
- `routes`: Tour/route definitions
- `route_stops`: Individual stops in routes
- `shipments`: Shipment/delivery records
- `locations`: Address/location data
- `laboratories`: Laboratory/client information

### API Authentication

All endpoints require API key authentication via the `verify_api_key` dependency. Pass the API key in request headers or as a parameter.

### Important Notes

- The system is deployed as a systemd service (`provence-courses-api.service`)
- Logs are written to systemd journal and `api.log`
- The optimization engine uses OR-Tools with custom constraints for time windows, capacity, and vehicle routing
- OSRM is used for distance matrix calculations when available, falling back to Google Maps API