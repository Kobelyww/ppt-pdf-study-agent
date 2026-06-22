from __future__ import annotations


class HealthCheckService:
    def check(self, components: dict[str, bool]) -> dict[str, object]:
        component_status = {
            name: "available" if available else "unavailable"
            for name, available in components.items()
        }
        overall = "ok" if all(components.values()) else "degraded"
        return {"status": overall, "components": component_status}
