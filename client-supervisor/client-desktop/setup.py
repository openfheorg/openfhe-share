from setuptools import find_packages, setup

setup(
    name="share-client-desktop",
    version="0.4.0",
    description="SHARE Client desktop supervisor with login-assigned provisioning, NVFlare management, and an embedded local Results API.",
    package_dir={"": "src"},
    packages=find_packages("src"),
    include_package_data=True,
    package_data={"share_desktop": ["assets/icons/*", "assets/branding/*"]},
    python_requires=">=3.10",
    install_requires=[
        "PySide6>=6.7,<7",
        "requests>=2.31,<3",
        "fastapi>=0.115,<1",
        "uvicorn[standard]>=0.32,<1",
        "pydantic>=2.10,<3",
    ],
    entry_points={
        "console_scripts": [
            "share-client-desktop=share_desktop.main:main",
            "duality-client-desktop=share_desktop.main:main",
        ]
    },
)
