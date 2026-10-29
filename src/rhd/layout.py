"""Which tab each data set belongs on. Order is importance order."""

CI_SERVER = "ci.ros2.org"
BUILD_SERVER = "build.ros2.org"
DISTROS = [  # (distro, build.ros2.org view, label)
    ("rolling", "Rci", "Rolling"),
    ("lyrical", "Lci", "Lyrical"),
    ("kilted", "Kci", "Kilted"),
    ("jazzy", "Jci", "Jazzy"),
    ("humble", "Hci", "Humble"),
]


def tab_for(server: str, grp: str) -> str:
    """Tab slug for a Jenkins section."""
    if server == CI_SERVER and grp == "nightly":
        return "ci"
    for distro, view, _ in DISTROS:
        if server == BUILD_SERVER and grp == view:
            return distro
    return f"{server}-{grp}".replace(".", "-")
