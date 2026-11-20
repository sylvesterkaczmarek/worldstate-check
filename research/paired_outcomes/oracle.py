"""Reference outcomes computed from private worker logs and high-rate simulator state."""


def label(episode):
    truth = episode["reference"]
    if episode["domain"] == "deployment":
        before = truth["pre_request"]
        if (
            episode["requires_transition"]
            and before["worker"] == truth["requested"]
            and before["actual"] == truth["expected"]
        ):
            return False
        return all(
            row["worker"] == truth["requested"] and row["actual"] == truth["expected"]
            for row in truth["requests"]
        )
    radius, target_z, dz = truth["tolerance"]
    x0, y0, z0 = truth["pre_position"]
    if (
        episode["requires_transition"]
        and x0 * x0 + y0 * y0 <= radius * radius
        and abs(z0 - target_z) <= dz
    ):
        return False
    positions = truth["positions"]
    return (
        all(
            x * x + y * y <= radius * radius and abs(z - target_z) <= dz
            for x, y, z in positions
        )
        and truth["tray_contact"]
    )
