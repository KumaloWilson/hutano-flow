"""Run inside the API environment to generate 300 timestamped synthetic journeys."""
from app.cli import generate_completed_visits

generate_completed_visits(count=300, seed=2026)

