from fastapi import HTTPException

from app.models import ServiceEpisode, User, Visit
from app.security import role_names

OPERATIONAL_ROLES = {"ADMIN", "RECEPTIONIST", "TRIAGE_NURSE", "CLINICIAN", "SERVICE_PROVIDER", "PHARMACY"}
CLINICAL_ROLES = {"TRIAGE_NURSE", "CLINICIAN"}


def operational(user: User) -> None:
    if not role_names(user) & OPERATIONAL_ROLES:
        raise HTTPException(403, "Research access is limited to de-identified aggregates")


def allowed_services(user: User) -> set[str]:
    roles = role_names(user)
    if "ADMIN" in roles or "CLINICIAN" in roles or "RECEPTIONIST" in roles:
        return {"registration", "triage", "consultation", "pharmacy", "laboratory", "discharge"}
    result = set()
    if "TRIAGE_NURSE" in roles:
        result |= {"triage", "consultation"}
    if "SERVICE_PROVIDER" in roles:
        result |= {"consultation", "laboratory", "discharge"}
    if "PHARMACY" in roles:
        result.add("pharmacy")
    return result


def can_access_visit(user: User, visit: Visit) -> bool:
    operational(user)
    if role_names(user) & {"ADMIN", "RECEPTIONIST", "CLINICIAN", "TRIAGE_NURSE"}:
        return True
    return any(ep.service_point.type in allowed_services(user) for ep in visit.episodes)


def service_action(user: User, episode: ServiceEpisode) -> None:
    roles = role_names(user)
    permitted = set()
    if "CLINICIAN" in roles:
        permitted |= {"consultation", "triage", "laboratory", "discharge"}
    if "TRIAGE_NURSE" in roles:
        permitted.add("triage")
    if "PHARMACY" in roles:
        permitted.add("pharmacy")
    if "SERVICE_PROVIDER" in roles:
        permitted |= {"consultation", "laboratory", "discharge"}
    if episode.service_point.type not in permitted:
        raise HTTPException(403, "This service point is outside your assigned role")

