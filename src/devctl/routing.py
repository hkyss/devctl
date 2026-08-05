from .profiles import ProjectProfile
from .settings import Settings


def domain_for(settings: Settings, profile: ProjectProfile) -> str:
    import os

    user = os.environ.get("USER") or os.environ.get("USERNAME") or "user"
    if settings.dns_suffix == "localhost":
        return (profile.domain or f"{profile.name}.localhost").replace("${USER}", user)
    return (profile.domain or f"{profile.name}.{user}.{settings.dns_suffix}").replace("${USER}", user)


def url_for(settings: Settings, profile: ProjectProfile) -> str:
    return f"{settings.url_scheme}://{domain_for(settings, profile)}"
